#!/usr/bin/python

"""
Task base class for the Ecoconnect Controller.

A "task" represents a particular group of external jobs, for a single
reference time, that we want separate scheduling control over (as a
group).  Each task has certain prerequisites that must be satisfied
before it can launch its external task, and certain postrequisites that
are created or achieved as the task runs, and which may be prerequisites
for other tasks.  A task must maintain an accurate representation of
the task's state as it follows through to the end of processing for its
reference time.  

tasks communicate with each other in order to sort out inter-task
dependencies (i.e. match postrequisites with prerequisites).

Task names must not contain underscores at the moment (the 'name'
attribute, not the class name itself, that is).
"""

import reference_time
from requisites import requisites, timed_requisites, fuzzy_requisites
from time import sleep

import os
import re
import sys
from copy import deepcopy
from time import strftime
import Pyro.core

import logging
import logging.handlers

#----------------------------------------------------------------------
class task_base( Pyro.core.ObjBase ):
    "task base class"
    
    name = "task base class"

    def __init__( self, ref_time, initial_state ):
        # Call this AFTER derived class initialisation
        #   (it alters requisites based on initial state)
        # Derived classes MUST call nearest_ref_time()
        #   before defining their requisites

        task_base.processing_required = True

        Pyro.core.ObjBase.__init__(self)

        self.log = logging.getLogger( "main." + self.name ) 

        self.latest_message = ""
        self.abdicated = False # True => my successor has been created

        # initial states: waiting, ready, running, finished
        if not initial_state:
            self.state = "waiting"
            pass
        elif initial_state == "waiting": 
            self.state = "waiting"
        elif initial_state == "finished":  
            self.postrequisites.set_all_satisfied()
            self.log.warning( self.identity() + " starting in FINISHED state" )
            self.state = "finished"
        elif initial_state == "ready":
            # waiting, but ready to go
            self.state = "waiting"
            self.log.warning( self.identity() + " starting in READY state" )
            self.prerequisites.set_all_satisfied()
        else:
            self.log.critical( "unknown initial task state: " + initial_state )
            sys.exit(1)

    def nearest_ref_time( self, rt ):
        # return the next time >= rt for which this task is valid
        rh = int( rt[8:10])
        
        incr = None

        first_vh = self.valid_hours[ 0 ]
        extra_vh = 24 + first_vh 
        foo = self.valid_hours
        foo.append( extra_vh )

        for vh in foo:
            if rh <= vh:
                incr = vh - rh
                break
    
        nearest_rt = reference_time.increment( rt, incr )
        return nearest_rt


    def next_ref_time( self ):
        # return the next time that this task is valid at
        n_times = len( self.valid_hours )
        if n_times == 1:
            increment = 24
        else:
            i_now = self.valid_hours.index( int( self.ref_time[8:10]) )
            # list indices start at zero
            if i_now < n_times - 1 :
                increment = self.valid_hours[ i_now + 1 ] - self.valid_hours[ i_now ]
            else:
                increment = self.valid_hours[ 0 ] + 24 - self.valid_hours[ i_now ]

        return reference_time.increment( self.ref_time, increment )


    def run_if_ready( self, tasks, dummy_clock_rate ):

        # don't run if any previous instance not finished
        for task in tasks:
            if task.name == self.name:
                if task.state != "finished":
                    if int( task.ref_time ) < int( self.ref_time ):
                        self.log.debug( self.identity() + " blocked by " + task.identity() )
                        return

        if self.state == "finished":
            # already finished
            pass
        elif self.state == "running":
            # already running
            pass
        elif self.prerequisites.all_satisfied():
            # prerequisites all satisified, so run me
            if dummy_clock_rate:
                # we're in dummy mode
                self.run_external_dummy( dummy_clock_rate )
            else:
                self.run_external_task()
        else:
            # still waiting
            pass

    def run_external_dummy( self, dummy_clock_rate ):
        # RUN THE EXTERNAL TASK AS A SEPARATE PROCESS
        self.log.info( "launching external dummy for " + self.ref_time )
        os.system( "./task_dummy.py " + self.name + " " + self.ref_time + " " + str(dummy_clock_rate) + " &" )
        self.state = "running"

    def run_external_task( self ):
        # DERIVED CLASSES MUST OVERRIDE THIS METHOD TO RUN THE EXTERNAL
        # TASK, AND SET self.state = "running"
        self.log.critical( "task base class run() should not be called" )

    def get_state( self ):
        return self.name + ": " + self.state

    def identity( self ):
        return self.name + "%" + self.ref_time

    def display( self ):
        return self.name + "(" + self.ref_time + ")"

    def set_finished( self ):
        # could do this automatically off the "name finished for ref_time" message
        self.state = "finished"

    def abdicate( self ):
        if self.state == "finished" and not self.abdicated:
            self.abdicated = True
            return True
        else:
            return False

    def get_satisfaction( self, tasks ):

        for task in tasks:
            self.prerequisites.satisfy_me( task.postrequisites )

    def will_get_satisfaction( self, tasks ):
        temp_prereqs = deepcopy( self.prerequisites )
        for task in tasks:
            temp_prereqs.will_satisfy_me( task.postrequisites )
    
        if not temp_prereqs.all_satisfied(): 
            return False
        else:
            return True

    def is_complete( self ):  # not needed?
        if self.postrequisites.all_satisfied():
            return True
        else:
            return False

    def is_running( self ): 
        if self.state == "running":
            return True
        else:
            return False

    def is_finished( self ): 
        if self.state == "finished":
            return True
        else:
            return False

    def get_postrequisites( self ):
        return self.postrequisites.get_requisites()

    def get_postrequisite_list( self ):
        return self.postrequisites.get_list()

    def get_postrequisite_times( self ):
        return self.postrequisites.get_times()

    def get_latest_message( self ):
        return self.latest_message

    def get_valid_hours( self ):
        return self.valid_hours

    def incoming( self, priority, message ):
        # receive all incoming pyro messages for this task 

        # print "HELLO FROM INCOMING: " + message

        task_base.processing_required = True

        self.latest_message = message

        if self.state != "running":
            # message from a task that's not supposed to be running
            self.log.warning( "MESSAGE FROM NON-RUNNING TASK: " + message )

        if self.postrequisites.requisite_exists( message ):
            # an expected postrequisite from a running task
            if self.postrequisites.is_satisfied( message ):
                self.log.warning( "POSTREQUISITE ALREADY SATISFIED: " + message )

            self.log.info( message )
            self.postrequisites.set_satisfied( message )

        else:
            # a non-postrequisite message, e.g. progress report
            if priority == "NORMAL":
                self.log.info( message )
            elif priority == "WARNING":
                self.log.warning( message )
            elif priority == "CRITICAL":
                self.log.critical( message )
            else:
                self.log.warning( message )

        if self.postrequisites.all_satisfied():
            self.set_finished()

