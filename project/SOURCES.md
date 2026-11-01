# 来源、证据与本次新增

## 用户提供的要求

本聊天的两张截图：指南 §3.3.5.2 技能包与通用 PYNQ Skill 说明。用户要求基于两段
项目对话制作一套 skill，因此采用 `skill/`＋逐项 README、工作流、模板、校验脚本、
坑清单的形式。截图是格式/评审需求；其中对其他提交材料的描述不扩大本次任务。

## 项目记录

- [规划 NeuroHead FPGA竞赛项目](codex://threads/01a06f57-d2d9-70c0-b481-066059dcf72d)：
  已读最新交接及引脚修复相关记录，涵盖Pin3/Pin10不一致、数字回读与实物分离、
  全局 inhibit、微步试验和超时。读取范围为最新10轮，未声称读取该长对话全部历史。
- [搭建 AX7020 机器人头驱动框架](codex://threads/01a16e80-49db-7da3-866a-4f7f8067c7eb)：
  已读最新R6.7提交记录及此前10轮关键记录，包含R6.7并发、掉电恢复、上下眼球
  不动和后续R6.8–R6.10变更。后续版本不并入R6.7案例基线。
- 本地只读材料：`F:/NeuroHead/submissions/neurohead_r6_7_final_20261101/skill/` 的
  readme/workflow/troubleshooting、check_implementation.py、verify_manifest.py、
  test_skill.py；同提交包 data/version_provenance.json、board/channels.csv 和
  build/reports/zynq_neurohead/{timing_summary,utilization}.rpt。
- 架构和并发细节参考 `F:/NeuroHead/builds/nh22_v26_1029/CURRENT_ARCHITECTURE.md` 与
  `PARALLEL_DIALOGUE_R6_7.md`。它们用于辨别架构和流程；不复制其当前运行状态为现场证据。

原 hash/report helper 的思路被重新实现：移除固定时钟名，补 hold/pulse端点、缺约束、
路径、容差与权限失败检查。R6.7原始报告的本次读取哈希记录在 validation 结果中。
本包未重新运行原项目234项测试，也未运行其部署脚本。

## PYNQ 官方依据（核查于2026-11-01）

- [Overlay API，v3.0.0](https://pynq.readthedocs.io/en/v3.0.0/pynq_package/pynq.overlay.html)：
  Overlay/download/is_loaded、ip_dict、DefaultIP read/write/register_map。文档版本明确，
  目标板实际安装版本需另核对；不默认 ignore_version。
- [Allocate / Buffer](https://pynq.readthedocs.io/en/latest/pynq_libraries/allocate.html)：
  allocate、device_address、coherent、flush/invalidate 与 sync 别名。
- [DMA 教程，v2.7.0](https://pynq.readthedocs.io/en/v2.7.0/pynq_libraries/dma.html)：
  simple mode 示例、TLAST 与长度配置；本包没有把旧教程限制推广到所有版本。
- [PYNQ 官方 DMA 源码](https://github.com/Xilinx/PYNQ/blob/master/pynq/lib/dma.py)：
  参考通道 idle/error/running/transfer/wait/stop/transferred 接口。master会变化，
  本次只进行主机替身验证；真板验收必须记录实际 PYNQ 包版本与该版本源码。

前三项 PYNQ helper、契约生成器、证据审核器与本包回归测试为本次新增；没有声称从
NeuroHead 提取出已实测的 DMA 或 Linux/PYNQ 镜像。通用 DMA 层约束来自官方接口，
不能用原项目 UDP 的历史测试替代它的硬件验收。
