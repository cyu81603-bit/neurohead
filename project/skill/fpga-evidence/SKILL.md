---
name: fpga-evidence
description: Verify FPGA release manifests, compare numeric CSV outputs against golden references, extract Vivado implementation metrics and generate evidence reports with explicit unknowns and provenance.
---

# 黄金参考、实现指标与复现

按 [README.md](README.md) 选择独立脚本；读
[references/reporting.md](references/reporting.md) 决定验收与报告措辞。

冻结 build ID、part、源代码、位流、HWH/固件和实验配置，生成可信资产清单。
从可信快照读取预期哈希；不能在部署后重算一份清单便宣称原始构建无变化。
运行态标定/缓存与冻结资产分开。清单只证明字节一致，不证明真实性或设计正确。

黄金参考先定义输入分布、dtype、定点舍入/溢出、shape/布局、单位、atol/rtol。
对 CSV 逐元素判定 `abs(actual-expected) <= atol + rtol*abs(expected)`，拒绝 NaN/Inf、
空输入、列/行数不同。边界、随机种子、零值和饱和另设计样例；不要靠容差掩盖单位差。

实现报告从同一 routed build 取 timing_summary/utilization，保存原报告哈希。
解析 WNS/WHS、setup/hold/pulse 失败端点、全部 clock 和约束缺失；负裕量或资源
超预算失败，无法识别/缺报告明确失败。未约束 IO 需对应设计的明确例外说明，
不能由“all user specified constraints met”推出所有接口都已约束。

主机时延从真实测量的 CSV 导入，报告样本数、median/p95 与测量边界；没有采样
就写未测。时钟约束频率不是 Fmax；Python DMA 往返不是 PL 纯计算；不得编造加速比。
对已确认可重复的计算命令，用 benchmark.py 自动采集逐次时延、原始输出与失败；
禁止用重复测量执行器动作、烧写或复位。进程启动开销包含在报告中，timeout只约束
直接子进程；有后台子进程的命令需自己管理生命周期。

报告区分离线、仿真、板上数字、外部实测和操作者反馈，列失败项、未知项及恢复
条件。最终复现包要在新目录校验哈希、运行验证，再归档。
