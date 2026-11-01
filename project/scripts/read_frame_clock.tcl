connect
configparams force-mem-access 1
targets -set -filter {name =~ "ARM Cortex-A9 MPCore #0"}
puts "FRAME_COUNTER_A:";puts [mrd 0x4000002c 1]
set start [clock milliseconds]
after 1000
puts "FRAME_COUNTER_B:";puts [mrd 0x4000002c 1]
puts "HOST_ELAPSED_MS: [expr {[clock milliseconds]-$start}]"
puts "CURRENT_ENABLE_MASK:";puts [mrd 0x40000014 1]
configparams force-mem-access 0
disconnect
exit