#----------------------------------------------------------------------
class runahead_task_base( task_base ):
    # for tasks with no-prerequisites, e.g. downloader and nztide,
    # that would otherwise run ahead indefinitely: delay if we get
    # "too far ahead" based on number of existing finished tasks.

    def __init__( self, ref_time, initial_state = "waiting" ):

        self.MAX_FINISHED = 4
        task_base.__init__( self, ref_time, initial_state )

        # logging is set up by task_base
        self.log.info( self.identity() + " max runahead: " + str( self.MAX_FINISHED ) + " tasks" )


    def run_if_ready( self, tasks, dummy_clock_rate ):
        # don't run if too many previous finished instances exist
        delay = False

        old_and_finished = []
        if self.state == "waiting":
            for task in tasks:
               if task.name == self.name and task.state == "finished":
                   old_and_finished.append( task.ref_time )
                            
            if len( old_and_finished ) >= self.MAX_FINISHED:
                delay = True

        if delay:
            # the following gets logged every time the function is called
            # self.log.debug( self.identity() + " ready and waiting (too far ahead)" )
            pass

        else:
            task_base.run_if_ready( self, tasks, dummy_clock_rate )

#----------------------------------------------------------------------
class downloader( runahead_task_base ):
    "Met Office input file download task"

    """
    This task provides initial input to get things going: it starts
    running immediately and it completes when its outputs are ready
    for use by downstream tasks.
    """

    name = "downloader"
    valid_hours = [ 0, 6, 12, 18 ]

    def __init__( self, ref_time, initial_state = "waiting" ):
 
        # adjust reference time to next valid for this task
        self.ref_time = self.nearest_ref_time( ref_time )
        ref_time = self.ref_time
       
        hour = ref_time[8:10]

        # no prerequisites: this is The Initial Task
        self.prerequisites = requisites( self.name, [])

        lbc_06 = reference_time.decrement( ref_time, 6 )
        lbc_12 = reference_time.decrement( ref_time, 12 )

        if hour == "00":

            self.postrequisites = timed_requisites( self.name, [ 
                [0, self.name + " started for " + ref_time],
                [0.5, "file obstore_" + ref_time + ".um ready"],
                [1, "file bgerr" + ref_time + ".um ready"], 
                [106, "file lbc_" + lbc_12 + ".um ready"], 
                [122, "file 10mwind_" + ref_time + ".um ready"],
                [122.5, "file seaice_" + ref_time + ".um ready"],
                [199, "file dump_" + ref_time + ".um ready"], 
                [200, self.name + " finished for " + ref_time] ])

        elif hour == "12":

            self.postrequisites = timed_requisites( self.name, [ 
                [0, self.name + " started for " + ref_time],
                [0.5, "file obstore_" + ref_time + ".um ready"],
                [1, "file bgerr" + ref_time + ".um ready"], 
                [97, "file lbc_" + lbc_12 + ".um ready"],
                [98, self.name + " finished for " + ref_time] ])

        if hour == "06" or hour == "18":

            self.postrequisites = timed_requisites( self.name, [
                [0, self.name + " started for " + ref_time],
                [0, "file lbc_" + lbc_06 + ".um ready"],
                [0.5, "file obstore_" + ref_time + ".um ready"],
                [1, "file bgerr" + ref_time + ".um ready"],
                [2, self.name + " finished for " + ref_time] ])
 
        runahead_task_base.__init__( self, ref_time, initial_state )
           
