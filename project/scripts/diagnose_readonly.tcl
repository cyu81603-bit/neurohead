connect
configparams force-mem-access 1
targets -set -filter {name =~ "ARM Cortex-A9 MPCore #0"}
stop
puts "CPU_PC:"; puts [rrd pc]; puts [rrd lr]
puts "HW_ID:"; puts [mrd 0x40000000 2]
puts "HW_STATUS_MASKS:"; puts [mrd 0x4000000c 5]
puts "HW_ACCEPTED_REJECTED_WD:"; puts [mrd 0x40000020 3]
con
configparams force-mem-access 0
disconnect
exit