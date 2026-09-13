# 队友新版融合实验报告（2026-09-13）

分支：`codex/q3-q4-v3-fusion`（从本地 `1820f63` 创建）
对照来源：`origin/main` = **66faa29**（feat：q3在12源289，q4在13源445；其后无新提交）
本地基线：`student-opt-v2` 配置 —— Q3 `run.py --problem 3 --q3-ring-guard aggressive --q3-probe-radius 60`；Q4 默认（radial + atomic locate + probe40）

**结论：本轮无算法增量通过发布门槛 → Q3 与 Q4 均继续采用 v2 配置；不创建 `student-opt-v3` 标签。** 队友机制的移植与研究开关已提交，供 review。

## 1. 拉取与移植范围

| 类别 | 内容 |
|---|---|
| 拉取 | `git fetch origin`；`66faa29` 已在 `origin/main` 且为其尖端 |
| 保留（本地） | 7 站受保护缩环 + probe60、16 源发现关闭、radial 布局、证书/义务/有限后备、本地原子定位与 probe40、全部历史实验与否决结论 |
| 吸收（队友） | `localization_service.py`（有限分步服务，仅 Q4 接入）、`run.py --q4-service-policy {atomic,adaptive}`（默认 atomic）、`outside_disk_hull` 负观测外包（仅作 Q3 研究候选） |
| 移植方式 | 新文件原样复制并加 provenance 头；solver 侧只加 opt-in 参数（`service_policy`、`service_class`），默认路径逐位不变（已用 trace 对拍验证） |
| 未吸收 | 队友的 Q3 `tight` 八站布局、Q3 adaptive 分步定位、整体默认参数与 README 声明 |
| 排除项 | 未提交 `__pycache__`/`.pyc`、缓存、密钥或无关大文件 |

## 2. Q4：2×2 消融（布局 × 定位服务）

四臂共享同批冻结种子并保留本地 16 源发现关闭：A = radial+atomic（强基线）；B = radial+adaptive；C = rings(22)+atomic；D = rings+adaptive。

### 2.1 24 个冻结开发 seed（3501000–3501023，基线 463.73 秒/源）

| 臂 | 均值比 | 均值之比 | 中位 | >5% | >10% | 最坏配对比 | P95Δ(比值) | CVaRΔ(比值) | 失败 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| B radial+adaptive | −0.98% | −1.59% | −1.32% | 2 | 2 | 1.2484 | +13.29% | +20.10% | 0 |
| C rings+atomic | −0.97% | −1.67% | −1.82% | 3 | 2 | 1.1384 | +10.07% | +12.35% | 0 |
| **D rings+adaptive** | **−4.16%** | **−4.53%** | −3.78% | 1 | 0 | 1.0505 | +3.75% | +4.66% | 0 |

机制触发：B/D 每场约 22 次服务访问、8.4–8.6 次未清除返回、2.5–3.0 次重新选中；D 的 measure 256.8 vs 基线 282.5（−25.7 次），移动 21715 vs 22320 m。

### 2.2 64 个全新 seed 复筛（3502000–3502063，基线 501.41 秒/源）

| 臂 | 均值比 | 均值之比 | 中位 | >5% | >10% | 最坏配对比 | P95Δ(比值) | 绝对P95 | 绝对CVaR95 | 绝对最差 | 失败 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| B radial+adaptive | −2.37% | −2.32% | −1.76% | 2 | 1 | 1.1150 | +2.05% | 654.9 | 663.6 | 680.6 | 0 |
| C rings+atomic | −0.68% | −1.36% | −1.45% | 9 | 3 | 1.4699 | +8.42% | 658.9 | 668.1 | 676.9 | 0 |
| **D rings+adaptive** | **−5.34%** | **−5.83%** | −5.41% | 1 | 1 | **1.5082** | +1.16% | **619.2** | **634.3** | **651.9** | 0 |

分层（D，按源数）：10–12 源 −5.46%（最坏 +1.27%）、13–14 源 −7.78%（最坏 +2.42%）、**15–16 源 −2.87%（最坏 +50.82%）**。
非 16 源场景 D 均值 **−6.06%**；16 源场景 C +7.28%、D −0.31%。

### 2.3 压力与已知退化场景（每类 3 场，均值/最差）

| 类 | B | C | D |
|---|---:|---:|---:|
| cluster | −2.20% / −0.70% | **−42.65%** / −38.96% | **−44.36%** / −39.97% |
| cluster_wide | +4.35% / +5.94% | −23.73% / −13.13% | −18.91% / −1.36% |
| boundary | +5.08% / **+54.06%** | −4.09% / **+68.55%** | −8.64% / **+65.21%** |
| plus（全定向 +1°） | +0.98% / +9.32% | −5.98% / +3.19% | −7.57% / +4.48% |
| minus | −0.68% / +0.24% | +0.13% / +5.62% | −12.62% / +4.61% |
| 队友切向 3400001–3（boundary） | **+36.0%/+35.5%/+39.2%** | +47.9%/+48.2%/+47.4% | +37.1%/+43.2%/+48.8% |

