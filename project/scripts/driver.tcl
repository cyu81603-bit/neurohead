# Build only. No hardware-manager, JTAG or flash commands.
source scripts/package_ip.tcl
source scripts/create_bd.tcl
source scripts/build_hw.tcl
open_project build/vivado_zynq_neurohead/neurohead_zynq.xpr
open_run impl_1
set pins {V15 W18 W19 R14 P14 Y17 Y16 W15 Y14 W14 P18 N17 U15 U14 P16 P15 U17 T16 V18 V17 T15 T14}
for {set i 0} {$i<22} {incr i} {
 set port [get_ports [format {pwm_0[%d]} $i]]
 if {[get_property PACKAGE_PIN $port] ne [lindex $pins $i]} {error "PWM pin audit failed at $i"}
}
set maxpath [get_timing_paths -delay_type max -max_paths 1]
set minpath [get_timing_paths -delay_type min -max_paths 1]
set wns [get_property SLACK $maxpath]
set whs [get_property SLACK $minpath]
if {$wns<0 || $whs<0} {error "Timing failed WNS=$wns WHS=$whs"}
report_drc -file build/reports/zynq_neurohead/final_drc.rpt
set bad [get_drc_violations -quiet -filter {SEVERITY == "Error" || SEVERITY == "Critical Warning"}]
if {[llength $bad]>0} {error "DRC has error or critical warning"}
set out [open build/reports/zynq_neurohead/audit.txt w]
puts $out "NH22_PIN_TIMING_DRC_PASS WNS=$wns WHS=$whs N=22"
close $out
close_project
puts "NH22_BUILD_PASS WNS=$wns WHS=$whs"
