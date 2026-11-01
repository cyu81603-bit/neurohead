# DMA 搬运封装

适用：PYNQ、AXI DMA simple mode、双通道、非循环、完整连续 buffer、固定等长帧。
不支持 SG/cyclic、VDMA、Micro DMA、切片／部分传输、多进程共享引擎或非等长输出。
调用方须按真实 IP 参数填写宽度、DRE 和最大长度；不能默认 DRE 已启用。

```python
import sys
sys.path.insert(0, "scripts")  # 在该 skill 目录运行，或改为脚本目录的绝对路径
from pynq import allocate
from dma_transfer import exchange, TransferFailure
tx = allocate(shape=(256,), dtype='u4')
rx = allocate(shape=(256,), dtype='u4')
tx[:] = range(256)
try:
    measurement = exchange(ol.axi_dma_0, tx, rx, timeout=1.0,
        max_bytes=16383, tx_word_bytes=4, rx_word_bytes=4,
        tx_dre=False, rx_dre=False)
    print(measurement)
except TransferFailure as failure:
    print(failure.snapshot)
    # failure.buffers 保留活动分配；确认硬件 quiescent 后由恢复流程回收。
    raise
else:
    # 此处再比对 rx 与黄金结果，成功或不匹配均可安全回收已完成的分配。
    tx.freebuffer()
    rx.freebuffer()
```

例中 max_bytes 和宽度仅用于展示调用，不是其他设计默认值。普通参数错误在启动前
抛 ValueError/TypeError，buffer 可回收。TransferFailure 表示已进入设备调用路径，
调用方应保存异常及分配直到恢复完成；不要用无条件 `finally: freebuffer()`。

离线验证使用假 DMA/假 buffer，覆盖先接收、缓存同步、超时停止、错误和回收边界。
运行时要求 `dma.description['parameters']` 明确包含 `c_include_sg=0`、
`c_micro_dma=0`，拒绝其他模式或元数据缺失；停止态通道不自动启动。初次运行时
PYNQ simple driver 的 idle 可能为0，封装只在其 `_first_transfer=True` 时允许该状态；
这是经官方源码核对的私有兼容点，换PYNQ版本必须复核，未知状态按忙碌拒绝。
尚未上 PYNQ 板卡验证。来源：项目中的无界等待、过期结果和数字状态不等于完成
的经验迁移；具体缓存/DMA API 来自官方文档，未声称原 NeuroHead 使用过 DMA。
