# NeuroHead R6.7

2026嵌赛AMD具身智能赛道作品。22路仿生机器人头，结合本地语音对话、视觉追踪、自然语言动作库与Zynq-7020 PWM控制。

## 完整工程下载

[下载R6.7完整工程](https://github.com/cyu81603-bit/neurohead/releases/tag/r6.7-final-20261101)。Release附件包含完整提交ZIP、SHA256和校验结果。Git源码仓库保留原始工程文件，约228MiB的SenseVoice INT8模型通过Release分发。

完整ZIP的SHA256：

```text
e5e00c42d881cf15281d725ff60515caabe547db7f8e3a42c65d194c495670f3
```

## 目录

|目录|内容|
|---|---|
|project/src|FPGA RTL、PS固件及PC控制源码|
|project/integration|同学原语义界面、语音与视觉集成、网页处理流程展示|
|project/board|AX7020引脚约束与接线资料|
|project/build|原位流、固件、资源时序报告及构建证据|
|project/sim|仿真、离线测试和当前验证结果|
|project/skill|五项可复用FPGA/PYNQ技能及脚本|
|project/scripts|构建、启动、恢复与验证入口|
|project/environment|工具链与新机器复现说明|
|tools|Release模型恢复工具|

原工程说明见[project/readme.md](project/readme.md)，复现条件见[project/environment/reproduction.md](project/environment/reproduction.md)。project子目录对应完整ZIP内的工程根目录。

## 克隆后恢复模型

需要Python 3。以下操作只下载并校验文件，不启动机器人。

```powershell
git clone https://github.com/cyu81603-bit/neurohead.git
cd neurohead
python tools/restore_model.py
python project/verify_package.py
```

若已下载完整ZIP：

```powershell
python tools/restore_model.py --archive F:/path/to/neurohead_r6_7_final_20261101.zip
```

恢复脚本验证完整ZIP与模型的SHA256，只恢复指定模型，不覆盖源码。模型恢复后，project/manifest.json可验证完整冻结工程。独立下载完整ZIP也可直接解压复现。

## 验证与实现范围

R6.7冻结控制与对话策略；PC执行视觉及本地模型推理，AX7020 PS处理UDP与协议，PL产生22路PWM和硬件看门狗。当前架构没有将4B语言模型部署到AX7020，也没有使用PYNQ/DMA执行视觉推理。

276项离线软件测试通过；RTL仿真通过。22路PWM的no_output_delay警告采用有文件哈希绑定的接口例外审查，原始报告保持不变。详情见[当前验证结果](project/sim/results/readme.md)与[I/O审查](project/data/io_constraint_review.md)。

离线验证不代表本轮实物验收。上下眼球未响应、部分模型措辞失败及未测性能均保留原记录。启动和运动前须按原工程说明确认现场供电、接线与头部支撑。

## 许可与来源

仓库现有LICENSE保持原样，第三方组件分别遵循其自身许可与版权声明。模型、AMD/Xilinx BSP、视觉支持代码及同学界面来源见[第三方说明](project/third_party.md)。第三方内容不因仓库根许可证而改授许可。

本仓库不包含另行准备的技术报告；赛事提交材料以团队最终上传内容为准。
