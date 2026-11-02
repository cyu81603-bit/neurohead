# NeuroHead R6.7 最终提交工程

基于 AX7020 / AMD Zynq-7000 xc7z020clg400-2 的22路机器人头。最终功能版本冻结为 R6.7：本地语音/视觉交谈、共享上下文的并发聊天与动作判断、眼颈追踪、表情与语音嘴形、右眼wink和自然语言动作库。保留同学原三栏语义界面与只读视觉流程网页。

版本恢复依据见 data/version_provenance.json：按逆序覆盖R6.10、R6.9、R6.8修改前备份，恢复12个文件，移除后续新增模块/测试。不是把现版本标题改成R6.7。控制源码不作功能增改；新增内容仅用于提交、复现、验包。当前正在运行的工程没有被替换。

## 目录与提交项对照

|目录|内容|
|---|---|
|src/|PL RTL、PS裸机C/lwIP、PC Python控制与协议|
|sim/|仿真测试、回归测试、results/中的本次执行日志|
|build/reports/|Vivado2026.1资源、时序、DRC报告、bit和xsa|
|build/firmware/|已验证PS ELF/BIN|
|scripts/|硬件构建、固件构建、上板、离线验证、启动脚本|
|board/|AX7020针脚约束和引脚表|
|config/|R6.7参数与原实物标定配置|
|integration/|原同学语义交互界面、并发对话与视觉网页|
|data/|历史板测、原始模型输出、版本来源、实测与参考对照|
|skill/|替换后的五项FPGA/PYNQ技能，保留原包脚本与模板|
|tests/ 与 validation/|新技能包的离线测试与原始验证记录|
|report/neurohead_design_report.pdf|用户提供的设计报告PDF，按原文件直接打包|
|report/llm_collaboration/|真实提示词所在源码、实际模型回答与纠错记录|
|vendor/|视觉源码与YuNet模型及原许可|
|support/|原始眼部禁止记录、PS BSP源码/头文件/静态库与依赖布局说明|
|environment/|原环境版本、依赖清单、外部资产说明|

工程目录使用英文路径；新技能保留SKILL.md、README.md等原包标准名称。上板工程由Tcl重建，不提交含机器绝对路径的大型Vivado缓存。用户提供的设计报告PDF纳入report/目录，未从Word转换。提交归档使用RAR格式，文件名为NeuroHead智能仿生头.rar。

## 从零复现（Windows）

1. 解压到短英文路径；先运行 `python verify_package.py`。完整性校验只读，无硬件连接。
2. 安装Python3.11（含Tk）、PowerShell7、Vivado2026.1、Vitis2026.1；固件原构建使用Vitis2022.2 ARM工具链和配套BSP，此例外已声明。Icarus Verilog和GCC用于离线RTL/C验证。
3. `python -m venv <venv>`，`<venv>/Scripts/python -m pip install -r environment/requirements.txt`。原环境完整版本见environment/original_environment.json。SAPI需安装Windows中文语音。
4. 路径约束与首次安装见environment/reproduction.md。原R6.7保留固定F盘共享锁、guard、Ollama与工具路径；不是任意路径免配置版本。不得用安装脚本覆盖现有项目。新的机器可用scripts/install_support.ps1安装缺失的外部辅助文件。
5. `python scripts/validate_submission.py --gcc D:/MinGW/bin/gcc.exe --iverilog C:/iverilog/bin/iverilog.exe --vvp C:/iverilog/bin/vvp.exe`：控制器/协议、集成、RTL与C离线回归，日志写sim/results/。没有板卡动作。需要PowerShell7才能运行原恢复资产检查。
6. `python src/pc/lifelike_panel.py --self-test` 和 `python integration/embodied/embodied_app.py --self-test`：空闲GUI自检，不启动相机/麦克风/舵机。
7. `pwsh -File scripts/run_hw.ps1` 从RTL/Tcl重建PL，详见scripts/reproduce_build.ps1；固件可使用包内BSP与build_ps_portable.ps1重建。均不自动烧录。bit是否逐字节一致受工具/主机影响，以约束、DRC、资源、时序和功能结果复核。
8. 真正上板前托稳头部、关闭外部舵机电源、拔开全部PWM，板卡独立供电。阅读scripts/load_22.ps1，现场确认后才传-ServoPowerOff -SignalsDisconnected。先做只读通信确认，再按原接线与共地恢复。板卡掉电后需重新加载，当前不是已验证SD自启动方案。
9. 安装Ollama、拉取qwen3.5:4b；配置路径见integration/embodied/config.py。运行 `pwsh -File scripts/start_submission.ps1` 打开R6.7待机界面，现场确认后由操作者开始会话、开启追踪/表情/动作库/麦克风。摄像头必须指定USB Cam，不回退内置相机。
10. 视觉处理网页：`pwsh -File integration/vision_dashboard/start_dashboard.ps1`，访问http://127.0.0.1:8766/。页面只读显示共享视觉与控制状态，不能单独启动舵机。

