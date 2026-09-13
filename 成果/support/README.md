# 最终程序运行与复核

当前生产入口为 `run.py`。Q3采用Fusion推荐配置，Q4保留此前方案。论文方法和实际成绩见[论文准备材料](../论文准备/README.md)；旧运行说明存入[历史记录](HISTORY.md)，不能把其中的阶段性默认值用于当前运行。

## 固定配置

| 参数 | Q3 | Q4 |
| --- | --- | --- |
| strategy | integrated | integrated |
| layout | original起始，按原点接收条件切换1123米环 | rings（22站） |
| service_policy | atomic | adaptive |
| ring_guard / probe_radius | aggressive / 60米 | 不适用；Q4中心试探上限40米 |
| negative_observations | 关闭 | 不使用Q3距离排除 |

不要给Q3增加旧的 `--layout hex/tight` 或 `--service-policy adaptive`。Q3构造器的默认研究开关与 `run.py` 最终入口默认值不同，日常运行统一使用入口。

## 官方平台运行

在本目录打开PowerShell，先在平台启动对应场次并等待接口就绪，再分别执行相应命令：

```powershell
$teamId = Read-Host "请输入当前平台队号"
python run.py --mode official --problem 3 --robot-id $teamId --output practice_logs
# 另开问题四场次后执行：
python run.py --mode official --problem 4 --robot-id $teamId --output practice_logs
```

`official`表示使用官方HTTP接口，不自动选择演练/正式模块，也不会启动平台场次。每个新场次只运行对应命令一次。默认接口为 `http://127.0.0.1:2026`，端口改变时使用 `--url`。是否仍可开始新测试以平台状态为准。

保存终端结果、JSON/JSONL和平台导出的原名JLOG；核对 `complete`、`normal_exit`、清除数与平台总数。`ring_activated=1`表示Q3实际缩环，0表示保留大环。`failed_clear`包括未命中的光学尝试，不等同于程序异常，但其时间必须计入结果。

## 本地检查

生产依赖为NumPy，Python 3.12已验证：

```powershell
python -m pip install -r requirements.txt
python -m unittest discover -p "test_*.py" -v
```

本地单场运行示例：

```powershell
python run.py --mode offline --problem 3 --runs 1 --seed 4800000 --output practice_logs/local_check
python run.py --mode offline --problem 4 --runs 1 --seed 4800000 --output practice_logs/local_check
```

此类结果为合成场景，不能写作官方成绩。不要用 `results/`默认输出覆盖已有论文证据；示例明确指定个人检查目录。

## 保留的证据与历史复现

- `test_q3_replacement.py`核对Fusion Q3来源源码、Q4依赖源码和24条参考动作序列。
- `test_coverage_rings.py`独立复核Q4连续覆盖证书。
- 其他测试覆盖几何、计时、后备、频道状态和历史策略兼容。
- `results/validation/fusion_q3/`保存最终Q3相关的配对结果和来源快照；`results/target_pair/`保存Q4分步策略对照；当前四场演练整理于`../论文准备/数据/`。
- `verify_*.py`在临时目录解包冻结源码，复现相应历史实验；不会依赖已清除的仓库`tmp/`。历史实验不是当前生产控制器的并行版本。

`question2.py`、`experiments.py`及问题一几何仍保留，以便完整论文使用；本次仅梳理Q3/Q4，Q1/Q2最终文字需另行核对。当前未生成最终论文PDF或支撑材料ZIP。
