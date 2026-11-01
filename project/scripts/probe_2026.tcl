puts "VIVADO_VERSION=[version -short]"
puts "VIVADO_INSTALL=$::env(XILINX_VIVADO)"
set target xc7z020clg400-2
if {[llength [get_parts -quiet $target]]!=1} {error "AX7020 part missing: $target"}
create_project -in_memory -part $target
foreach pattern {xilinx.com:ip:processing_system7:* xilinx.com:ip:proc_sys_reset:* xilinx.com:ip:axi_interconnect:*} {
 set defs [get_ipdefs -all -quiet $pattern]
 if {[llength $defs]==0} {error "Required IP missing: $pattern"}
 puts "AVAILABLE_IP=$defs"
}
puts "VIVADO2026_DEVICE_IP_PROBE_PASS"
close_project
exit
