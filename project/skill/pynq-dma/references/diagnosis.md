# DMA 排障清单

|触发|检查顺序|证据/失效边界|
|---|---|---|
|recv 长期不 idle|保存双通道 DMASR/register_map；查 TLAST、TVALID/TREADY、数据帧长、TKEEP|ILA 波形才支持 stream 握手结论；无 TLAST 可能不结束|
|decode/slave/internal error|地址范围、HP 端口、时钟/复位、DRE 对齐、长度、DDR buffer|保留原始状态；不清错误后直接称通过|
|结果是旧值|输入原 buffer 是否被换掉、flush/invalidate、coherent、完成状态|缓存同步不修复算法/流端协议|
|第二次运行失败|第一次是否真正结束、auto_restart、旧对象、IP 状态|不自动重置或无限重试|
|大帧失败小帧通过|按 IP 导出的 length width 确定上限和 TLAST 分段|教程里的 14 位不是固定全局参数|
|aligned 报错|分别检查 MM2S/S2MM width 与 DRE，地址及 transfer 字节数|本封装无 offset；切片另实现|
|超时后 Python 已返回|确认 halt/idle 和 outstanding transaction，记录 buffer 所有权|超时不等于 DMA 停止；保留分配至板级恢复|

验收至少包含：零长度拒绝、单帧、连续多帧、最大合法长度、超限、断流/无 TLAST、
输出黄金比对。故障注入只在无危险外设的专门测试设计上进行。
