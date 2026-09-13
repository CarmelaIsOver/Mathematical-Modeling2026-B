import json
from pathlib import Path

ledger = Path('OPTIMIZATION_LEDGER.md')
section = '''

---

## 9. 第七轮（队友新版融合）：66faa29 最小移植与 Q4 2×2 消融

分支 `codex/q3-q4-v3-fusion`（从本地 `1820f63` 创建）；对照来源 `origin/main = 66faa29`（其后无新提交）。
详细报告见 `成果/support/FUSION_REPORT_20260913.md`；全量测试与源码哈希见
`research/iterative_speed/results/r121_fusion_final/`。

**最终采用：Q3 与 Q4 均继续 v2**（Q3 `aggressive+probe60`；Q4 默认 radial+atomic+probe40）。
本轮无候选通过发布门槛 → **不创建 `student-opt-v3` 标签、不修改默认参数**（新增开关默认关闭/atomic）。
用户指示本轮不做远端推送；`origin` 未改动（`main` 仍为 `66faa29`），本地分支保留可直接 review。

### 9.1 移植范围

| 类别 | 内容 |
|---|---|
| 保留（本地） | 7 站受保护缩环+probe60、16 源发现关闭、radial 布局、证书/义务/有限后备、原子定位+probe40、全部历史结论 |
| 吸收（队友，均 opt-in） | `localization_service.py`（有限分步服务，仅 Q4）、`--q4-service-policy {atomic,adaptive}`（默认 atomic）、`outside_disk_hull`（仅作 Q3 研究候选 `neg_hull`） |
| 未吸收 | 队友 Q3 `tight` 八站布局、Q3 adaptive 分步定位、整体默认参数 |
| 默认路径不变 | `service_policy='atomic'` 与原 v2 轨迹逐位一致（trace 对拍）；`run.py` 入口与研究臂同种子逐位一致（atomic 438.122/306、adaptive 437.873/307） |

### 9.2 Q4 2×2 消融（A radial+atomic；B radial+adaptive；C rings+atomic；D rings+adaptive；均保留 16 源关闭）

24 冻结 seed（3501000–，基线 463.73 秒/源）：B −0.98%（最坏比 1.2484）、C −0.97%（1.1384）、**D −4.16%（1.0505）**。
64 全新 seed（3502000–，基线 501.41）：B −2.37%（1.1150）、C −0.68%（1.4699）、**D −5.34%（1.5082）**，D 的绝对 P95 619.2 / CVaR95 634.3 / 最差 651.9 均优于基线（654.8/677.9/697.6）。
分层：D 在非 16 源 **−6.06%**，16 源 −0.31% 且最坏 **+50.82%**。
压力（每类 3 场）：cluster 下 C/D 大幅领先（−23.7%~−44.4%）；cluster_wide C −23.7%；**boundary/切向所有融合臂 +36%~+68%**；plus/minus 以 D 最好（−7.6%/−12.6%）。
机制：16 源 × rings 的尾部来自**站点数**（rings 19–22 站 vs 基线 8 站，覆盖转场 19005 vs 2563m）与早期的目标间穿梭（服务 22 次访问/场、8.4 次无清除返回）；boundary/切向类是布局/服务改变了定位接近路径后失去基线优势。
一次修订 `service_rev1.py`（无进展即就地完成 + 有进展返回≤2，公开信息）：已实测触发（最坏场 inplace=4），但该场仍 +50.9% → **不能修复 rings 极端尾部**。
判定：D 均值最好但最差配对比 1.51 ≫ 1.05，且已知困难类一致灾难退化 → 未达主发布门槛，仅保留研究开关；B 为尾部最稳的融合臂（最坏 1.1150）。

### 9.3 Q3 负观测外包（`neg_hull`，仅吸收该机制）

与本地 A4 的差别：A4 用"收到/未收到"对的**中垂线半平面**（需同频道先有正接收，仅用于规划）；队友 `outside_disk_hull` 用**接收半径下界**（no_signal ⟹ 距离>1000m）构造凸外包（可进入认证区域）。
包含性论证＋8 项测试（`test_neg_hull.py` 6 项 + 队友外包直接测试 2 项）：随机可行点不被移除、边圆相切、极窄/退化多边形、
全内圆矛盾（RuntimeError→保留上次区域并计数）、全外恒等、连续两次排除仍保守。
24 场配对：**+0.00%（逐位相同）**；每场 64.7 次负观测、19.5 次区域更新、0 矛盾 → 机制**安全但零效果**，保留研究候选，不接入默认。

### 9.4 测试与复现

- 全量 `unittest discover -p "test_*.py"` → **185 项通过（7 项按范围 skip**：队友 Q3 `tight`/adaptive 用例，已注明原因）。
- 复现：`run.py --problem 4 --q4-service-policy adaptive`（研究开关）；研究臂 `fusA–fusE`、`neg_hull`
  （命令见 `FUSION_REPORT_20260913.md` 第 4 节）。
- 若日后需要推送该分支：`git push origin codex/q3-q4-v3-fusion`（本轮按用户指示未执行；`origin` 未改动）。
'''
ledger.write_text(ledger.read_text(encoding='utf-8').rstrip() + section, encoding='utf-8')

# also record the no-push decision in the fusion report
rep = Path('成果/support/FUSION_REPORT_20260913.md')
t = rep.read_text(encoding='utf-8')
t = t.replace('**结论：本轮无算法增量通过发布门槛 → Q3 与 Q4 均继续采用 v2 配置；不创建 `student-opt-v3` 标签。** 队友机制的移植与研究开关已提交，供 review。',
              '**结论：本轮无算法增量通过发布门槛 → Q3 与 Q4 均继续采用 v2 配置；不创建 `student-opt-v3` 标签。** 队友机制的移植与研究开关已提交，供 review。\n\n> 推送说明：按用户指示本轮**不做远端推送**（此前一次推送尝试因缺少凭据被终止，未对远端产生任何改动；`origin/main` 仍为 `66faa29`）。需要时执行 `git push origin codex/q3-q4-v3-fusion`。')
rep.write_text(t, encoding='utf-8')
print('ledger section 9 + fusion report note written')
