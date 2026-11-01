---
name: fpga-commissioning
description: Diagnose FPGA-controlled actuators using layered digital and physical evidence, preserve calibration and channel ownership, and prevent stale AI decisions from replaying actions during commissioning.
---

# 从数字到实物的执行机构调试

读 [README.md](README.md) 和 [references/playbook.md](references/playbook.md)。
本 skill 不预设引脚、脉宽、电压、通道数或机构；按目标板和执行机构的数据手册、
已确认接线和校准配置建立 profile。原项目状态仅作历史案例，不能充当当前现场确认。

先保存目标、数字回读、测量点、时间、资产/标定哈希、供电接线与操作者反馈。
区分“请求已选择→控制器已接受→PWM寄存器到位→接头实测波形→实物运动→闭环误差”；
不能从前一层推断后一层。用 `scripts/trial_evidence.py` 对声明做离线一致性审核。

从最小可区分原因的对照开始：软件映射与 XDC、接头处供电/信号、已知正常器件、
空载/带载与机械干涉。既有安装/接线改变使原校准失效；有卡滞、过热或输出不符合
预期则停止该试验，不反复扩大行程。停止 PWM、回中、保持和断电不是同一动作，
先按具体机构确定失能策略；重力负载可能需要支撑。

真实动作仅在用户请求的范围内，使用当前已验证端点与现场条件；本包离线工具不
产生任何动作。未测的机械角度、全行程和故障恢复保持待验，不由一次小步外推。

多来源控制使用单一仲裁与通道 owner：追踪/表情/手动不能同时直接写同一路。
禁止通道在 enable、neutral、return、watchdog 路径也要保持策略，不能只过滤动作入口。

AI 交互时共享同一次上下文快照，聊天与动作判断可独立完成；动作仅选择白名单 ID。
用请求 ID/取消代次丢弃迟到结果；意图选择、语音描述均不构成执行证据。
在离线模拟中验证取消、重复请求、旧控制者和被禁通道，然后才评估实物效果。

交付变更前后证据、成功与失败记录、已知故障、恢复入口和下一步最小检查。
