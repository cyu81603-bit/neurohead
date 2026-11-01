# 本次验证范围

2026-11-01，从独立R6.7提交目录运行：169项控制/协议/恢复检查、56项集成测试、7项网页测试、38项新技能测试，共270项软件测试通过；两项空闲GUI自检通过。RTL功能和50MHz时序仿真通过，C协议原可执行文件重跑通过。

本次MinGW cc1依赖缺失（0xc0000135），未成功重新编译C。可在正常GCC环境运行默认validate_submission.py重编；使用--prebuilt-protocol显式跳过编译。本次结果已记录c_recompiled=false。供应商xsdb原TclReadbackTests未纳入本轮离线套件，依赖厂商DLL环境；历史启动/通信证据单独保留，不声称本次上板成功。

综合与实现没有重跑。build/reports/synthesis/utilization.rpt和synthesis.dcp来自原2026.1成功构建，routed报告来自同一原构建。导出报告的Vivado启动器此次未成功启动；不以此更新原报告日期。恢复代码和位流没有因此修改。

历史模型检查含失败，见report/llm_collaboration；本轮不重新调用模型、不发声、不打开摄像头、不发板卡动作。全部GUI自检退出后才归档，无活动会话文件。

技能包替换后，测试入口为 tests/test_suite.py。五项技能保持输入包内容不变；内部生成接口测试另有6项通过。历史替换前结果见 data/historical/before_skill_replace。

新技能实现报告检查识别到22路输出未设置output delay，尚需书面I/O约束审查，因此 implementation_metrics.json 的 passed 为 false；本轮软件测试通过不代表实现检查或物理验收全部通过。PYNQ仅做离线模拟验证，未在真实PYNQ板上验证。
