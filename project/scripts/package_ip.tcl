set root [file normalize "./build/ip_repo/nh22_axi"]
create_project ip_packaging [file normalize "./build/ip_packaging_tmp"] -part xc7z020clg400-2 -force
file mkdir $root
file copy -force [file normalize "./src/rtl/nh22_axi.sv"] $root
add_files [file join $root nh22_axi.sv]
set_property top nh22_axi [current_fileset]
update_compile_order -fileset sources_1
ipx::package_project -root_dir $root -vendor user.org -library user -taxonomy {/UserIP} -import_files -force
set core [ipx::current_core]
set_property name nh22_axi $core
set_property display_name {NeuroHead 22 channel PWM} $core
set_property version 3.0 $core
set busif [ipx::get_bus_interfaces S_AXI -of_objects $core]
if {[llength $busif]==0} {set busif [ipx::add_bus_interface S_AXI $core]}
set_property bus_type_vlnv xilinx.com:interface:aximm:1.0 $busif
set_property abstraction_type_vlnv xilinx.com:interface:aximm_rtl:1.0 $busif
set_property interface_mode slave $busif
foreach {lp pp} {
 AWADDR s_axi_awaddr AWPROT s_axi_awprot AWVALID s_axi_awvalid AWREADY s_axi_awready
 WDATA s_axi_wdata WSTRB s_axi_wstrb WVALID s_axi_wvalid WREADY s_axi_wready
 BRESP s_axi_bresp BVALID s_axi_bvalid BREADY s_axi_bready
 ARADDR s_axi_araddr ARPROT s_axi_arprot ARVALID s_axi_arvalid ARREADY s_axi_arready
 RDATA s_axi_rdata RRESP s_axi_rresp RVALID s_axi_rvalid RREADY s_axi_rready
} {
 set pm [ipx::get_port_maps $lp -of_objects $busif]
 if {[llength $pm]==0} {set pm [ipx::add_port_map $lp $busif]}
 set_property physical_name $pp $pm
}
set mm [ipx::get_memory_maps S_AXI -of_objects $core]
if {[llength $mm]==0} {set mm [ipx::add_memory_map S_AXI $core]}
set ab [ipx::get_address_blocks Reg -of_objects $mm]
if {[llength $ab]==0} {set ab [ipx::add_address_block Reg $mm]}
set_property range 4096 $ab
set_property width 32 $ab
set_property usage register $ab
set_property slave_memory_map_ref S_AXI $busif
catch {ipx::infer_bus_interface s_axi_aclk xilinx.com:signal:clock_rtl:1.0 $core}
catch {ipx::infer_bus_interface s_axi_aresetn xilinx.com:signal:reset_rtl:1.0 $core}
ipx::save_core $core
ipx::check_integrity -quiet $core
close_project
puts NH22_IP_READY