## 真实实现与边界

推理在本地PC执行，AX7020的PS负责UDP命令与状态，PL负责22路PWM与看门狗。可称本地边缘推理与PC/ARM/FPGA异构协同；没有把4B模型或视觉网络部署到AX7020，没有使用PYNQ、HLS或DMA加速，不申报PYNQ技能加分。

R6.7自动颈部范围为左右±100μs、俯仰±100μs；追踪速度50/35μs/s，参考1500/1270/1500。没有包含R6.8及之后的加速、目标点保持和扩行程。CH6/7自动屏蔽避免挡相机，CH16未许可；默认wink为右眼；下颚仅1200张嘴/1300闭嘴两个已测端点。标定属于这一台机械装配，不可直接复用到另一台。

当前上下眼球故障尚未解决：有5V、PWM寄存器变化但舵盘不动；用户暂不便进行换线对照。历史基本跟随成功不能代替当前故障修复。R6.7恢复配置不代表该故障已消失。

模型真实测试：动作上下文8/8，wink动作选择14/14，但含口语行为的wink综合13/14、对话7/8，全部语言测试未通过。聊天与动作HTTP并发不证明GPU计算并行。PWM回读不代表测得关节角度；端到端时延、追踪角度误差、掉帧率等没有统一仪器实测，不填造数值。

## 提交前人工项

见submission_checklist.md：团队/作者/组别、团队原创部分开源许可和仓库链接需由团队填写；第三方模型与BSP遵循原许可。本包不冒填身份、不自动上传。指南未在所读3.3.5节单列视频要求，若报名系统另有视频/图片/命名要求需由团队补传。用户提供的设计报告PDF位于report/neurohead_design_report.pdf，按原PDF直接纳入。

验证结果：sim/results/verification.json；本轮离线报告为276项Python检查全部通过。C协议使用包内预编译程序（--prebuilt-protocol），未重新编译；xsdb依赖的单项Tcl检查未重跑。本轮没有重新执行Vivado综合实现或向板卡发送命令，实物验收标记为未完成。构建与运行的外部依赖及许可边界已单列，见environment/reproduction.md、third_party.md。

## 技能包替换

原skill目录已整体替换为neurohead-fpga-skills.zip中的五项技能：pynq-overlay、pynq-dma、pynq-interface、fpga-evidence和fpga-commissioning。配套tests、validation、SOURCES.md与VALIDATION.md一并收录。运行 `python -B tests/test_suite.py` 进行38项离线测试；新PYNQ工具尚无真实板卡验证，不据此宣称硬件迁移成功。工程完整性入口为 `python verify_package.py`。

## I/O约束审查结果

22路PWM的缺少输出延迟约束项已完成自动化文档审查，状态为审查通过、接受限定接口例外。原警告和报告数值保持不变。依据和适用范围见data/io_constraint_review.md，复核入口为scripts/validate_submission.py；本轮276项软件测试通过。此结论不覆盖未完成的实物排障、波形测量或团队人工项。
