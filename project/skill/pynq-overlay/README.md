# Overlay 加载与校验

适用：已有兼容 PYNQ 镜像和 Vivado `.bit/.hwh` 的全量 overlay；板卡、算法和
IP 名称均不固定。不支持部分重配置、XRT/xclbin、仅有裸机 ELF 或缺少 HWH 的资产。
只验证身份与加载流程，不能证明时序、外部波形或算法正确。

离线（Python 3.9+、仅标准库）：

```sh
python scripts/overlay_guard.py path/to/design.bit --ip design/accel_0 --manifest trusted.json
```

`trusted.json` 为 `{"files":{"design.bit":"64位SHA256","design.hwh":"64位SHA256"}}`；
脚本只验证这对文件；其他依赖（固件、dtbo、配置）也需在完整发布清单中验证。
省略 manifest 仍输出哈希，但 `trusted_hashes_verified=false`，不能视作可信校验。

板上 Python（安装本板对应版本 PYNQ 后）：

```python
import sys
sys.path.insert(0, "scripts")  # 在该 skill 目录运行，或改为脚本目录的绝对路径
from overlay_guard import load_overlay
ol, evidence = load_overlay("design.bit", ["accel_0"], manifest="trusted.json")
ip = ol.accel_0
print(ip.register_map)  # 先确认元数据/驱动读取是否有副作用
# value = ip.read(documented_offset)  # 仅使用当前地址表
```

不要只改板名复用位流；换板须重建 part、时钟、引脚、PS 配置和 HWH，再重新验收。
需要 dtbo 的设计还须扩展完整资产清单和加载参数；此 helper 不自动加载 dtbo。

来源：NeuroHead 早期 Pin3/W19 输出与实际 Pin10/V15 接线不一致、掉电后恢复需
核对位流/固件。提炼为资产→元数据→硬件身份→功能的分层验证。
验证：本包离线测试覆盖缺失 HWH、哈希损坏、IP 缺失、解析先于 download；
未完成真实 PYNQ 加载验收。官方依据见包根 `SOURCES.md`。
