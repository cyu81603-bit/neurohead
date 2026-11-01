---
name: pynq-overlay
description: Load and inspect PYNQ overlays, validate bitstream/HWH provenance and IP identity, and use register_map or documented MMIO offsets when bringing up or porting an overlay.
---

# PYNQ Overlay 与寄存器

先读 [README.md](README.md) 确认使用与失效边界；需要诊断时读
[references/troubleshooting.md](references/troubleshooting.md)。

先确认目标板、FPGA part、PYNQ/Python 版本、启动镜像、Vivado 版本及实际 IP
层级路径。板卡叫 AX7020 并不证明它已安装兼容的 PYNQ 镜像；裸机 ELF/lwIP
不能直接运行 Python Overlay。没有匹配镜像时交付迁移步骤与离线结果。

使用 `scripts/overlay_guard.py` 的 `inspect_bundle` 检查同名 `.bit/.hwh`、
非空文件、SHA256 和 HWH 目标 IP。清单来自同一次可信构建；相同文件名和
哈希校验本身都不能证明两文件设计匹配。保存 part、工具版本和构建 ID。

加载前暂停 DMA／IP 调用者，确认板级输出处于适合重新配置的状态。只有用户
请求实际加载时调用 `load_overlay`；离线 inspect 不导入 PYNQ。
`Overlay(..., download=False)` 先解析元数据，检查 `ip_dict`，再 download。
加载后重新取得 IP 对象，不能复用旧 overlay 的 driver/register_map/buffer 状态。

检查 `ol.is_loaded()`、目标 IP VLNV、`ip_dict[path]['phys_addr']` 与
`addr_range`。仅在文档规定无副作用的 ID/version 寄存器上回读确认设计身份。
没有硬件 ID 时记录无法验证该项，不虚构版本寄存器。

寄存器字段优先按实际 HWH 的 `ip.register_map` 使用；无寄存器描述时按
当前导出地址表使用 `ip.read(offset)`／`ip.write(offset,value)`，offset 相对 IP
基址。读可能 clear-on-read，写可能 W1C；先查语义，禁止全寄存器扫描或
盲目 read-modify-write。需要批量主机 API 时使用 pynq-interface 的契约生成流程。

报告列出：资产哈希、环境、预期与发现的 IP、加载前后状态、ID 证据、执行过的
读写及偏移；把“元数据一致”“加载成功”“功能输出正确”分别判定。
