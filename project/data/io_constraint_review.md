# R6.7 PWM输出延迟约束审查

结论：审查通过，接受限定范围的约束例外。此结论只关闭22路PWM的no_output_delay文档审查项，不表示警告归零或外部波形已经实测通过。

审查日期：2026-11-01。审查者：Codex，自动化源码与既有报告审查；不声明人工签字。

## 依据

- scripts/create_bd.tcl只将PWM总线作为本IP的PL输出引出，没有输出给舵机的同步采样时钟。
- board/ax7020_zynq_ports_template.xdc逐路约束pwm_0[0]至pwm_0[21]，共22路；使用LVCMOS33、DRIVE 8与SLEW SLOW。电气配置检查不等于实测电平合格。
- src/rtl/nh22_axi.sv中PWM由时钟沿寄存器产生；默认时钟50MHz、帧周期20000us，时间基准为1us。
- sim/tb_nh22_50mhz.sv与sim/results/pwm50.log验证RTL级1500us高电平、20ms周期和复位关闭PWM。它不是布线后仿真或管脚测量。
- 原Routed时序报告为WNS +5.432ns、WHS +0.100ns、WPWS +9.146ns，三类失败端点均为0；no_clock和unconstrained_internal_endpoints均为0。唯一非零的所选约束检查是no_output_delay=22。

AMD UG903说明set_output_delay用于相对于接口时钟边沿描述输出外部延迟：https://docs.amd.com/r/en-US/ug903-vivado-using-constraints/Output-Delay 。本项目舵机接口采用脉宽编码，未定义共享接收时钟与同步setup/hold预算。因此本次选择保留原XDC与原始警告，接受限定接口的文档例外，不填写任意虚拟延迟来消除警告。

## 适用边界

审查记录data/io_constraint_review.json绑定上述源码、约束、构建脚本、仿真证据和原报告SHA256。scripts/review_io_constraints.py逐项检查；数量、任何其他约束检查或绑定文件变化都拒绝复用本例外。原综合/实现报告不修改，位流不重建，硬件不操作。

外部线路延迟、管脚波形、舵机输入门限、CDC、Fmax与完整实物验收没有由本次审查证明。原上下眼球故障和模型测试失败保持原记录。第三方技能包内原始验证结果保留为导入历史，本次结果以sim/results/verification.json为准。
