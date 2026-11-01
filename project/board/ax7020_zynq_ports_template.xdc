# AX7020 official manual J10. SIGNALS ONLY. External 5V servo supply, common ground.
# Channel 0 keeps historical eye signal on J10 pin10 / V15.
# channel 0: J10 pin10
set_property PACKAGE_PIN V15 [get_ports {pwm_0[0]}]
# channel 1: J10 pin4
set_property PACKAGE_PIN W18 [get_ports {pwm_0[1]}]
# channel 2: J10 pin3
set_property PACKAGE_PIN W19 [get_ports {pwm_0[2]}]
# channel 3: J10 pin5
set_property PACKAGE_PIN R14 [get_ports {pwm_0[3]}]
# channel 4: J10 pin6
set_property PACKAGE_PIN P14 [get_ports {pwm_0[4]}]
# channel 5: J10 pin7
set_property PACKAGE_PIN Y17 [get_ports {pwm_0[5]}]
# channel 6: J10 pin8
set_property PACKAGE_PIN Y16 [get_ports {pwm_0[6]}]
# channel 7: J10 pin9
set_property PACKAGE_PIN W15 [get_ports {pwm_0[7]}]
# channel 8: J10 pin11
set_property PACKAGE_PIN Y14 [get_ports {pwm_0[8]}]
# channel 9: J10 pin12
set_property PACKAGE_PIN W14 [get_ports {pwm_0[9]}]
# channel 10: J10 pin13
set_property PACKAGE_PIN P18 [get_ports {pwm_0[10]}]
# channel 11: J10 pin14
set_property PACKAGE_PIN N17 [get_ports {pwm_0[11]}]
# channel 12: J10 pin15
set_property PACKAGE_PIN U15 [get_ports {pwm_0[12]}]
# channel 13: J10 pin16
set_property PACKAGE_PIN U14 [get_ports {pwm_0[13]}]
# channel 14: J10 pin17
set_property PACKAGE_PIN P16 [get_ports {pwm_0[14]}]
# channel 15: J10 pin18
set_property PACKAGE_PIN P15 [get_ports {pwm_0[15]}]
# channel 16: J10 pin19
set_property PACKAGE_PIN U17 [get_ports {pwm_0[16]}]
# channel 17: J10 pin20
set_property PACKAGE_PIN T16 [get_ports {pwm_0[17]}]
# channel 18: J10 pin21
set_property PACKAGE_PIN V18 [get_ports {pwm_0[18]}]
# channel 19: J10 pin22
set_property PACKAGE_PIN V17 [get_ports {pwm_0[19]}]
# channel 20: J10 pin23
set_property PACKAGE_PIN T15 [get_ports {pwm_0[20]}]
set_property IOSTANDARD LVCMOS33 [get_ports {pwm_0[*]}]

set_property DRIVE 8 [get_ports {pwm_0[*]}]
set_property SLEW SLOW [get_ports {pwm_0[*]}]

# channel 21: J10 pin24, independent jaw output
set_property PACKAGE_PIN T14 [get_ports {pwm_0[21]}]
