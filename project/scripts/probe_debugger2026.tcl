foreach name {connect targets configparams rst stop fpga mrd mwr dow con disconnect} {
 if {[llength [info commands $name]]!=1} {error "Missing debugger command: $name"}
}
puts "XSDB2026_RECOVERY_COMMANDS_AVAILABLE Tcl=[info patchlevel]"
exit
