# 接口主机代码与测试骨架

适用：可通过 `read(offset)`、`write(offset,value)` 访问的 32 位 AXI-Lite IP，
例如 PYNQ DefaultIP；无 PYNQ 也能在主机离线生成和测试。Python 3.9+，标准库。

```sh
python scripts/generate_host.py assets/interface.example.json generated
python -m unittest discover -s generated -p test_host_api.py -v
```

输出目录中的同名文件不会覆盖；修改契约时使用新目录。
调用：把 generated 加到模块路径，`from host_api import RegisterAPI`，再执行
`api = RegisterAPI(ol.accel_0)`、`api.read_ID()` 等。用户必须先核对该 IP 的实际
VLNV、窗口与生成代码中的 CONTRACT 元数据。契约的 unit 为文档，不做自动换算。

不支持大小端转换、跨字寄存器、混合语义字段、读清除或并发事务原子性。读高位会
按契约位宽屏蔽，保留位规则需单独验收；写只允许范围内非负 Python int。

来源：早期 2 路与后续 22 路控制、寄存器回读和引脚绑定错位，说明协议/接口不能
靠口头约定。生成器为本次新增；离线验证覆盖访问权限、范围、W1C、契约冲突及
第二个无关题目的接口。未宣称验证其对应 RTL 或真实 PYNQ。
