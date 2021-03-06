#!/usr/bin/env python

# THIS FILE IS PART OF THE CYLC SUITE ENGINE.
# Copyright (C) 2008-2018 NIWA
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
"""Task to cylc progress messaging."""

import os
import sys
from time import sleep
from cylc.remote import remrun
from cylc.wallclock import get_current_time_string
import cylc.flags

from cylc.suite_srv_files_mgr import (
    SuiteSrvFilesManager, SuiteServiceFileError)
from cylc.task_outputs import TASK_OUTPUT_STARTED, TASK_OUTPUT_SUCCEEDED


class TaskMessage(object):

    """Send task (job) output messages."""

    CYLC_JOB_PID = "CYLC_JOB_PID"
    CYLC_JOB_INIT_TIME = "CYLC_JOB_INIT_TIME"
    CYLC_JOB_EXIT = "CYLC_JOB_EXIT"
    CYLC_JOB_EXIT_TIME = "CYLC_JOB_EXIT_TIME"
    CYLC_MESSAGE = "CYLC_MESSAGE"

    ABORT_MESSAGE_PREFIX = "Task job script aborted with "
    FAIL_MESSAGE_PREFIX = "Task job script received signal "
    VACATION_MESSAGE_PREFIX = "Task job script vacated by signal "

    NORMAL = "NORMAL"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"
    CUSTOM = "CUSTOM"
    SEVERITIES = (NORMAL, WARNING, CRITICAL, CUSTOM)

    MSG_RETRY_INTVL = 5.0
    MSG_MAX_TRIES = 7
    MSG_TIMEOUT = 30.0

    def __init__(self, severity=NORMAL):
        if severity in self.SEVERITIES:
            self.severity = severity
        else:
            raise ValueError('Illegal message severity ' + severity)

        # load the environment
        self.env_map = dict(os.environ)

        # set some instance variables
        self.suite = self.env_map.get(SuiteSrvFilesManager.KEY_NAME)
        self.task_id = self.env_map.get('CYLC_TASK_ID')

        # Record the time the messaging system was called and append it
        # to the message, in case the message is delayed in some way.
        self.true_event_time = get_current_time_string(
            override_use_utc=self.env_map.get('CYLC_UTC') == 'True')

    def send(self, messages):
        """Send messages back to the suite."""
        self._print_messages(messages)
        self._update_job_status_file(messages)
        messages = [msg + ' at ' + self.true_event_time for msg in messages]
        try:
            self.env_map.update(
                SuiteSrvFilesManager().load_contact_file(self.suite))
        except (IOError, ValueError, SuiteServiceFileError):
            # No suite to communicate with, just print to stdout.
            if cylc.flags.debug:
                import traceback
                traceback.print_exc()
            return
        if self.env_map.get('CYLC_TASK_COMMS_METHOD') == 'ssh':
            self._send_by_ssh()
        else:
            self._send_by_remote_port(messages)

    def _print_messages(self, messages):
        """Print message to send."""
        if self.severity in [self.NORMAL, self.CUSTOM]:
            handle = sys.stdout
        else:
            handle = sys.stderr
        for message in messages:
            handle.write('%s %s - %s\n' % (
                self.true_event_time, self.severity, message))
        handle.flush()

    def _send_by_remote_port(self, messages):
        """Send message by talking to the daemon (remote?) port."""
        from cylc.network.httpclient import (
            SuiteRuntimeServiceClient, ClientError, ClientInfoError)

        # Convert time/duration into appropriate units
        retry_intvl = float(self.env_map.get(
            SuiteSrvFilesManager.KEY_TASK_MSG_RETRY_INTVL,
            self.MSG_RETRY_INTVL))
        max_tries = int(self.env_map.get(
            SuiteSrvFilesManager.KEY_TASK_MSG_MAX_TRIES,
            self.MSG_MAX_TRIES))

        client = SuiteRuntimeServiceClient(
            self.suite,
            owner=self.env_map.get(SuiteSrvFilesManager.KEY_OWNER),
            host=self.env_map.get(SuiteSrvFilesManager.KEY_HOST),
            port=self.env_map.get(SuiteSrvFilesManager.KEY_PORT),
            timeout=float(self.env_map.get(
                SuiteSrvFilesManager.KEY_TASK_MSG_TIMEOUT, self.MSG_TIMEOUT)),
            comms_protocol=self.env_map.get(
                SuiteSrvFilesManager.KEY_COMMS_PROTOCOL))
        for i in range(1, max_tries + 1):  # 1..max_tries inclusive
            try:
                for message in messages:
                    client.put_message(self.task_id, self.severity, message)
            except ClientError as exc:
                sys.stderr.write(
                    "%s WARNING - Send message: try %s of %s failed: %s\n" % (
                        get_current_time_string(), i, max_tries, exc))
                # Break if:
                # * Exhausted number of tries.
                # * Contact info file not found, suite probably not running.
                #   Don't bother with retry, suite restart will poll any way.
                if i >= max_tries or isinstance(exc, ClientInfoError):
                    # Issue a warning and let the task carry on
                    sys.stderr.write("%s WARNING - MESSAGE SEND FAILED\n" % (
                        get_current_time_string()))
                else:
                    sys.stderr.write(
                        "   retry in %s seconds, timeout is %s\n" % (
                            retry_intvl, client.timeout))
                    sleep(retry_intvl)
                    # Reset in case contact info or passphrase change
                    client.host = None
                    client.port = None
                    client.auth = None
            else:
                if i > 1:
                    # Continue to write to STDERR, so users can easily see that
                    # it has recovered from previous failures.
                    sys.stderr.write(
                        "%s INFO - Send message: try %s of %s succeeded\n" % (
                            get_current_time_string(), i, max_tries))
                break

    def _send_by_ssh(self):
        """Send message via SSH."""
        # The suite definition specified that this task should
        # communicate back to the suite by means of using
        # non-interactive ssh to re-invoke the messaging command on the
        # suite host.

        # The remote_run() function expects command line options
        # to identify the target user and host names:
        sys.argv.append(
            '--user=' + self.env_map[SuiteSrvFilesManager.KEY_OWNER])
        sys.argv.append(
            '--host=' + self.env_map[SuiteSrvFilesManager.KEY_HOST])
        if cylc.flags.verbose:
            sys.argv.append('-v')

        if self.env_map.get('CYLC_TASK_SSH_LOGIN_SHELL') == 'False':
            sys.argv.append('--no-login')
        else:
            sys.argv.append('--login')

        # Some variables from the task execution environment are
        # also required by the re-invoked remote command: Note that
        # $CYLC_TASK_SSH_MESSAGING is not passed through so the
        # re-invoked command on the remote side will not end up in
        # this code block.
        env = {}
        for var in [
                SuiteSrvFilesManager.KEY_NAME,
                SuiteSrvFilesManager.KEY_DIR_ON_SUITE_HOST,
                'CYLC_TASK_ID',
                'CYLC_UTC',
                'CYLC_VERBOSE']:
            # (no exception handling here as these variables should
            # always be present in the task execution environment)
            try:
                env[var] = self.env_map[var]
            except KeyError:
                pass

        # The path to cylc/bin on the remote end may be required:
        path = os.path.join(self.env_map['CYLC_DIR_ON_SUITE_HOST'], 'bin')

        # Return here if remote re-invocation occurred,
        # otherwise drop through to local messaging.
        # Note: do not sys.exit(0) here as the commands do, it
        # will cause messaging failures on the remote host.
        remrun(env=env, path=[path])

    def _update_job_status_file(self, messages):
        """Write messages to job status file."""
        job_log_name = os.getenv("CYLC_TASK_LOG_ROOT")
        if not job_log_name:
            return
        job_status_file = None
        try:
            job_status_file = open(job_log_name + ".status", "ab")
        except IOError:
            if cylc.flags.debug:
                import traceback
                traceback.print_exc()
            return
        for message in messages:
            if message == TASK_OUTPUT_STARTED:
                job_id = os.getppid()
                if job_id > 1:
                    # If os.getppid() returns 1, the original job process
                    # is likely killed already
                    job_status_file.write("%s=%s\n" % (
                        self.CYLC_JOB_PID, job_id))
                job_status_file.write("%s=%s\n" % (
                    self.CYLC_JOB_INIT_TIME, self.true_event_time))
            elif message == TASK_OUTPUT_SUCCEEDED:
                job_status_file.write(
                    ("%s=%s\n" % (self.CYLC_JOB_EXIT,
                                  TASK_OUTPUT_SUCCEEDED.upper())) +
                    ("%s=%s\n" % (
                        self.CYLC_JOB_EXIT_TIME, self.true_event_time)))
            elif message.startswith(self.FAIL_MESSAGE_PREFIX):
                job_status_file.write(
                    ("%s=%s\n" % (
                        self.CYLC_JOB_EXIT,
                        message[len(self.FAIL_MESSAGE_PREFIX):])) +
                    ("%s=%s\n" % (
                        self.CYLC_JOB_EXIT_TIME, self.true_event_time)))
            elif message.startswith(self.ABORT_MESSAGE_PREFIX):
                job_status_file.write(
                    ("%s=%s\n" % (
                        self.CYLC_JOB_EXIT,
                        message[len(self.ABORT_MESSAGE_PREFIX):])) +
                    ("%s=%s\n" % (
                        self.CYLC_JOB_EXIT_TIME, self.true_event_time)))
            elif message.startswith(self.VACATION_MESSAGE_PREFIX):
                # Job vacated, remove entries related to current job
                job_status_file_name = job_status_file.name
                job_status_file.close()
                lines = []
                for line in open(job_status_file_name):
                    if not line.startswith("CYLC_JOB_"):
                        lines.append(line)
                job_status_file = open(job_status_file_name, "wb")
                for line in lines:
                    job_status_file.write(line)
                job_status_file.write("%s=%s|%s|%s\n" % (
                    self.CYLC_MESSAGE, self.true_event_time, self.severity,
                    message))
            else:
                job_status_file.write("%s=%s|%s|%s\n" % (
                    self.CYLC_MESSAGE, self.true_event_time, self.severity,
                    message))
        try:
            job_status_file.close()
        except IOError:
            if cylc.flags.debug:
                import traceback
                traceback.print_exc()
