# Called only after an authenticated load, with servo power off/signals unplugged.
set connected 0
set stopped 0
proc rd32 {address} {
    set word [lindex [mrd -value $address 1] 0]
    if {![string is integer -strict $word]} {error "Cannot parse numeric readback at $address"}
    return [expr {$word + 0}]
}
set failed [catch {
    connect
    set connected 1
    configparams force-mem-access 1
    targets -set -filter {name =~ "ARM Cortex-A9 MPCore #0"}
    if {[rd32 0x40000000] != 0x3232484e || [rd32 0x40000004] != 0x00030016} {error "Wrong NH22 hardware"}
    foreach address {0x4000000c 0x40000014 0x40000018} {
        if {[rd32 $address] != 0} {error "Board is not unconfigured and disarmed; refusing CPU resume recovery"}
    }
    stop
    set stopped 1
    puts "COLD_START_CPU_PC: [rrd pc]"
    con
    set stopped 0
    after 200
} message]
if {$stopped} {catch {con}}
if {$connected} {
    catch {configparams force-mem-access 0}
    catch {disconnect}
}
if {$failed} {puts stderr "COLD_START_RECOVERY_FAILED: $message";exit 1}
puts "COLD_START_RESUME_OK"
exit 0