#----------------------------------------------------------------------
class oper_to_topnet( runahead_task_base ):
    "connect separate operational system to a topnet task"

    """use instead of downloader"""

    name = "oper_to_topnet"
    valid_hours = [ 6, 18 ]

    def __init__( self, ref_time, initial_state = "waiting" ):
        
        # adjust reference time to next valid for this task
        self.ref_time = self.nearest_ref_time( ref_time )
        ref_time = self.ref_time
 
        # no prerequisites: this is The Initial Task
        self.prerequisites = requisites( self.name, [])

        self.postrequisites = timed_requisites( self.name, [
            [0, self.name + " started for " + ref_time],
            [1, "file tn_" + ref_time + ".nc ready"],
            [2, self.name + " finished for " + ref_time] ])

        runahead_task_base.__init__( self, ref_time, initial_state )

#----------------------------------------------------------------------
class nzlam( task_base ):

    name = "nzlam"
    valid_hours = [ 0, 6, 12, 18 ]

    def __init__( self, ref_time, initial_state = "waiting" ):

        # adjust reference time to next valid for this task
        self.ref_time = self.nearest_ref_time( ref_time )
        ref_time = self.ref_time
 
        hour = ref_time[8:10]

        lbc_06 = reference_time.decrement( ref_time, 6 )
        lbc_12 = reference_time.decrement( ref_time, 12 )

        if hour == "00" or hour == "12":
            self.prerequisites = requisites( self.name, [ 
                "file obstore_" + ref_time + ".um ready",
                "file bgerr" + ref_time + ".um ready",
                "file lbc_" + lbc_12 + ".um ready" ])

            self.postrequisites = timed_requisites( self.name, [ 
                [0, self.name + " started for " + ref_time],
                [30, "file sls_" + ref_time + ".um ready"],   
                [32, self.name + " finished for " + ref_time] ])
 
        elif hour == "06" or hour == "18":
            self.prerequisites = requisites( self.name, [ 
                "file obstore_" + ref_time + ".um ready",
                "file bgerr" + ref_time + ".um ready",
                "file lbc_" + lbc_06 + ".um ready" ])

            self.postrequisites = timed_requisites( self.name, [ 
                [0, self.name + " started for " + ref_time],
                [110, "file tn_" + ref_time + ".um ready"],
                [111, "file sls_" + ref_time + ".um ready"],   
                [112, "file met_" + ref_time + ".um ready"],
                [115, self.name + " finished for " + ref_time] ])

        task_base.__init__( self, ref_time, initial_state )

#----------------------------------------------------------------------
class nzlam_post( task_base ):

    name = "nzlam_post"
    valid_hours = [ 0, 6, 12, 18 ]

    def __init__( self, ref_time, initial_state = "waiting" ):

        # adjust reference time to next valid for this task
        self.ref_time = self.nearest_ref_time( ref_time )
        ref_time = self.ref_time

        hour = ref_time[8:10]

        if hour == "00" or hour == "12":
            
            self.prerequisites = requisites( self.name, [ 
                "file sls_" + ref_time + ".um ready" ])

            self.postrequisites = timed_requisites( self.name, [
                [0, self.name + " started for " + ref_time],
                [10, "file sls_" + ref_time + ".nc ready"],   
                [11, self.name + " finished for " + ref_time] ])

        elif hour == "06" or hour == "18":

            self.prerequisites = requisites( self.name, [ 
                "file tn_" + ref_time + ".um ready",
                "file sls_" + ref_time + ".um ready",   
                "file met_" + ref_time + ".um ready" ])

            self.postrequisites = timed_requisites( self.name, [ 
                [0, self.name + " started for " + ref_time],
                [10, "file sls_" + ref_time + ".nc ready"],   
                [20, "file tn_" + ref_time + ".nc ready"],
                [30, "file met_" + ref_time + ".nc ready"],
                [31, self.name + " finished for " + ref_time] ])

        task_base.__init__( self, ref_time, initial_state )

