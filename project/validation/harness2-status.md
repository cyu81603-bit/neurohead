# Harness² 状态与后续入口

2026-11-01，在本聊天项目根目录完成：

- 已执行 `harness2 guide`、`init --yes --executor codex --auth login`。
- 项目根新增 AGENTS.md，未改动全局 Codex 配置与F盘工程。
- 三个 files 任务及对应隐藏 rubric 已写入 `.harness2/tasks/`：
  portable-register-api、dma-timeout-review、evidence-boundary。
- doctor：Codex CLI可用，executor/improver/selector等配置可识别；provider尚未登录。
- dry-run 命令已尝试，因同一登录前置条件退出，未输出有效任务计划/调用数。
- status：无 runs。未运行 run/eval/apply，不存在模型优化或候选 diff，不声称已优化。
- 所有本包结果来自直接编写、官方格式检查、离线回归与原报告复算。

阻塞原文：

```text
chatgpt-login: not logged in for harness2; run `harness2 login codex`
```

需要进一步模型优化时，由用户在当前项目根完成独立登录：

```powershell
$env:PYTHONUTF8='1'
& "$env:USERPROFILE/.local/bin/harness2.exe" login codex
& "$env:USERPROFILE/.local/bin/harness2.exe" --json doctor
& "$env:USERPROFILE/.local/bin/harness2.exe" run --dry-run --only-tasks portable-register-api,dma-timeout-review,evidence-boundary --k 1 --max-calls 12 --workers 1
```

12是拟议硬上限，不是成功 dry-run 给出的调用估计；实际计划待登录后生成。
当前 CLI 的 `--json` 为全局参数，放子命令之前。

随后展示 dry-run 的任务与调用数，取得用户同意才运行同参数的非 dry-run，并保留
`--max-calls 12`。结束后 `--json status`、`diff`；展示差异并取得同意后才能 apply。
不要直接把模型输出复制到 skill。

依据为已读取的 [harness2/SKILL.md](C:/Users/ASUS/.codex/skills/harness2/SKILL.md)：
“Ask for the user's go-ahead before `harness2 run` or `harness2 eval`”；CLI guide另要求
“Before `harness2 run` or `harness2 eval`, show the person the plan from
`harness2 run --dry-run` and get their go-ahead.” 登录阻塞不是用户拒绝授权，不能假装
得到计划或跳过这个明确门槛。

本目录附 `harness2-task-specs.json`，可在其他项目重新创建相同评估任务；原始seed为
相应 skill 的副本，不依赖NeuroHead硬件。本包没有分发用户的登录或认证材料。