### 2.4 坏尾机制（已解释）与一次修订

- **16 源 × rings**（seed 3502044，+50.8%）：基线只用 8 个站（发现闭合早）并以原子定位就地完成（定位移动 10567 m、覆盖转场 2563 m）；rings 臂访问 19–22 站且分步服务在已知目标间反复穿梭（覆盖转场 19005 m、定位移动 0）。→ 尾部来自**布局的站点数与早期穿梭**，不是测量次数。
- **boundary/切向**：所有融合臂一致 +36%~+68%，机制是边界切向目标的定位接近路径被布局/服务改变后失去基线优势；该类**无法通过本轮一次修订修复**。
- **修订 r1**（`service_rev1.py`，公开信息限定）：无进展访问即就地完成 + 有进展返回次数上限 2。已实测触发（最坏场 inplace=4），但该场仍 +50.9% → 修订不能修复 rings 的极端尾部（D+rev1 与 D 在该场等效）。

## 3. Q3：负观测外包（仅吸收该机制）

- 机制差异：本地 A4（`--negative-observations`）用"收到/未收到"对的**中垂线半平面**且只用于规划；队友 `outside_disk_hull` 用**接收半径下界**（no_signal ⟹ 距离 > 1000 m）构造凸外包，可用于认证区域。
- 包含性论证（写入 `neg_hull.py`）：① 半径 ≥1000 m ⇒ 排除 999.999 m 圆盘不丢可行点；② 余集的极点只可能是圆外顶点或边–圆交点，均已收集 ⇒ hull 包含真集；③ 与超集的半平面求交仍是超集，认证保持可靠；④ 顺序施加逐步放大 hull，仍保守。
- 测试：`test_neg_hull.py` 6 项（随机可行点不被移除、相切、极窄/退化、全内圆矛盾、全外恒等、连续两次排除仍保守）+ 队友外包直接测试 2 项。
- 24 场配对（3501000–3501023，对照 = 本地强基线）：**+0.00%（逐位相同）**；每场记录 64.7 次负观测、19.5 次区域更新、**0 次矛盾**，移动/测量完全不变。
- 判定：机制**安全但零效果** → 保留为研究候选（`neg_hull` 臂），不接入默认。

## 4. 最终采用

| 题 | 采用配置 | 理由 |
|---|---|---|
| Q3 | **继续 v2**：`--q3-ring-guard aggressive --q3-probe-radius 60` | 负观测外包 24 场零效果；无其他 Q3 变更 |
| Q4 | **继续 v2**：默认（radial + atomic + probe40） | 融合臂均值最好的是 D（−5.34%），但最差配对比 1.5082 ≫ 1.05、boundary/切向一致 +36%~+68% → 未达主发布门槛，仅保留研究开关 |

回退/研究命令：

```bash
# 生产（不变）
python run.py --mode official --problem 3 --robot-id <队号> --q3-ring-guard aggressive --q3-probe-radius 60 --output practice_logs
python run.py --mode official --problem 4 --robot-id <队号> --output practice_logs

# 研究开关：Q4 分步服务（默认 atomic 与 v2 逐位一致）
python run.py --problem 4 --seed 3502000 --q4-service-policy adaptive --output /tmp/fusion_demo

# 研究臂（含布局消融）
cd 成果/support/research/iterative_speed
"$PY" study.py --problem 4 --variants baseline fusB_radial_adaptive fusC_rings_atomic fusD_rings_adaptive \
  --control baseline --start <seed> --count 24 --workers 8 --round <name> --hypothesis "<text>"
"$PY" study.py --problem 3 --variants baseline skip12_probe60 neg_hull --control skip12_probe60 ...
```

## 5. 测试、入口一致性与哈希

- 全量测试：`python -m unittest discover -p "test_*.py"` → 见 `research/iterative_speed/results/r121_fusion_final/final_tests.log`（7 项队友用例按范围 skip 并注明原因）。
- 入口一致性（同种子 3502000，`run.py` vs 研究臂）：atomic 438.122 秒/源 / 306 次测量，adaptive 437.873 / 307，两两**逐位相同**；默认 atomic 与 v2 轨迹逐位一致（trace 对拍）。
- 源码哈希：见 `research/iterative_speed/results/r121_fusion_final/source_hashes.json`。

## 6. 限制

- 全部为 `LOCAL_SYNTHETIC` 离线模拟；队友的 200 场与官方成绩不由本报告背书。
- 本报告的 rings 臂 = 本地 22 站 rings（1+7+14，与队友 rings 同源 `search_stations`）；队友 `tight` 八站布局未移植，故 Q3 不构成对其路线评估。
- 压力类（boundary/切向）为本轮合成样本，用于机制诊断；其最坏值不代表总体分布。
- 未达门版本只作为研究开关保留，**不得**当作最佳版本对外表述。

> 推送说明：按用户指示本轮**不做远端推送**（此前一次推送尝试因缺少凭据被终止，未对远端产生任何改动；`origin/main` 仍为 `66faa29`）。需要时执行 `git push origin codex/q3-q4-v3-fusion`。
