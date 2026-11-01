---
name: pynq-dma
description: Implement and troubleshoot bounded PYNQ AXI DMA simple-mode transfers, allocated buffers, cache synchronization, TLAST and status diagnostics for streaming IP bring-up.
---

# PYNQ DMA 与缓存一致性

先读 [README.md](README.md) 的限定范围。按
[references/diagnosis.md](references/diagnosis.md) 定位异常。

记录真实 PYNQ 版本及 driver、DMA VLNV、simple/SG 配置、MM2S/S2MM 数据宽度、
DRE、长度寄存器宽度、最大传输字节数和 stream TLAST/TKEEP 契约。不能依据旧教程
推断所有 PYNQ 版本只支持 simple 模式；本封装主动限定 simple 双向 DMA。

`pynq.allocate` 分配收发 buffer；保留原对象，使用 `buf[:] = values`，不能把 buf
替换成普通 NumPy array。字节数由 `nbytes` 和接口契约推导，禁止把元素数当字节。
本模板仅处理整个、连续、等字节数的不同收发 buffer；非等长算法另行定义 shape。

发送前 flush、接收完成后 invalidate；部分驱动已做同步仍保留明确的责任边界。
先启动 S2MM 接收，配置／启动算法 IP 的时机由握手契约决定，然后启动 MM2S。
不要把 ap_start=1 或 auto_restart=1 写成通用启动序列。

用 `scripts/dma_transfer.py` 的有界 idle/error 轮询，再调用完成态 wait。
异常时停止两通道、保留状态与 buffer 引用，不释放仍可能被 DMA 访问的内存，不
自动 reset、重传或重载 overlay。恢复需确认引擎停止及系统可恢复状态。
Python 轮询 deadline 不能约束底层 MMIO/driver 自身阻塞，板级恢复另验收。

采集 transfer 总时延与样本数；包括同步、轮询与 Python 开销，不能标成 PL 纯计算
时延。与相同输入、dtype、布局的黄金参考比较；超时、错误、短包均保留为失败。
