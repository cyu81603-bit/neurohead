# 当前验证结果

2026-11-01：169项控制测试、56项集成测试、7项网页测试、38项技能测试和6项I/O审查失效检查，共276项软件测试通过。两项空闲GUI自检通过，RTL功能和50MHz周期/脉宽仿真通过。C协议沿用原可执行文件重跑，未重新编译；厂商Tcl检查未重跑。

I/O约束审查通过，采用限定接口的例外接受：原Routed报告的no_output_delay=22保持不变，内部未约束端点和缺时钟均为0。data/io_constraint_review.json记录依据、范围、审查者和文件哈希；data/io_constraint_review.md说明理由。源文件或约束检查数量变化时，校验拒绝复用此例外。implementation_metrics.json的passed=true只表示所选实现指标及本例外通过，不表示完整板卡验收。

本轮没有重跑综合实现、加载板卡、发送动作、打开摄像头或调用大模型。管脚波形、CDC、Fmax与完整物理验收未由本次验证完成。上下眼球故障与历史模型测试失败保留。

替换技能前及本次审查前记录分别保存在data/historical/before_skill_replace和data/historical/before_io_review。validation目录的原始技能包验证结果属于导入历史，本轮结果以sim/results/verification.json为准。
