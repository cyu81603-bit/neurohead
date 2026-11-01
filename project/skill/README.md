# 可复用 FPGA / PYNQ 技能包

按所提供竞赛截图 §3.3.5.2 制作；更新日期 2026-11-01。目录 `skill/` 中包含五项
可独立复制的 Codex Skill，每项有 SKILL.md、README.md、脚本或模板及适用/失效说明。

|技能|使用场景|可复用产物|本次验证范围|
|---|---|---|---|
|[pynq-overlay](pynq-overlay/README.md)|换板/换题后的 Overlay 身份、加载、寄存器校验|离线 bit/HWH/hash/IP 检查、受控加载函数、排障表|主机假 Overlay；未上板|
|[pynq-dma](pynq-dma/README.md)|AXI stream 数据搬运与缓存/超时排障|simple DMA 封装、接收先行、显式同步、异常保留buffer|假 DMA 故障注入；未上板|
|[pynq-interface](pynq-interface/README.md)|从地址契约生成主机调用与测试|JSON 契约、权限/范围检查 API、独立 Mock 测试|两个无关题目离线生成|
|[fpga-evidence](fpga-evidence/README.md)|黄金比对、资源时序报告、资产复现|哈希清单、CSV 比对/采样统计、Vivado报告 JSON|合成边界测试+原始R6.7报告复算|
|[fpga-commissioning](fpga-commissioning/README.md)|数字正确但执行器不动、多个动作来源冲突|证据分层审核器、排障清单、提示词与验收模板|离线证据审查；无动作输出|

## 十分钟复用

1. 解压到任意工作目录，Python 3.9+ 即可执行离线脚本，无第三方依赖。
2. 在包根运行 `python -B tests/test_suite.py`，测试临时目录自动清理；不接触硬件。
3. 选择一项 skill，先读其 README。将目标板、IP路径、接口/数据/时序预算填入自己的
   profile/契约；示例值是合成数据，不是板卡默认值。
4. 要在 Codex 自动发现：把所需技能目录（如 `skill/pynq-overlay`）复制到
   `~/.codex/skills/`，或相应项目的 `.agents/skills/`；重新加载会话。不要复制外层
   skill 目录充当单个 Skill。可显式调用 `$pynq-overlay` 等五个名称。
5. 在板上单独安装与该板镜像匹配的 PYNQ 并验收；离线通过不跳过实际板级检查。

本技能目录已按要求整合至R6.7工程ZIP，未安装到全局Codex技能目录。

## 从原项目提炼出的经验

两个来源对话与本地冻结 R6.7 提交包构成案例依据，见 [SOURCES.md](../SOURCES.md)。
固定引脚/舵机/脉宽没有进入通用脚本。原工程是 PC + AX7020 裸机 ARM/lwIP + FPGA，
没有现成 PYNQ 上板成果；前三项为基于官方 API 新增的 PYNQ 工具。本次离线通过可
证明主机流程与失败边界，不能证明跨板硬件可用，也不据此宣称已获得 PYNQ 额外加分。

|开发观察/失败|提炼|保留的边界|
|---|---|---|
|早期Pin3输出与实际Pin10接线错位|资产、逻辑映射、外部测点分层验证|寄存器变化不证明引脚有正确波形|
|重启恢复、位流/固件/标定可能错配|可信清单和构建身份|哈希不证明真实性或功能正确|
|上下眼球回读到位，实际舵盘不动|保留失败与实物证据|不能由 accepted 推出执行成功|
|CH6/7会遮挡镜头|所有输出路径与所有权审查|禁用策略与看门狗需针对机构设计|
|R6.7聊天和动作两路并发|共享快照、取消代次、意图/执行分离|模型措辞失败仍保留|
|原工具写死clk_fpga_0且忽略未约束IO|多时钟解析、缺约束显式审查|正WNS不等于完整时序验收|

## 提交与验收

- 完整性：工程包根 `manifest.json` 覆盖除自身外全部交付文件；用
  `python verify_package.py` 复验，不产生硬件/网络操作。
- 本次验证：[VALIDATION.md](../VALIDATION.md) 和 `validation/` 原始 JSON/日志。
- 要申报通用 PYNQ Skill：仍需在真实 PYNQ 板上完成 Overlay 身份、只读寄存器、DMA
  正常/异常、黄金比对和第二块板迁移；记录镜像/版本/构建/数据/实测结果。
- 本包提供工具和模板；没有仿造第二块板 bitstream、HWH 或实测加速比。
- Harness²：项目已初始化并准备评估任务；实际模型优化是否运行以
  `validation/harness2-status.md` 为准，不把 dry-run 当优化结果。
