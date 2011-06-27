#!/usr/bin/env python

#C: THIS FILE IS PART OF THE CYLC FORECAST SUITE METASCHEDULER.
#C: Copyright (C) 2008-2011 Hilary Oliver, NIWA
#C: 
#C: This program is free software: you can redistribute it and/or modify
#C: it under the terms of the GNU General Public License as published by
#C: the Free Software Foundation, either version 3 of the License, or
#C: (at your option) any later version.
#C:
#C: This program is distributed in the hope that it will be useful,
#C: but WITHOUT ANY WARRANTY; without even the implied warranty of
#C: MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#C: GNU General Public License for more details.
#C:
#C: You should have received a copy of the GNU General Public License
#C: along with this program.  If not, see <http://www.gnu.org/licenses/>.

"""Generate a suite with N dummy tasks arranged in a simple tree structure:
  T1 => T2 & T3; T2 => T4 & T5; T3 => T6 & T7; ...
"""

import os, sys
from mkdir_p import mkdir_p

def usage():
    print "USAGE: sys.argv[0] N_TASKS"
    print "(INTEGER number of tasks)"

try:
    N = sys.argv[1]
except:
    usage()
    sys.exit(1)

try:
    int(N)
except:
    usage()
    sys.exit(1)

try:
    tmpdir = os.environ['TMPDIR']
except:
    print 'ERROR: you must define $TMPDIR'
    sys.exit(1)

name = 'T' + N
group = 'scaling'
suite = group + ':' + name

os.system( 'cylc db unregister --obliterate --force ' + suite )

dir = os.path.join( tmpdir, group, name )
mkdir_p( dir )
 
suiterc = os.path.join( dir, 'suite.rc' )

FILE = open( suiterc, 'wb' )

FILE.write( "title = scaling test" + N + '\n' )
FILE.write( "description = A test suite containing " + N + " tasks\n" )
FILE.write( "job submission method = at_now\n" )

FILE.write( """
[special tasks]
    sequential = """)
for i in range(1,int(N)+1):
    FILE.write( 'T' + str(i) + ', ' )

FILE.write( """

[dependencies]
    [[0,6,12,18]]
        graph = \"\"\"
""")

for i in range(2,int(N)+1,2):
    FILE.write( 'T' + str(i/2) + ' => T' + str(i) + '\n')
    FILE.write( 'T' + str(i/2) + ' => T' + str(i+1) + '\n')

FILE.write('\n"""')
FILE.close()

os.system( 'cylc db register ' + suite + ' ' + dir )

