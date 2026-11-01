# Load the new monitor firmware, not the old workspace binary.
# Prerequisite: servo power is OFF. System reset happens BEFORE PL programming.
# Usage: xsct load_monitor_jtag.tcl <ps7_init.tcl> <monitor_app.bin> <bitstream>
if {$argc != 3} { puts stderr "Expected PS init, binary, and bitstream paths"; exit 1 }
set initfile [file normalize [lindex $argv 0]]
set binfile [file normalize [lindex $argv 1]]
set bitfile [file normalize [lindex $argv 2]]
foreach path [list $initfile $binfile $bitfile] {
    if {![file isfile $path]} { puts stderr "Required file missing: $path"; exit 1 }
}
if {[catch {
connect
configparams force-mem-access 1
targets -set -filter {name =~ "APU"}
rst -system
after 1000
targets -set -filter {name =~ "ARM Cortex-A9 MPCore #1"}
stop
targets -set -filter {name =~ "ARM Cortex-A9 MPCore #0"}
stop
source $initfile
ps7_init
targets -set -filter {name =~ "APU"}
fpga -file $bitfile
ps7_post_config
puts "PL_PHYSICAL_READBACK_BEFORE_APP"
puts [mrd 0x4000000c 5]
targets -set -filter {name =~ "ARM Cortex-A9 MPCore #0"}
rst -processor
dow -data $binfile 0x01000000
con -addr 0x01000000
after 1000
puts "MONITOR_BINARY_JTAG_LAUNCHED: $binfile"
puts "QUERY_ONLY_NEXT: 192.168.10.20:5005"
configparams force-mem-access 0
disconnect
} err]} {
    puts stderr "MONITOR_LAUNCH_FAILED: $err"
    exit 1
}
exit
