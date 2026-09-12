# 运行与复现说明

日常入口统一为本目录 `run.py`。问题三、四现均默认使用 `integrated` 联合调度：问题三为原七站布局 `original`，问题四为25站布局 `radial`。本次在原目录覆盖更新，没有新增版本目录。论文和旧支撑材料ZIP暂不更新，请直接运行本目录源码。

## 问题三最新调度优化

取消等待三个站点后的中途强制清除，采用更充分的联合路线搜索，并跳过确定无用的已知目标测量。搜索结束后仍必须处理所有已知目标，七站覆盖、几何安全清除与后备策略继续保留。

200场独立同场对照：均值从314.60降到 **282.24秒/源**，降低10.29%；P95从388.02降到350.07秒/源。200场全部完成，180场更快、1场持平，最差退化7.79%，无退化超过10%的场景。另100场压力场景全部完成。详见[Q3调度验证记录](results/q3_scheduling/README.md)。官方新策略效果仍需人工测试，不能将之前standard策略的两场日志当作本轮效果。

## 问题四与400秒/源目标

最新一轮覆盖试验已完成：22站候选在新200场同场对照中为486.51秒/源，当前25站对照为501.54秒/源，仅改善3.00%，未通过预设5%默认接入门槛。**问题四默认仍为 `integrated/radial`，400目标未达到。** 22站以显式 `--layout rings` 保留作研究复核，未设为默认。详见[最新Q4覆盖试验](results/q4_adaptive/README.md)。下面513.96秒/源为上一轮另一组独立场景结果，不能跨组直接算提速比例。

目标为多场测试的场均 `virtual_time_s / cleared` 不超过400秒/源，并全部清除、正常退出。

200场独立本地测试中，新方案平均 **513.96秒/源**；同场论文定位+原31站布局为768.56秒/源，论文定位+内收31站布局为692.38秒/源。均值分别降低33.13%和25.77%，200场均全部完成。19场达到400秒/源，最差710.06秒/源。**400目标尚未达到，官方表现仍需人工演练确认。**

60场额外压力测试全部完成，最坏压力场景约879.85秒/源，单独报告，不混入200场均值。详见[本轮验证记录](results/target400/README.md)。

## 优化版本与完整路径

本批优化的完整台账（采用的 + 失败的，避免重复投入）见 [OPTIMIZATION_LEDGER.md](OPTIMIZATION_LEDGER.md)。

版本标记：`student-opt-v1`（提交 `7119afb`）。当前推荐：Q3 用 `--q3-ring-guard aggressive`（独立 200 场 −12.92%，0 失败），Q4 用默认。

## 本轮优化候选（opt-in，默认不改变上面两条基线）

三个方向都先做成默认关闭的可选项，只有经过同种子配对验证的改动才改变默认：

- **问题四默认已启用** `close_discovery_on_upper_bound`：一旦由真实观测确认“已发现+已清除=16”（题目上限），就取消剩余站点的发现义务。62场配对中11个16源种子全部改善（均值比0.99213，最差1.0000，10改善/52持平/0退化）；非16源场景逐位不变。构造参数 `close_discovery_on_upper_bound=False` 可复现旧行为。
- **问题三 `--negative-observations`（默认关闭）**：把“同一目标在 p 收到、在 q 未收到”推出的中垂线半平面**只用于下一测点选择**；路由中心、站点跳过、清除证书与后备始终使用仅正观测外包区域。60个新种子均值比0.98621（t=−6.57），最差+0.17%。该半平面在现存场景下不会改变清除判定；用于排路会引入尾部退化（最差+8.64%），因此默认关闭。
- **问题四 `reschedule_after_step`（默认关闭）**：定位一次有效测量后返回任务池重新调度。62场均值比0.98275，但**不建议与 `close_discovery_on_upper_bound` 同时启用**：相对当前默认均值−1.4%但最差+15.2%，且交错会延迟第16个目标发现、使 closure 取消更少站点。有界切换（`reschedule_switches`）已验证不能消解该尾部。
- **问题四 `certify_channel_absence`（默认关闭）**：用真实 no_signal 位置证明某频道在某网格单元不可能存在源。证书本身正确（10源场景可证明10个无源频道整盘缺失），但两个布局的每个站都对至少一个单元必不可缺，故**不可能跳过任何测量**；保留为布局工具。

研究脚本：`negative_observations.py`（纯几何半平面）、`q3_negative_experiment.py`、`q4_reschedule_experiment.py`；对应单测 `test_negative_observations.py`、`test_q4_reschedule.py`、`test_q4_discovery_closure.py`、`test_q4_channel_absence.py`。证据在 `results/q3_negative*/`、`results/q4_reschedule*/`、`results/q4_closure/`、`results/q4_step_closure/`、`results/q4_step_switch/`、`results/q4_absence/`。

