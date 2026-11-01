# 大模型协作记录（独立附件，不是技术报告）

真实开发过程说明见r6_7_development_record.md；真实本机模型输入/上下文、模型动作解释、语言回答、预期值与通过/失败见*_actual_model_results.json。提示词原文保存在integration/embodied/qwen_brain.py，测试输入在scripts/check_action_context.py、check_wink_defaults.py、check_dialogue_context.py、check_parallel_dialogue.py。脚本加--live-llm可重跑，仅本地HTTP调用，不播放音频、不发PWM。

纠错链：动作回应被固定句覆盖→用户要求说归说、执行归执行→两路并发各自消费结果；上下文缺失→同一轮共享对话快照及单独意图记录；默认wink错误拒绝→未指定侧别默认右眼、明确左眼请求不偷换；反复播报历史动作→提示词约束当前轮语义、否定和取消不重放。软件测试验证请求/取消隔离，实际模型检查保留剩余措辞失败。

本附件是从现有开发说明及测试产物整理的记录，非伪装成逐字完整IDE对话导出。模型实际输出不重写，不剔除失败样本。没有人为生成“自我纠错回答”冒充模型。
