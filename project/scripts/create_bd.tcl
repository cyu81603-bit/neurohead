set repo [file normalize "./build/ip_repo"]
set proj [file normalize "./build/vivado_zynq_neurohead"]
create_project neurohead_zynq $proj -part xc7z020clg400-2 -force
set_property ip_repo_paths $repo [current_project]
update_ip_catalog
create_bd_design "neurohead_system"

set ps [create_bd_cell -type ip -vlnv xilinx.com:ip:processing_system7:5.5 processing_system7_0]
set_property -dict [list \
    CONFIG.PCW_USE_M_AXI_GP0 {1} \
    CONFIG.PCW_FPGA0_PERIPHERAL_FREQMHZ {50} \
    CONFIG.PCW_USE_S_AXI_HP0 {0} \
    CONFIG.PCW_ENET0_PERIPHERAL_ENABLE {1} \
    CONFIG.PCW_ENET0_ENET0_IO {MIO 16 .. 27} \
    CONFIG.PCW_ENET0_GRP_MDIO_ENABLE {1} \
    CONFIG.PCW_ENET0_GRP_MDIO_IO {MIO 52 .. 53} \
    CONFIG.PCW_PRESET_BANK1_VOLTAGE {LVCMOS 1.8V} \
    CONFIG.PCW_UIPARAM_DDR_PARTNO {MT41J256M16 RE-125} \
    CONFIG.PCW_UIPARAM_DDR_DRAM_WIDTH {16 Bits} \
    CONFIG.PCW_UIPARAM_DDR_BUS_WIDTH {32 Bit} \
] $ps

set rst [create_bd_cell -type ip -vlnv xilinx.com:ip:proc_sys_reset:5.0 rst_ps7_0_50M]
set axi [create_bd_cell -type ip -vlnv xilinx.com:ip:axi_interconnect:2.1 axi_interconnect_0]
set servo [create_bd_cell -type ip -vlnv user.org:user:nh22_axi:3.0 neurohead_servo_0]
set_property CONFIG.NUM_MI {1} $axi

connect_bd_net [get_bd_pins processing_system7_0/FCLK_CLK0] [get_bd_pins processing_system7_0/M_AXI_GP0_ACLK] [get_bd_pins rst_ps7_0_50M/slowest_sync_clk] [get_bd_pins axi_interconnect_0/ACLK] [get_bd_pins axi_interconnect_0/S00_ACLK] [get_bd_pins axi_interconnect_0/M00_ACLK] [get_bd_pins neurohead_servo_0/s_axi_aclk]
connect_bd_net [get_bd_pins processing_system7_0/FCLK_RESET0_N] [get_bd_pins rst_ps7_0_50M/ext_reset_in]
connect_bd_net [get_bd_pins rst_ps7_0_50M/peripheral_aresetn] [get_bd_pins axi_interconnect_0/ARESETN] [get_bd_pins axi_interconnect_0/S00_ARESETN] [get_bd_pins axi_interconnect_0/M00_ARESETN] [get_bd_pins neurohead_servo_0/s_axi_aresetn]
connect_bd_intf_net [get_bd_intf_pins processing_system7_0/M_AXI_GP0] [get_bd_intf_pins axi_interconnect_0/S00_AXI]
connect_bd_intf_net [get_bd_intf_pins axi_interconnect_0/M00_AXI] [get_bd_intf_pins neurohead_servo_0/S_AXI]
assign_bd_address
set cpu_segs [get_bd_addr_segs -of_objects [get_bd_addr_spaces processing_system7_0/Data]]
if {[llength $cpu_segs]!=1} {error "Expected exactly one PS AXI peripheral segment: $cpu_segs"}
set servo_offset [get_property OFFSET [lindex $cpu_segs 0]]
if {[expr {$servo_offset}]!=0x40000000} {error "Firmware AXI base mismatch: $servo_offset"}
set check [open build/migration/axi_ps_config.txt w]
puts $check "PART=[get_property PART [current_project]]"
puts $check "SERVO_AXI_BASE=$servo_offset"
puts $check "SERVO_AXI_RANGE=[get_property RANGE [lindex $cpu_segs 0]]"
foreach key {PCW_FPGA0_PERIPHERAL_FREQMHZ PCW_ENET0_ENET0_IO PCW_ENET0_GRP_MDIO_IO PCW_UIPARAM_DDR_PARTNO PCW_UIPARAM_DDR_BUS_WIDTH} {
 puts $check "$key=[get_property CONFIG.$key $ps]"
}
close $check

make_bd_pins_external [get_bd_pins neurohead_servo_0/pwm]

make_bd_intf_pins_external [get_bd_intf_pins processing_system7_0/DDR]
make_bd_intf_pins_external [get_bd_intf_pins processing_system7_0/FIXED_IO]
save_bd_design
validate_bd_design
make_wrapper -files [get_files $proj/neurohead_zynq.srcs/sources_1/bd/neurohead_system/neurohead_system.bd] -top
add_files -norecurse [glob $proj/neurohead_zynq.gen/sources_1/bd/neurohead_system/hdl/neurohead_system_wrapper.v]
add_files -fileset constrs_1 -norecurse [file normalize "./board/ax7020_zynq_ports_template.xdc"]
set_property top neurohead_system_wrapper [current_fileset]
update_compile_order -fileset sources_1
puts "AX7020_DDR: MT41J256M16 RE-125, 2 x16 devices, 32-bit PS DDR"
puts "AX7020_ETH: GEM0 RGMII MIO 16..27, MDIO MIO 52..53, MIO bank1 1.8V"
puts "AX7020_PHY_RESET: not enabled; the original AX7020 manual did not identify a PS MIO reset connection"
puts "ZYNQ_BD_READY: $proj/neurohead_zynq.xpr"