## 官方演练

在PowerShell输入：

```powershell
Set-Location "C:\Users\Carmela\Desktop\b\成果\support"
$teamId = Read-Host "请输入当前登录平台的参赛队号"
```

在平台另开问题四演练，等待接口就绪后运行：

```powershell
python run.py --mode official --problem 4 --robot-id $teamId --output practice_logs
```

启动行应显示 `strategy=integrated`、`layout=radial`，结果也记录这两个标识。每个新场次只运行一次，保存终端结果、客户端JSON/JSONL和平台导出的JLOG。

在平台另开问题三演练后，使用相同形式的命令即可运行新Q3调度：

```powershell
python run.py --mode official --problem 3 --robot-id $teamId --output practice_logs
```

问题三启动行应显示 `strategy=integrated, layout=original`，结果还包含 `scheduling_policy=joint_route`。`forced_targets`现在只统计全部搜索站点结束后处理剩余目标的次数，不再表示等待三站后强制处理。问题三可用 `--negative-observations` 显式启用本轮的负观测测点优化（默认关闭，见上节）。

此前策略可显式指定 `--strategy standard` 或 `--strategy paper` 用于对照；它们**不会启用本轮联合路线优化**。测试新优化请直接使用上面的默认命令。

`official` 表示连接官方HTTP接口；演练或正式模块由平台选择，程序不会自行开始场次。默认接口地址为 `http://127.0.0.1:2026`，修改过端口时用 `--url` 指定。

检查 `complete`、`normal_exit`，核对 `cleared` 与平台目标总数一致。以虚拟时间计算秒/源，不使用界面的开始和结束时间差。小区域光学尝试或后备搜索可能产生 `failed_clear`，未命中后会继续定位，不等同于程序失败；异常会写入 `.error.json` 并停止。

客户端日志不能替代平台JLOG，正式测试需按题目要求另行完成。包含队号的原始请求日志应保存在个人验证材料中，提交匿名支撑材料时处理身份信息。

## 本地检查与复现

依赖NumPy，Python 3.12环境已验证。

```powershell
python -m unittest discover -p "test_*.py" -v
python run.py --problem 4 --runs 30 --seed 2100000
python verify_target_experiments.py --runs 200
python verify_q3_scheduling.py --runs 200
python verify_q4_coverage.py --runs 200
```

复现脚本校验冻结源码SHA256，在临时目录运行原始对照实验，不连接官方平台，输出至 `results/target400/reproduction`。可用 `--runs 1` 检查入口。已使用的开发集及留出集不能在未来调参后再次宣称为独立验证。

显式对照参数保留在同一入口：问题三 `--strategy standard` 为本轮调度对照；问题四 `--strategy paper --layout original` 为原31站论文定位对照，`--strategy paper --layout compact` 为上一轮31站内收对照。`integrated`使用默认950米间距参数，问题三使用 `original` 布局，问题四默认 `radial`，研究候选可显式指定 `rings`。

历史研究记录见[论文定位研究](results/paper_localization/README.md)、[覆盖布局研究](results/coverage_optimization/README.md)及 `results/optimization`，用于追溯，不代表当前默认策略。

## 文件职责

| 文件 | 用途 |
|---|---|
| run.py | 统一入口、日志与参数检查 |
| joint_search.py | 问题四联合路线、选择性测量、小区域光学尝试 |
| joint_search.py | 问题四联合路线、选择性测量、小区域光学尝试；默认16上限发现关闭与每频道证书开关 |
| omni_search.py | 问题三联合路线、选择性测量与覆盖后收尾；可选负观测半平面测点 |
| negative_observations.py | 问题三正/负观测中垂线半平面的纯几何实现 |
| q3_negative_experiment.py / q4_reschedule_experiment.py | 本轮opt-in策略的同种子配对试验入口 |
| active_localization.py | 论文启发的有界误差主动定位 |
| solver.py | 通用动作、定位后备及对照策略 |
| geometry.py | 有界误差几何与连续覆盖构造 |
| coverage_geometry.py | 接收距离与凸包的连续区域覆盖检验 |
| backend.py / audit.py | 官方通信、本地模拟及逐步计时核查 |
| verify_target_experiments.py | 冻结源码的独立对照复现 |
| verify_q3_scheduling.py | 问题三冻结源码的独立对照复现 |
| verify_q4_coverage.py | 最新问题四覆盖候选的冻结复现 |
| test_*.py | 几何、协议、覆盖及入口检查（含本轮opt-in组件的专项单测） |
