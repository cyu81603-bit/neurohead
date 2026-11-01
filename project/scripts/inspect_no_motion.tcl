connect
puts "JTAG_TARGETS_BEGIN"
puts [targets]
puts "JTAG_TARGETS_END"
if {[catch {
    targets -set -filter {name =~ "ARM Cortex-A9 MPCore #0"}
    configparams force-mem-access 1
    puts "CPU_STATE:"; puts [state]
    puts "NH22_ID:"; puts [mrd 0x40000000 2]
    puts "NH22_STATUS_ACTIVE_CONFIGURED_HOLD:"; puts [mrd 0x4000000c 5]
    configparams force-mem-access 0
} err]} {puts "INSPECT_ERROR: $err"}
disconnect
exit