# 运行与复现说明

日常入口统一为本目录 `run.py`。按用户要求，**Q3已替换为Fusion推荐方案：`aggressive + probe60`、原子定位**；**Q4保留原有22站 `rings + adaptive`**。Q3在原点收到至少一个源时使用1123米六点环，否则保留1558.85米大环。直接用原来的两条命令即可，无需另加参数。

目标仍为多场场均 `virtual_time_s / cleared`：Q3低于250秒/源、Q4低于440秒/源，全部清除、正常退出。替换依据为用户明确选择Fusion Q3，不宣称本次替换带来额外平均提速：此前同场200场当前旧Q3为247.33、Fusion推荐为247.38，整体持平，详见[方案对比](results/validation/fusion_q3/README.md)。替换后Q3与Fusion动作一致、Q4与替换前动作及依赖源码一致的核查见[替换验证](results/validation/q3_replacement/README.md)。

之前hex/adaptive的400场本地均值243.32、9场官方均值254.36属于已替换的旧Q3，不能算作Fusion Q3的成绩。历史见[布局验证](results/scan_route/README.md)和[九场官方核查](results/validation/q3_hex_official_batch.md)。Q4最近两场官方均值436.64，对应仍然保留的Q4策略。

Q3默认使用Fusion原子定位、60米小区域试探和条件缩环；推荐配置不启用负观测，可选 `--negative-observations` 使用Fusion的正负观测中垂线半平面进行测点规划。Q4继续分步定位及大可行区域的测量点评分，部分定位最多四轮后进入原有完整定位和后备流程。

Q3可用 `--q3-ring-guard off --q3-probe-radius 0` 对照Fusion原始默认；旧Q3 tight/hex/adaptive从生产入口退役，历史策略仅通过冻结源码复现。Q4的 `--service-policy atomic` 仍保留原有语义与radial默认布局。下方历史记录只说明此前决策，不代表当前默认。

## 历史布局复核（当前默认以上方说明为准）

此前3100000—3100199种子的配对中，问题三八站平均节省9.78%；问题四仅换22站平均节省3.57%，当时恢复了25站默认。本轮Q4同时改变定位调度，采用依据为新的配对结果，不是仅换布局。详见[历史布局复核](results/validation/user_layout_review/README.md)。

问题三：原点加半径1558.846米六点环（7站）改为原点加半径1000米七点环（8站）。接收只在1000米内有保证，故覆盖条件即“每点距某站不超过1000米”；由余弦定理得闭式判据 2000cos(π/7)=1801.938米 > 1800米，最紧点为π/7方向边界点，距站998.2545米，余量1.75米。保留起点原点的扫描，没有额外移动成本。固定站点开放巡回9353米降为6207米。

问题四：25站 `radial` 和22站 `rings` 均已有覆盖验证。

此前820000至820199的200场对照中，问题三平均每源284.29→255.81秒，节省10.02%；问题四508.99→492.80秒，节省3.18%。该种子区间在早期实验中已使用，不再作为全新独立留出集。新复核中，问题三279.43→252.09秒，问题四491.53→473.98秒，800次配对运行全部完成。问题四仍未达到5%平均收益门槛，且最大耗时和后备次数增加，不能称全面改善。Q3旧布局可用 `--layout original` 对照，Q4候选可用 `--layout rings` 对照。

此前八站Q3和22站Q4布局的压力检验：七种困难情形各60场共420场全部完整清除，含接收半径取下限1000米与问题四全定向配置。这些是历史策略的测试记录。

四项已实现但未采用的候选（自适应覆盖记账、精测点改基准、覆盖顺序优先内圈、外环压到1850米以下）均在配对对照中变慢或无改善，已回退，原因见 `../效率优化验收报告.md`，以免重复尝试。

## 问题三历史调度优化

取消等待三个站点后的中途强制清除，采用更充分的联合路线搜索，并跳过确定无用的已知目标测量。搜索结束后仍必须处理所有已知目标，七站覆盖、几何安全清除与后备策略继续保留。

200场独立同场对照：均值从314.60降到 **282.24秒/源**，降低10.29%；P95从388.02降到350.07秒/源。200场全部完成，180场更快、1场持平，最差退化7.79%，无退化超过10%的场景。另100场压力场景全部完成。详见[Q3调度验证记录](results/q3_scheduling/README.md)。官方新策略效果仍需人工测试，不能将之前standard策略的两场日志当作本轮效果。

以上为调度改动本身的记录，站点布局仍为当时的七站；本轮再换用八站布局后，同一入口在种子820000起的200场上为255.81秒/源。两处数字属不同轮次，不可相减。

## 问题四历史实验（原400秒目标）

仅换22站的历史对照曾得到3.00%和3.57%的平均收益，当时没有作为默认保留。详见[历史复核](results/validation/user_layout_review/README.md)。下面513.96秒/源为更早的独立场景结果，不能跨组直接计算提速比例。

历史目标为多场场均不超过400秒/源；用户现已将Q4目标调整为440秒/源。

