if {[llength $argv] != 2} {error "usage: checkpoint output_directory"}
set checkpoint [file normalize [lindex $argv 0]]
set output [file normalize [lindex $argv 1]]
file mkdir $output
open_checkpoint $checkpoint
report_utilization -file $output/utilization.rpt
report_timing_summary -file $output/timing_summary.rpt
close_design
puts SYNTHESIS_REPORT_EXPORT_PASS