#----------------------------------------------------------------------
class globalprep( task_base ):

    name = "globalprep"
    valid_hours = [ 0 ]

    def __init__( self, ref_time, initial_state = "waiting" ):

        # adjust reference time to next valid for this task
        self.ref_time = self.nearest_ref_time( ref_time )
        ref_time = self.ref_time

        hour = ref_time[8:10]

        self.prerequisites = requisites( self.name, [ 
            "file 10mwind_" + ref_time + ".um ready",
            "file seaice_" + ref_time + ".um ready" ])

        self.postrequisites = timed_requisites( self.name, [
            [0, self.name + " started for " + ref_time],
            [5, "file 10mwind_" + ref_time + ".nc ready"],
            [7, "file seaice_" + ref_time + ".nc ready"],
            [10, self.name + " finished for " + ref_time] ])
       
        task_base.__init__( self, ref_time, initial_state )

#----------------------------------------------------------------------
class globalwave( task_base ):

    name = "globalwave"
    valid_hours = [ 0 ]

    def __init__( self, ref_time, initial_state = "waiting" ):

        # adjust reference time to next valid for this task
        self.ref_time = self.nearest_ref_time( ref_time )
        ref_time = self.ref_time
 
        self.prerequisites = requisites( self.name, [ 
            "file 10mwind_" + ref_time + ".nc ready",
            "file seaice_" + ref_time + ".nc ready" ])

        self.postrequisites = timed_requisites( self.name, [
            [0, self.name + " started for " + ref_time],
            [120, "file globalwave_" + ref_time + ".nc ready"],
            [121, self.name + " finished for " + ref_time] ])
 
        task_base.__init__( self, ref_time, initial_state )
       
#----------------------------------------------------------------------
class nzwave( task_base ):
    
    name = "nzwave"
    valid_hours = [ 0, 6, 12, 18 ]

    def __init__( self, ref_time, initial_state = "waiting" ):

        # adjust reference time to next valid for this task
        self.ref_time = self.nearest_ref_time( ref_time )
        ref_time = self.ref_time
 
        hour = ref_time[8:10]

        self.prerequisites = requisites( self.name, [ 
            "file sls_" + ref_time + ".nc ready" ])

        self.postrequisites = timed_requisites( self.name, [
            [0, self.name + " started for " + ref_time],
            [110, "file nzwave_" + ref_time + ".nc ready"],
            [112, self.name + " finished for " + ref_time] ])
 
        task_base.__init__( self, ref_time, initial_state )
       
#----------------------------------------------------------------------
class ricom( task_base ):

    name = "ricom"
    valid_hours = [ 6, 18 ]

    def __init__( self, ref_time, initial_state = "waiting" ):

        # adjust reference time to next valid for this task
        self.ref_time = self.nearest_ref_time( ref_time )
        ref_time = self.ref_time
 
        self.prerequisites = requisites( self.name, [ 
            "file sls_" + ref_time + ".nc ready" ])

        self.postrequisites = timed_requisites( self.name, [
            [0, self.name + " started for " + ref_time],
            [30, "file ricom_" + ref_time + ".nc ready"],
            [31, self.name + " finished for " + ref_time] ])
 
        task_base.__init__( self, ref_time, initial_state )
       
#----------------------------------------------------------------------
class mos( task_base ):

    name = "mos"
    valid_hours = [ 0, 6, 12, 18 ]

    def __init__( self, ref_time, initial_state = "waiting" ):

        # adjust reference time to next valid for this task
        self.ref_time = self.nearest_ref_time( ref_time )
        ref_time = self.ref_time
 
        hour = ref_time[8:10]

        if hour == "06" or hour == "18":
            self.prerequisites = requisites( self.name, [ 
                "file met_" + ref_time + ".nc ready" ])
        else:
            self.prerequisites = requisites( self.name, [])

        self.postrequisites = timed_requisites( self.name, [
            [0, self.name + " started for " + ref_time],
            [5, "file mos_" + ref_time + ".nc ready"],
            [6, self.name + " finished for " + ref_time] ])

        task_base.__init__( self, ref_time, initial_state )

