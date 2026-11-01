# 外部依赖与原路径契约

本次冻结的是R6.7功能版本；不为打包而修改其控制策略或全局路径。Windows、Python3.11、Tk、PowerShell7；原测试Python位于F:/NeuroHead/environments/embodied_20261029/Scripts/python.exe。

新机器建议复刻布局：本目录复制到F:/NeuroHead/builds/nh22_v26_1029（若已存在，禁止覆盖，改用另一台机器/单独磁盘），虚拟环境建到上述environments目录。运行scripts/install_support.ps1只安装缺失辅助文件，不加载板卡。无需复制21路工程源码，但共享锁/视觉日志目录F:/NeuroHead/builds/nh21_20261024/build必须可写；原始guard位于F:/NeuroHead/workspace/neurohead_fpga_2026/data/joint_setups/eye_horizontal.json，原SHA256保持不变。不要修改guard里的motion_inhibited以绕过保护。

原启动器和恢复GUI有固定Python、Vivado、Vitis、GCC和Icarus路径。新机器需编辑本机副本的启动/构建路径；scripts/start_submission.ps1提供显式-Python入口。相机config/camera.json的ffmpeg原在E盘，必须改为本机安装路径。更新配置后完整性清单相应变化是预期行为，不应冒称仍是原冻结文件。

需另行安装：Ollama（原F:/Ollama/ollama.exe）、qwen3.5:4b（原F:/Ollama/models）、ffmpeg、中文SAPI声音、Python、FPGA工具链。未打包几GB模型权重；模型标签不是不可变版本，environment/ollama_model_snapshot.json记录本机可读版本信息（如服务可用）。权重缺失时不能进行真实LLM交谈，离线模拟回归不依赖权重。

包含SenseVoice INT8 ONNX/token和YuNet模型；第三方权利见third_party.md。PS BSP及静态库来自Vitis2022.2，build_ps_portable.ps1指定此版本工具链；不能声称PS固件已由2026.1重新编译。现bit为2026.1实构建，PS固件复用且有板卡通信记录。

没有执行此次重新上板或实物动作验收；data/下是明确标注日期的历史证据。启动即待机，实际运动需要当前接线供电和头部支撑确认。

本次重跑C需加--prebuilt-protocol；原编译器缺少DLL，详情见sim/results/readme.md。readme中的默认命令保留为正常工具环境下从源码构建路径，不把使用预构建文件当作重编成功。供应商xsdb单项Tcl测试未重跑。
