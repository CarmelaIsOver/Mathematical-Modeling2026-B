# 数学建模 B 题

当前维护入口为 `成果/support/run.py`。Q3采用Fusion推荐的 `aggressive + probe60` 原子定位方案；Q4保留 `rings + adaptive`。运行参数、策略对照及验证依据见[运行说明](成果/support/README.md)。

## 目录

| 路径 | 用途 |
| --- | --- |
| `B题/` | 题目与附件 |
| `成果/support/` | 当前代码、测试与实验复现脚本 |
| `成果/support/results/` | 验证报告、实验结果及测试依赖的冻结源码，需随代码提交 |
| `成果/` 下的论文与评估文档 | 历史阶段材料，当前优化未同步修改论文；策略以运行说明和代码为准 |

模拟器、Fusion完整参考目录、`tmp/`、Python缓存、客户端原始运行日志和平台导出的JLOG仅保留在本机，由 `.gitignore` 排除。采用的Fusion Q3及其依赖已在 `成果/support/` 中，不依赖参考目录运行。原始演练记录需自行备份，Git不会保存后续日志。

## 本地检查

在仓库根目录打开PowerShell，使用已安装NumPy的Python环境：

```powershell
Set-Location .\成果\support
python -m pip install -r requirements.txt
python -m unittest discover -p "test_*.py" -v
```

`results/` 中部分JSON是测试与历史复现必需的源码快照，不应作为缓存删除或统一忽略。测试不要求安装或启动官方平台。

## 人工演练

在平台选择并启动相应场次，接口就绪后，在 `成果/support/` 运行对应命令：

```powershell
$teamId = Read-Host "请输入当前平台队号"
python run.py --mode official --problem 3 --robot-id $teamId --output practice_logs
# 另开问题四场次后运行：
python run.py --mode official --problem 4 --robot-id $teamId --output practice_logs
```

每场核对 `complete`、`normal_exit` 及清除数量，使用虚拟时间计算秒/源，并另行导出平台日志。
