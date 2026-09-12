# 本轮优化汇总（2026-09-12）

分支 `codex/q3-q4-upgrade`。基线为队友默认：Q3 `integrated/original`，Q4 `integrated/radial`。
所有对比均为**同种子配对**（同一 `LocalBackend` 场景跑多臂），时间单位秒/源，`mean_time_s = virtual_time_s / cleared`。

## 0. 结论总表

| 改动 | 开关（默认值） | 效果 | 建议 |
|---|---|---|---|
| Q4 16 上限结束发现义务 | `close_discovery_on_upper_bound=True` | 62 场均值比 **0.99213**，最差 **1.0000**，10 改善/52 持平/**0 退化** | **已启用为默认** |
| Q3 负观测半平面 | `--negative-observations`（关闭） | 60 场均值比 **0.98621**，最差 **+0.17%**，t=−6.57 | opt-in，可安全启用 |
| Q4 定位一步后重调度 | `reschedule_after_step=False`（关闭） | 相对当前默认均值比 0.98604，最差 **+15.2%** | opt-in，**不建议启用** |
| Q4 每频道缺失证书 | `certify_channel_absence=False`（关闭） | 证书正确但 **无法跳过任何测量** | opt-in，仅作布局工具 |

全量测试：`python -m unittest discover -p "test_*.py"` → **62 项全部通过**。

## 1. Q4：16 上限结束发现义务（默认启用）

一旦由真实观测确认「已发现 + 已清除 = 16」（题目给出的源数上限），剩余站点的**发现义务取消**，只继续清除已知目标。

62 场（1900011、1900112、1910000–1910059）：

| 指标 | 值 |
|---|---|
| 配对均值比 | **0.99213** |
| 中位 / p90 / 最差 | 1.0000 / 1.0000 / **1.0000** |
| 改善 / 持平 / 退化 | 10 / 52 / **0** |
| 取消站点总数 | 59 |
| 触发的 16 源种子 | 1900011、1900112、1910002、1910007、1910009、1910026、1910027、1910034、1910040、1910051、1910058 |

触发的 11 个种子全部改善（非 16 源种子逐位不变）：

| seed | 比值 | seed | 比值 |
|---|---|---|---|
| 1910009 | **0.8566** | 1910027 | 0.9209 |
| 1910007 | 0.9316 | 1910051 | 0.9598 |
| 1910002 | 0.9614 | 1900011 | 0.9615 |
| 1910058 | 0.9709 | 1910026 | 0.9718 |
| 1910040 | 0.9851 | 1900112 | 0.9923 |
| 1910034 | 1.0000 | | |

复现：`results/q4_closure/pilot_metrics.csv`、`pilot_summary.json`。
A/B 复现旧行为：构造参数 `close_discovery_on_upper_bound=False`（已实测与旧基线逐位一致）。

## 2. Q3：负观测半平面（opt-in）

数学：同一全向目标在 `p` 收到、在 `q` 未收到 ⇒ `2(q−p)ᵀg < ‖q‖²−‖p‖²`。
**只用于选择下一测点**；路由中心、站点跳过、清除证书与光学后备全部保持在仅正观测外包区域（完备性不依赖负观测）。

60 个新种子（995000–995059）：

| 臂 | 均值比 | 中位 | 最差 | t | 改善/持平/退化 | >5% |
|---|---|---|---|---|---|---|
| `measure`（仅影响测点） | **0.98621** | 0.99373 | **1.00168** | **−6.57** | 46/9/5 | 0 |
| `guard`（紧区域还改排路） | 0.98376 | 0.98650 | **1.08643** | −4.70 | 48/5/7 | 2 |

7 个种子（含退化案例 990025）：`measure` 均值比 0.990486、最差 1.00388（990003）；990025 从 226.886 降到 **223.899**（0.98684）。`guard`/`tight` 在该种子为 **+7.78%**。

诊断：负观测在现有场景下**从未改变清除判定**（`crossed19.99=0`），全部臂 `fallback=0`、`negative_region_fallbacks=0`。

复现：`results/q3_negative/`（7 种子 4 臂）、`results/q3_negative_new/`（60 种子）。
CLI：`python run.py --mode official --problem 3 --negative-observations --robot-id <队号> --output practice_logs`

## 3. Q4：定位一步后重调度（opt-in，不建议）

逐次测量后返回任务池重新调度；测量预算跨调度累计、小区域试探按区域状态去重、后备不可打断。

**相对未开 closure 的旧基线**（62 场）：均值比 0.98275，bootstrap 95% CI [0.97367, 0.99129]，最差 1.0571，51 改善/10 退化，符号检验 p=9.6e-8；后备 30→28，失败清除 365→337。

**相对当前默认（closure 已开）**（62 场，这才是实际增量）：

| 臂 | 均值比 | 中位 | p90 | 最差 | 改善/持平/退化 | >5% |
|---|---|---|---|---|---|---|
| step（无限切换） | 0.98604 | 0.99346 | 1.00607 | **1.1517** | 49/1/12 | 4 |
| step1（有界 1 次） | 0.98872 | 0.99577 | 1.02076 | 1.1517 | 47/1/14 | **5** |
| step2（有界 2 次） | 0.98604 | 0.99346 | 1.00607 | 1.1517 | 49/1/12 | 4 |

否决的两个变体：
- `stepskip`（额外禁止站点扫描已知目标）：均值比 1.00036，**最差 1.4670**，9 场 >5% —— 机会测量是目标收敛的信息来源，去掉后更多目标触发昂贵后备。
- 有界切换：不修复尾部（`step2` 与无限切换逐位相同，无调参空间）。

**负向交互（关键）**：交错调度延迟第 16 个目标的发现，使 closure 更晚触发、取消更少站点。
例：1910009 默认 17 站/取消 8，step 为 **20 站/取消 5**；1910026 上 step1 为 21 站。

复现：`results/q4_reschedule_new/`、`results/q4_reschedule_step/`、`results/q4_step_closure/`（2×2 因子）、`results/q4_step_switch/`（有界切换）。

## 4. Q4：每频道缺失证书（opt-in，零收益）

用**真实 no_signal 测量位置**判定某频道在某网格单元不可能存在源（`C ⊆ conv(P_C)` 且所有 `‖p−x‖ ≤ 1000`）。

13 场（含 11 个 10 源场景）：

| 指标 | 值 |
|---|---|
| 整盘缺失证明 | 110 次（10 源场景的 10 个无源频道全部被证明） |
| 跳过的测量 | **0** |
| 时间 | **逐位不变**（均值比 1.00000） |
| 每站对单元的必不可缺性 | radial **25/25**、rings **22/22** |

结构性原因：每个站都对至少一个网格单元必不可缺，因此每个站必须测量每个未决频道——缺失证书**不可能减少任何测量或站点访问**，只能在最后确认 `certify` 的结论。已固化为测试。

复现：`results/q4_absence/`（`pilot_summary.json` 含 `essential_stations`）。

## 5. 清理与一致性修正

- `results/q4_adaptive/trace_fixtures.json` 旧 digest/mean 对应更早被取代的求解器状态。已实测：提交的 `frozen_sources.json` 候选（`verify_q4_coverage.py` 还原）现在重跑与当前生产 rings 逐位一致（digest `44804c3d`/`de114dda`/`82322fb2`，mean 完全相同），故陈旧的是 fixture。已重冻并加 `results/q4_adaptive/PROVENANCE.md`。
- 还原被单次离线运行覆盖的 `results/local_q3.csv`、`results/local_q3_example.json`。
- `.gitignore` 忽略 `__pycache__/`、`*.pyc`，16 个被跟踪的 `.pyc` 移出版本控制。

## 6. 文件索引

| 内容 | 路径 |
|---|---|
| Q3 负观测（7 种子 4 臂） | `results/q3_negative/` |
| Q3 负观测（60 新种子） | `results/q3_negative_new/` |
| Q4 step vs stepskip（旧基线） | `results/q4_reschedule_new/` |
| Q4 step（旧基线，62 场） | `results/q4_reschedule_step/` |
| Q4 closure 默认（62 场） | `results/q4_closure/` |
| Q4 step × closure 2×2 | `results/q4_step_closure/combination_summary.json` |
| Q4 有界切换 | `results/q4_step_switch/switch_summary.json` |
| Q4 每频道证书 | `results/q4_absence/pilot_summary.json` |
| 试验入口脚本 | `q3_negative_experiment.py`、`q4_reschedule_experiment.py` |
| 专项单测 | `test_negative_observations.py`、`test_q4_reschedule.py`、`test_q4_discovery_closure.py`、`test_q4_channel_absence.py` |

每个目录内的 `pilot_metrics.csv` 为逐场原始记录（seed、各臂时间、测量数、后备数等），`pilot_summary.json` 为聚合与配对统计。
