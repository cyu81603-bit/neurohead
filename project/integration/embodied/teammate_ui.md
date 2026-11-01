# 同学原界面接入（2026-10-31）
保留incoming_20261029/gui_unified_app.py中原三栏_build_ui的布局、配色与组件，源文件保持不变。teammate_layout.py仅提取声明式布局；不导入旧板卡调度器。
默认全链路入口使用TeammatePanel，语义交互独立入口为项目根目录“启动语义交互.cmd”。原眼颈和面部标定窗口继续保留。
相机仅复用现有USB Cam共享源；开机不启动摄像头、麦克风或PWM。麦克风按钮使用当前有15秒上限及自适应噪声门限的ConversationVoice。表情开关只连接已运行且已开启活人感的唯一主控。
原直连UDP开关位置用于打开共享相机；原HTTP开关连接现用IntentLink。颈速、强度仍在标定主控操作，原三栏对应选择器只读；眨眼保留待确认状态。缺少真实回读的通道显示--，不填充假测量。
输入文字、语音识别、Ollama问答及SAPI播放均复用当前通过对话测试的后端，振幅表显示实际合成数据。不会运行旧NH22ExpressionRuntime或NH21UnifiedScheduler。
