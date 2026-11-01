# 工程完整性、黄金比对、报告工具

适用：普通 RTL/HLS/PYNQ 项目，不依赖机器人；Python 3.9+ 标准库。

```sh
python scripts/manifest.py create release_dir trusted.json
python scripts/manifest.py verify release_dir trusted.json
python scripts/golden_report.py expected.csv actual.csv --atol 0.000001 --rtol 0.00001 --output golden.json
python scripts/benchmark.py --output bench-run --samples 10 --warmups 1 --timeout 30 -- python my_repeatable_compute.py
python scripts/implementation_report.py reports --max-luts 10000 --output implementation.json
```

manifest create 默认收录根目录下全部普通文件；输出须位于被扫描根目录外，避免
自包含。不跟随符号链接，不收录空目录。verify 拒绝路径逃逸、绝对路径、大小写
别名、缺失/损坏文件、空清单；报告未列入清单的额外文件，须加 `--strict` 才拒绝。
清单不是签名，可信发布来源仍需维护。

CSV 为带表头的纯数值表，表头/形状严格匹配。可附 `--latency latency.csv`，
格式仅一列 `latency_ms`，至少一个非负有限数；p95 用最近秩法，需记录采样范围。
golden.json 保存原输入哈希与最大绝对/相对误差，输出 exit 1 表示不匹配。
CSV 浮点比较不用于超过 2^53 的精确整数；该场景需专用整数比较器。

benchmark.py 以 argv（shell=False）运行明确提供的可重复命令，自动生成 latency.csv、
benchmark.json 与每次 stdout/stderr；输出目录不能已存在。失败/超时立即停止并保留
失败样本；不只统计成功后掩盖失败。只用于可重复的计算/数据路径，不能反复执行
动作、烧写或复位。测量包括进程启动；timeout不保证清理命令派生的后台进程。

实现报告支持本包验证过的 Vivado 2026.1 文本表格及相同布局；不支持 JSON/中文化
表格或缺 Clock Summary 的报告，不能把解析失败填成 0。支持多时钟、Slice/CLB
LUTs 与 Registers。缺延迟/未约束端点默认失败；确有异步输出例外时提供
`--constraint-waiver "设计依据与审查记录"`，原始计数仍保留，结果不等于全接口时序验收。
工具不自动扫描 DRC；DRC、CDC、功耗需额外报告，缺失时写未检查。

来源：沿用并加强 R6.7 提交 skill 的哈希/实现检查经验，消除 clk_fpga_0 写死和
约束缺失被忽略的问题。原报告本次离线复算，不重新综合，不继承原项目234项测试
作为本技能测试。包内 validation 目录记录本次结果。无硬件验证。
