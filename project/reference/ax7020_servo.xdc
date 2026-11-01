# ==============================================================================
# 1. 系统时钟约束 (AX7020 PL端 50MHz 晶振 -> U18)
# ==============================================================================
set_property PACKAGE_PIN U18 [get_ports sys_clk]
set_property IOSTANDARD LVCMOS33 [get_ports sys_clk]
create_clock -period 20.000 -name sys_clk -waveform {0.000 10.000} [get_ports sys_clk]

# ==============================================================================
# 2. 按键约束 (AX7020 PL端按键 KEY1: N15, KEY2: N16)
# ==============================================================================
set_property PACKAGE_PIN N15 [get_ports sys_rst_n]
set_property IOSTANDARD LVCMOS33 [get_ports sys_rst_n]

set_property PACKAGE_PIN N16 [get_ports key_enable_n]
set_property IOSTANDARD LVCMOS33 [get_ports key_enable_n]

# ==============================================================================
# 3. PL端 LED 状态指示灯 (PL_LED1: M14, PL_LED2: M15)
# ==============================================================================
set_property PACKAGE_PIN M14 [get_ports {led[0]}]
set_property IOSTANDARD LVCMOS33 [get_ports {led[0]}]

set_property PACKAGE_PIN M15 [get_ports {led[1]}]
set_property IOSTANDARD LVCMOS33 [get_ports {led[1]}]

# ==============================================================================
# 4. MG90S 舵机 PWM 输出信号 (挂载在扩展口 J11 的 Pin 3 -> V15)
# ==============================================================================
set_property PACKAGE_PIN V15 [get_ports servo_pwm]
set_property IOSTANDARD LVCMOS33 [get_ports servo_pwm]
set_property DRIVE 8 [get_ports servo_pwm]
set_property SLEW SLOW [get_ports servo_pwm]