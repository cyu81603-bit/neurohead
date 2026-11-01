# Build the corrected AX7020 Zynq hardware platform and export an XSA for
# Vitis.  Run package_neurohead_ip.tcl and create_zynq_neurohead_bd.tcl first.
# On Windows, launch these Tcl scripts from a short filesystem path (for
# example, a subst drive) because Vivado 2022.2 child runs can fail past the
# Windows 260-character normal path limit.
set proj [file normalize "./build/vivado_zynq_neurohead/neurohead_zynq.xpr"]
set output_dir [file normalize "./build/reports/zynq_neurohead"]
file mkdir $output_dir
# Vivado 2022.2's IP-integrator init.tcl sources some helper files by relative
# name when reopening a BD project. Resolve those against the installed IPI
# directory, then restore the caller directory for all generated artifacts.
if {[llength [get_projects -quiet]] == 0} {
if {![info exists ::env(XILINX_VIVADO)]} { error "XILINX_VIVADO is not set by the launcher" }
set ipi_dir [file normalize [file join $::env(XILINX_VIVADO) scripts ipintegrator]]
if {![file exists [file join $ipi_dir replace_bd_cell.tcl]]} { error "Missing Vivado IPI helper in $ipi_dir" }
set caller_dir [pwd]
cd $ipi_dir
set open_status [catch {open_project $proj} open_message open_options]
cd $caller_dir
if {$open_status} { return -options $open_options $open_message }
} elseif {[string tolower [file normalize [get_property DIRECTORY [current_project]]]] ne [string tolower [file dirname $proj]]} {
    error "An unrelated project is already open"
}
update_compile_order -fileset sources_1
launch_runs impl_1 -to_step write_bitstream -jobs 4
wait_on_run impl_1
if {[get_property STATUS [get_runs impl_1]] ne "write_bitstream Complete!"} {
    error "Implementation did not complete: [get_property STATUS [get_runs impl_1]]"
}
open_run impl_1
report_timing_summary -file "$output_dir/timing_summary.rpt"
report_utilization -file "$output_dir/utilization.rpt"
report_drc -file "$output_dir/drc.rpt"
write_bitstream -force "$output_dir/neurohead_zynq.bit"
write_hw_platform -fixed -include_bit -force -file "$output_dir/neurohead_zynq.xsa"
set init_files [glob -nocomplain [file join [file dirname $proj] neurohead_zynq.gen sources_1 bd neurohead_system ip * ps7_init.tcl]]
if {[llength $init_files]!=1} {error "Expected one generated PS7 init Tcl: $init_files"}
file copy -force [lindex $init_files 0] "$output_dir/ps7_init.tcl"
puts "ZYNQ_BUILD_READY: $output_dir/neurohead_zynq.bit"
puts "ZYNQ_XSA_READY: $output_dir/neurohead_zynq.xsa"
close_project
