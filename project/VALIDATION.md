# 本次验证记录

2026-11-01，Windows、Python 3.9；仅主机离线操作，无板卡或网络测试。

- 5项 skill 均通过官方 skill-creator `quick_validate.py`。
- 38项回归测试通过；两个无关契约另生成并运行共6项内部寄存器测试。
- 自动采样工具用本机可重复计算验证采集与失败保留；数据仅代表测试主机命令耗时，
  未作为FPGA性能或加速比。
- 全部Python文件通过AST语法解析；相对Markdown链接存在性检查通过。
- 原R6.7报告离线复算：LUT7033、FF3780、约束时钟50MHz、WNS5.432ns、WHS0.100ns、
  WPWS9.146ns。setup/hold/pulse失败端点均0，仍有22个输出无output delay约束。
  默认指标门禁因此失败：`IO constraint gaps need documented review`，未擅自豁免。
- 未重新综合/实现，不把上述约束频率当Fmax；DRC/CDC/功耗本次未审查。
- 真正PYNQ Overlay/DMA、执行机构、真实闭环误差及第二块板迁移均未验收。

复验：在包根运行 `python -B tests/test_suite.py`。详细结果见
[summary.json](validation/summary.json)、[offline-tests.log](validation/offline-tests.log)、
[skill-validation.json](validation/skill-validation.json) 和
[r6_7-implementation.json](validation/r6_7-implementation.json)。
原始Vivado报告保存在 `validation/source-reports/`，可离线复算，输入哈希在结果JSON中。

Harness²单独状态见 [harness2-status.md](validation/harness2-status.md)；初始化和受阻的
dry-run不代表模型优化通过。未运行模型评估或 apply。