200场独立本地测试中，新方案平均 **513.96秒/源**；同场论文定位+原31站布局为768.56秒/源，论文定位+内收31站布局为692.38秒/源。均值分别降低33.13%和25.77%，200场均全部完成。19场达到400秒/源，最差710.06秒/源。**400目标尚未达到，官方表现仍需人工演练确认。**

60场额外压力测试全部完成，最坏压力场景约879.85秒/源，单独报告，不混入200场均值。详见[本轮验证记录](results/target400/README.md)。

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

启动行应显示 `strategy=integrated`、`layout=rings`、`service_policy=adaptive`。每个新场次只运行一次，保存终端结果、客户端JSON/JSONL和平台导出的JLOG。

在平台另开问题三演练后，使用相同形式的命令即可运行新Q3调度：

```powershell
python run.py --mode official --problem 3 --robot-id $teamId --output practice_logs
```

问题三启动行应显示 `strategy=integrated, layout=original, service_policy=atomic, ring_guard=aggressive, probe_radius=60`。`layout=original` 是起始布局标签；结果中的 `ring_activated=1` 表示已切换1123米环，0表示保留大环。另有 `extra_probe_attempts`、`extra_probe_successes` 记录光学尝试。旧命令中的 `--layout hex/tight` 或 `--service-policy adaptive` 不再用于Q3。

此前策略可显式指定 `--strategy standard` 或 `--strategy paper` 用于对照；它们**不会启用本轮联合路线优化**。测试新优化请直接使用上面的默认命令。

`official` 表示连接官方HTTP接口；演练或正式模块由平台选择，程序不会自行开始场次。默认接口地址为 `http://127.0.0.1:2026`，修改过端口时用 `--url` 指定。

检查 `complete`、`normal_exit`，核对 `cleared` 与平台目标总数一致。以虚拟时间计算秒/源，不使用界面的开始和结束时间差。小区域光学尝试或后备搜索可能产生 `failed_clear`，未命中后会继续定位，不等同于程序失败；异常会写入 `.error.json` 并停止。

客户端日志不能替代平台JLOG，正式测试需按题目要求另行完成。包含队号的原始请求日志应保存在个人验证材料中，提交匿名支撑材料时处理身份信息。

## 本地检查与复现

依赖NumPy，Python 3.12环境已验证。

```powershell
python -m unittest discover -p "test_*.py" -v
python run.py --problem 4 --runs 30 --seed 2100000
python verify_target_pair_experiments.py --problem 3 --runs 300
python verify_target_pair_experiments.py --problem 4 --runs 200
python verify_target_experiments.py --runs 200
python verify_q3_scheduling.py --runs 200
python verify_q4_coverage.py --runs 200
```

复现脚本校验冻结源码SHA256，在临时目录运行原始对照实验，不连接官方平台。本轮复现输出至 `results/target_pair/reproduction`，历史脚本输出到各自实验目录。可用 `--runs 1` 检查入口。已使用的开发集及留出集不能在未来调参后再次宣称为独立验证。

Q3对照参数为 `--q3-ring-guard {off,aggressive,conservative}`、`--q3-probe-radius` 和 `--negative-observations`，默认aggressive、60、关闭。Q4对照参数保持：`--service-policy atomic` 使用radial原子定位，`--service-policy atomic --layout rings` 使用22站原子定位；Q4默认rings/adaptive。`--strategy paper --layout original/compact` 的历史对照能力保留。

历史研究记录见[论文定位研究](results/paper_localization/README.md)、[覆盖布局研究](results/coverage_optimization/README.md)及 `results/optimization`，用于追溯，不代表当前默认策略。

## 文件职责

| 文件 | 用途 |
|---|---|
| run.py | 统一入口、日志与参数检查 |
| joint_search.py | 问题四联合路线、选择性测量、小区域光学尝试 |
| omni_search.py / negative_observations.py | 从Fusion原样复制的Q3控制器及可选负观测依赖 |
| localization_service.py | 有限分步定位、Q3无信号区域约束与小区域光学尝试 |
| active_localization.py | 论文启发的有界误差主动定位 |
| solver.py | 通用动作、定位后备及对照策略 |
| geometry.py | 有界误差几何与连续覆盖构造 |
| coverage_geometry.py | 接收距离与凸包的连续区域覆盖检验 |
| backend.py / audit.py | 官方通信、本地模拟及逐步计时核查 |
| verify_target_experiments.py | 冻结源码的独立对照复现 |
| verify_q3_scheduling.py | 问题三冻结源码的独立对照复现 |
| verify_q4_coverage.py | 最新问题四覆盖候选的冻结复现 |
| verify_target_pair_experiments.py | 本轮Q3/Q4采用候选的冻结复现 |
| test_coverage_tight.py | 问题三八站布局的三条独立覆盖验证 |
| test_hex_coverage.py / test_history_support.py | 退役Q3的几何与冻结动作回归，仅测试使用 |
| test_q3_replacement.py | Fusion Q3动作一致性、原Q4源码与动作不变检查 |
| verify_scan_route_experiments.py | 使用冻结源码复现本轮Q3布局同场对照 |
| test_*.py | 几何、协议、覆盖及入口检查 |
