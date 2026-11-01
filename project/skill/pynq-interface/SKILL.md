---
name: pynq-interface
description: Generate a checked Python host register API and mock test skeleton from an explicit AXI-Lite register contract for PYNQ, HLS or custom RTL IP.
---

# 接口契约到主机代码

读 [README.md](README.md)，将实际 HWH、HLS header 或 RTL 地址解码逐项核对后
整理为 `assets/interface.example.json` 的契约。示例是虚构寄存器，不是 NeuroHead
寄存器表；禁止直接用于未知 IP。

契约写明 IP 路径、VLNV、地址窗口和每个 32 位寄存器的 offset、位宽、access、
单位及副作用。生成器仅接受无字段混用的 ro/rw/wo/w1c；clear-on-read、64 位、
打包字段、数组、指针、自动重启需要专用实现，不能把它们降级为 rw。

运行 `scripts/generate_host.py contract.json output_dir`，校验重名、重叠、对齐、
窗口越界与非法标识符。输出 `host_api.py` 和独立 `test_host_api.py`；Mock 测试仅证明
主机访问契约，不证明 RTL、总线或实物行为。先运行它，再进行板上身份和只读检查。

生成的 API 使用注入的 IP `.read/.write`，不硬编码物理基址；从当前 overlay 取得
driver，核对实际 VLNV/窗口后传入 `RegisterAPI(ip)`。W1C 直接写掩码，绝不 RMW。
不生成 start/enable 等自动调用，不读 wo/w1c，不写 ro。

交付接口表、机器契约、主机代码、测试结果及“契约来源→代码行→寄存器”对应。
换算法或板卡时先换契约并重建，不能只改变量名沿用老偏移。
