# 按用户要求替换Q3，保留现有Q4

目标目录为 `成果/support`。将Q3替换为 `Mathematical-Modeling2026-B-codex-q3-q4-v3-fusion/成果/support` 的实现，并在统一入口默认启用其最终推荐配置：`ring_guard=aggressive`、`probe_radius=60`、负观测关闭、原子定位。不是Fusion不加参数时关闭缩环和试探的基线。

## 修改范围

- `omni_search.py`、`negative_observations.py` 从Fusion原样复制，文件SHA256与来源一致。
- `run.py` 仅适配Q3的选择、参数默认值和日志字段；Q4控制器选择、布局、服务参数和执行流程保留。
- 同步Q3相关测试与README。旧Q3实验通过原有冻结源码保留为历史验证，不在生产入口并行维护旧Q3控制器。
- 未修改Fusion来源目录算法、论文、PDF或ZIP，未开启官方演练/正式会话。

## Q4不变的验证

替换前记录并在替换后逐文件核对以下8个文件SHA256：

`joint_search.py`、`localization_service.py`、`solver.py`、`active_localization.py`、`geometry.py`、`coverage_geometry.py`、`backend.py`、`audit.py`。

以上文件全部不变。另保存种子4800000–4800011的12场原Q4完整动作序列SHA256；替换后逐场动作、虚拟耗时、清除数量相同。对统一入口也用两场模拟官方HTTP后端验证，仍选择rings/adaptive，动作摘要与替换前一致。未把Fusion的Q4代码或通信模块复制进来。

## Q3一致性验证

从Fusion推荐配置预先采集同一12个种子的完整动作摘要，含4场接收半径1000米、源在边界且原点无信号的场景。替换后与这些参考动作逐条一致、全部清除、正常退出。统一入口两场也与Fusion参考一致，分别覆盖缩环激活和未激活情况。

全量86项单元测试通过。历史hex测试使用替换前的冻结控制器源码；Fusion相关测试验证默认构造关闭研究开关、入口推荐配置、条件缩环和试探失败后的完整处理。替换过程首轮发现两项历史测试误用了尚不支持hex的早期快照，已改用实际替换前快照后全量通过；未为通过测试改动Q4或Fusion运行逻辑。

## 运行方式

仍在 `C:\Users\Carmela\Desktop\b\成果\support` 使用原命令：

```powershell
$teamId = Read-Host "请输入当前登录平台的参赛队号"
python run.py --mode official --problem 3 --robot-id $teamId --output practice_logs
python run.py --mode official --problem 4 --robot-id $teamId --output practice_logs
```

每次先在平台启动对应问题的演练，再执行对应的一条命令。

Q3启动行：`strategy=integrated, layout=original, service_policy=atomic, ring_guard=aggressive, probe_radius=60`。original表示初始布局，实际是否改用1123米环看结果字段`ring_activated`。不要为Q3再加旧的`--layout hex/tight`或`--service-policy adaptive`。

Q4仍为`strategy=integrated, layout=rings, service_policy=adaptive`，命令和行为不变。

本次是遵照用户选择替换策略，不宣称进一步提速；之前同场200场的247.33与247.38已显示两套Q3总体平均接近。新入口还需要用户实际演练验证。

证据：`before.json`保存Fusion来源摘要、原Q4依赖摘要及24条参考动作摘要；`test_q3_replacement.py`执行逐文件、逐场和入口一致性检查。