#----------------------------------------------------------------------
class nztide( runahead_task_base ):

    name = "nztide"
    valid_hours = [ 6, 18 ]

    def __init__( self, ref_time, initial_state = "waiting" ):

        # adjust reference time to next valid for this task
        self.ref_time = self.nearest_ref_time( ref_time )
        ref_time = self.ref_time
 
        self.prerequisites = requisites( self.name, [])

        self.postrequisites = timed_requisites( self.name, [
            [0, self.name + " started for " + ref_time],
            [1, "file nztide_" + ref_time + ".nc ready"],
            [2, self.name + " finished for " + ref_time] ])

        runahead_task_base.__init__( self, ref_time, initial_state )

#----------------------------------------------------------------------
class topnet( task_base ):
    "streamflow data extraction and topnet" 

    """If no other tasks dependend on the streamflow data then it's
    easiest to make streamflow part of the topnet task, because of
    the unusual runahead behavior of topnet"""
 
    name = "topnet"
    valid_hours = range( 0,24 )

    # assume catchup mode and detect if we've caught up
    catchup_mode = True
    # (SHOULD THIS BE BASED ON TOPNET OR DOWNLOADER?)

    fuzzy_file_re =  re.compile( "^file (.*) ready$" )

    def __init__( self, ref_time, initial_state = "waiting" ):

        self.catchup_re = re.compile( "^CATCHUP:.*for " + ref_time )
        self.uptodate_re = re.compile( "^UPTODATE:.*for " + ref_time )

        # adjust reference time to next valid for this task
        self.ref_time = self.nearest_ref_time( ref_time )
        ref_time = self.ref_time
 
        if topnet.catchup_mode:
            #print "CUTOFF 11 for " + self.identity()
            nzlam_cutoff = reference_time.decrement( ref_time, 11 )
        else:
            #print "CUTOFF 23 for " + self.identity()
            nzlam_cutoff = reference_time.decrement( ref_time, 23 )
 
        self.prerequisites = fuzzy_requisites( self.name, [ 
            "file tn_" + nzlam_cutoff + ".nc ready" ])

        self.postrequisites = timed_requisites( self.name, [ 
            [0, "streamflow extraction started for " + ref_time],
            [2, "got streamflow data for " + ref_time],
            [2.1, "streamflow extraction finished for " + ref_time],
            [3, self.name + " started for " + ref_time],
            [4, "file topnet_" + ref_time + ".nc ready"],
            [5, self.name + " finished for " + ref_time] ])

        task_base.__init__( self, ref_time, initial_state )


    def run_external_dummy( self, dummy_clock_rate ):
        # RUN THE EXTERNAL TASK AS A SEPARATE PROCESS
        # TO DO: the subprocess module might be better than os.system?

        # for topnet, supply name of most recent nzlam file from the
        # sharpened fuzzy prerequisite

        prereqs = self.prerequisites.get_list()
        prereq = prereqs[0]
        m = topnet.fuzzy_file_re.match( prereq )
        [ file ] = m.groups()

        self.log.info( "launching external dummy for " + self.ref_time + " (off " + file + ")" )
        os.system( "./task_dummy.py " + self.name + " " + self.ref_time + " " + str(dummy_clock_rate) + " &" )
        self.state = "running"


    def incoming( self, priority, message ):

        # pass on to the base class message handling function
        task_base.incoming( self, priority, message)
        
        # but intercept catchup mode messages
        if not topnet.catchup_mode and self.catchup_re.match( message ):
            #message == "CATCHUP: " + self.ref_time:
            topnet.catchup_mode = True
            # WARNING: SHOULDN'T GO FROM UPTODATE TO CATCHUP?
            self.log.warning( "beginning CATCHUP operation" )

        elif topnet.catchup_mode and self.uptodate_re.match( message ):
            #message == "UPTODATE: " + self.ref_time:
            topnet.catchup_mode = False
            self.log.info( "beginning UPTODATE operation" )

#----------------------------------------------------------------------
class nwpglobal( task_base ):

    name = "nwpglobal"
    valid_hours = [ 0 ]

    def __init__( self, ref_time, initial_state = "waiting" ):

        # adjust reference time to next valid for this task
        self.ref_time = self.nearest_ref_time( ref_time )
        ref_time = self.ref_time
 
        self.prerequisites = requisites( self.name, [ 
            "file 10mwind_" + ref_time + ".um ready" ])

        self.postrequisites = timed_requisites( self.name, [
            [0, self.name + " started for " + ref_time],
            [120, "file 10mwind_" + ref_time + ".nc ready"],
            [121, self.name + " finished for " + ref_time] ])

        task_base.__init__( self, ref_time, initial_state )
