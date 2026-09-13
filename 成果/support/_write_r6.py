import json
from pathlib import Path

ROOT = Path('research/iterative_speed')
OUT = ROOT / 'results' / 'r104_final_report'
OUT.mkdir(parents=True, exist_ok=True)

payload = {
    'round': 'Q3 真正路线保持 + Q4 后备有限邻域（≤150 分钟）',
    'baseline': {
        'q3': 'integrated + --q3-ring-guard aggressive --q3-probe-radius 60 (arm skip12_probe60)',
        'q4': 'integrated/radial default (arm baseline)',
        'head': 'a78d520', 'tag': 'student-opt-v2 = 7e9e73a',
    },
    'q3': {
        'change': 'route_keep.py: stable ids (channel / (layout_generation, station_index)); '
                  'completion only removes its own task; re-plan only on a new task or (revision) target overdue',
        'guarantees_kept': 'only the visit order changes; coverage sites, certificates, 19.99 m rule, '
                           'final coverage obligation and the optical fallback are untouched',
        'invariants_tested': 10,
        'dev_24_seed_batches': {'r98': '+0.41% mean-of-ratios (median 0.00%, worst +10.05%, CVaRΔ +5.45%)',
                                'r99': '+1.98% (median +0.35%, worst +18.34%, CVaRΔ +15.59%)'},
        'mechanism_fired': 'route_reuses 11.8–12.3/scene (previously 0), re-plan only on new task (3.7/scene)',
        'revision': 'max_defer_age=3 (public deferred age): never fired (overdue=0) — targets were not starved',
        'stress_3_each': {'cluster': '-1.43%', 'cluster_wide': '0.00%', 'boundary': '0.00%',
                          'plus': '-2.95%', 'minus': '-5.97%', 'failures': 0},
        'worst_trace': {'seed': 3499211, 'delta': '+18.34%', 'coverage': '4996 vs 3946 m',
                        'localization': '3803 vs 3409 m', 'clear': '3690 vs 2636 m', 'reuses': 8},
        'typical_trace': {'seed': 3499218, 'delta': '+0.57%', 'coverage': '2339 vs 2447 m'},
        'complexity': 'wall 0.34 s/scene vs 0.34 s/scene (no measurable overhead)',
        'verdict': 'rejected for production; class-dependent (helps stress classes, hurts normal scenes with a '
                   'heavy tail). Does not prove route keeping is globally bad — the strict no-replan variant is '
                   'what was tested here.',
    },
    'q4': {
        'capture_fixed': 'collector attached to directional_fallback entry of the Q4 default strategy '
                         '(not an action-time counter diff, not the Q3 arm); validated by a constructed '
                         'forced-fallback state test',
        'incidence': {'scenes': 24, 'events': 17, 'scenes_with_event': 13, 'capture_success_rate': 1.0},
        'fallback_cost': {'sweep_s_total': 2172, 'scene_s_total': 152523, 'share_pct': 1.42,
                          'share_in_affected_scenes_pct': [2.1, 2.2, 4.5, 4.8, 4.9, 6.8],
                          'movement_m': 7373, 'attempts': 221, 'successes': 17,
                          'mean_scene_time_per_event_s': 127.7},
        'ceiling_statement': 'even if the whole fallback sweep became free, the mean gain is bounded by 1.42% of '
                             'scene time — below the 2% adoption gate; the gate is therefore unreachable by this '
                             'mechanism alone (this is a bound, not a claim about Q4 optimality)',
        'reorder': {'candidates_per_event_budget': 24, 'events': 16, 'orders_evaluated': 368,
                    'orders_adopted': 0, 'predicted_gain_s': 0.0,
                    'realised_delta': '0.000% (bit-identical to the unchanged default in dev and stress)'},
        'prediction_note': 'design-sample mean first-success cost over-estimates the single realised sweep by '
                           '~5x (783 s vs 140 s) because the design distribution averages over the feasible set; '
                           'only the relative ranking is used, and no neighbour beat the incumbent by the margin',
        'stress_3_each': {'cluster': '0.00% (7 events)', 'cluster_wide': '0.00%', 'boundary': '0.00% (8 events)',
                          'plus': '0.00% (9 events)', 'minus': '0.00% (7 events)', 'failures': 0},
        'complexity': '368 sweep-cost evaluations over 16 events in 24 scenes; wall time unchanged within noise',
        'verdict': 'stopped with evidence: bounded opportunity (1.42% ceiling) and 0/16 adopted orders; '
                   'the incumbent optical order is already optimal under the specified cost model in these states',
    },
    'final': {
        'adoption': 'none — keep student-opt-v2 as the production configuration',
        'freeze': 'no new candidate frozen for final testing',
        'production_unchanged': True, 'pushed': False, 'tests': '161 tests OK (140 previous + 10 route-keep + 11 fallback)',
    },
}
(OUT / 'final_report.json').write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding='utf-8')

section = '''

---

## 8. 第六轮（收尾）：Q3 真正路线保持 + Q4 后备有限邻域

合同：本轮用户给定（150 分钟）。基线：Q3 `aggressive+probe60`（`skip12_probe60`）、Q4 radial 默认；交接 `a78d520`，
`student-opt-v2` = `7e9e73a`。两方向独立实现、独立比较，未混合归因。生产默认、几何证书、19.99m 判据、
覆盖义务、有限后备与标签均未改动。

### 8.1 Q3 真正保留剩余任务路线（route_keep.py；未采用）

实现：任务身份改为**稳定 id**——目标用 `('t', channel)`，站点用 `('s', layout_generation, station_index)`；
完成任务只把自身从序列中移除、**保留其余任务相对顺序**；仅当出现**新任务**（id 不在已保存序列）或（修订版）
目标延迟超龄时才重排；目标区域与代表位置每轮用**最新公开观测**重算（保持顺序而非坐标）。
上轮 N3 的缺陷已证实并修正：旧键含"剩余任务集合"，任何完成都会换键 → `route_reuses=0`。

| 轮次（冻结种子） | 平均比 | 均值之比 | 中位 | >5% | >10% | 最坏（偏移） | p95Δ | CVaRΔ | 复用/场 | 失败 |
|---|---:|---:|---:|---:|---:|---|---:|---:|---:|---:|
| r98（3499100–3499123，24 场） | +0.41% | +0.43% | +0.00% | 1 | 1 | 3499103 (+10.05%) | +0.83% | +5.45% | 12.3 | 0 |
| r99（3499200–3499223，24 场，含修订臂） | +1.98% | +2.01% | +0.35% | 3 | 2 | 3499211 (+18.34%) | +11.95% | +15.59% | 11.8 | 0 |
| 压力（每类 3 场，r102） | cluster −1.43% / cluster_wide 0 / boundary 0 / +1° −2.95% / −1° −5.97% | | | | | | | | | 0 |

- **机制确实触发**：`route_reuses` 由 0 升到 11.8–12.3/场；重排仅发生在新任务（3.7/场）与初始规划；`plan_reversals=9`(r98)。
- **修订未生效**：`max_defer_age=3` 的 overdue 触发数为 0 → 目标并未被"饿死"，退化来自**站点顺序陈旧**而非目标延迟。
- **坏尾机制（轨迹证据）**：最坏场 3499211（+18.34%）覆盖转场 4996 vs 3946m（+1050m）、定位 3803 vs 3409m、
  清除接近 3690 vs 2636m —— 保留的计划把机器人送往更远的站点，三个移动相位同时上升；典型场 3499218（+0.57%）几乎持平。
- **类别依赖**：压力类（聚集/边界/±1°）反而更好（−1.4%~−6.0%，0 失败），普通场景变差且重尾 → 说明"陈旧计划"
  的代价与目标区域漂移/站点几何有关，本轮不据此再调参。
- 复杂度：wall 0.34s/场 vs 对照 0.34s/场，无可测开销。
- **判定：不接入生产**（均值门 <2% 且尾部恶化）。此结果**不证明**路线保持整体不可行——本轮只检验了"严格不重排"这一形态。

### 8.2 Q4 完整光学后备的有限邻域改良（fallback_neighborhood.py；有证据地停止）

**采集修正（关键）**：旧采集在 `action` 前后比较 fallback 计数（solver 在调用 action 之前已自增 → 漏记），
且挂在 Q3 臂上（Q4 方法永不执行）。现改为**挂 `directional_fallback` 入口**、记录第一步后备动作前的公开状态，
并用**构造的必然进入后备状态**做自检单测（`ForcedFallbackCaptureTests`，通过）。

| 指标 | 数值（24 场 Q4 开发种子 3499300–，对照=默认策略） |
|---|---|
| 后备事件 / 发生场次 / 捕获成功率 | 17 / 13 / **1.00** |
| 后备耗时 / 全场耗时 | 2172s / 152523s = **1.42%** |
| 有事件场次中的占比 | 2.1%–6.8%（6 个最大：6.8/4.9/4.8/4.5/2.2/2.1） |
| 后备移动 / 尝试 / 成功 | 7373m / 221 / 17（每次事件平均 127.7s） |
| 压力（每类 3 场）事件数 | cluster 7 / cluster_wide 0 / boundary 8 / +1° 9 / −1° 7，全部 0 失败 |

**上限结论**：即使后备清扫完全免费，平均收益上界也只有 **1.42%** 全场时间 → **2% 采用门在本机制下不可达**
（这是上界，不是"Q4 已最优"的证明）。

**有限邻域实现**：incumbent（既有 `open_route` 顺序）保留为候选；只加单点搬移与两节点交换，每次事件 ≤24 条候选；
费用=按设计分层样本逐假设位置累计"首次成功清除前的移动 + 光学尝试（失败 3s / 成功 5s）"+ 出口腿；
未命中的假设不予记功（该候选判不可用）；预登记裕度 max(3s, 0%)；粒子只用于排序。

| 结果 | 数值 |
|---|---|
| 评估候选顺序 / 采用 | 368 / **0**（16 次事件） |
| 与默认策略的整场配对差异 | **0.000%**（开发 24 场与压力 15 场均逐位相同） |
| 预测校准备注 | 设计样本均值 783s vs 实际单次清扫 140s（≈5×）：设计分布是对可行集的平均，不能当作单场景预测；只用相对排序 |

**判定：有证据地停止 Q4**（合同 §C）：机会上界 1.42% < 2% 门，且同状态仅顺序不同的对照中 0/16 被采用 →
既有顺序在该费用口径下已最优。不转向复杂粒子/深前瞻/漏检分支。

### 8.3 本轮结论与交付

1. **Q3/Q4 改了什么、原保证为何仍保留**：Q3 只改"任务顺序的保存/删除规则"（新增 `route_keep.py` 研究类），
   覆盖站集合、证书、19.99m 判据、最终覆盖义务与光学策略全部沿用；Q4 只改"后备清扫的访问顺序"
   （新增 `fallback_neighborhood.py` 研究类），进入时机、clear 规则、失败后的公开状态更新均未改。
2. **独立结果与复杂度**：Q3 开发 24 场 +0.41%/+1.98%（更差，尾重）、压力类 −1.4%~−6.0%（更好）；
   Q4 全部 0.000%（逐位相同）。复杂度：Q3 无可测开销；Q4 每次事件 ≤24 条候选、368 次评估/24 场，wall 无显著变化。
3. **收益来源/失败原因/坏尾**：Q3 的坏尾来自"保留陈旧计划 → 覆盖转场 +1050m"；Q4 无收益来源（0 采用），
   其"机会上限"只有 1.42%。
4. **保留/放弃/冻结**：两项都**放弃**；不冻结任何新候选；生产保持 `student-opt-v2`（Q3 `aggressive+probe60`，Q4 默认）。
5. **复现命令**：
   `cd 成果/support/research/iterative_speed && "$PY" study.py --problem 3 --variants baseline skip12_probe60 q3_keep --control skip12_probe60 --start 3499200 --count 24 --workers 8 --round <name> --hypothesis "<text>"`；
   Q4：`--problem 4 --variants baseline q4_fb_probe q4_fb_reorder --control baseline`；
   单测：`"$PY" -m unittest test_route_keep test_fallback_neighborhood`（21 项）。
6. **论文可用方法与实验说明**：本轮的 Q4 部分给出一个"修正采集 + 上限估计 + 同状态仅顺序对照"的三段式验证范式：
   先用构造状态自检采集器保证事件不漏记，再用"消除该阶段全部费用"给出机制收益上界以判断是否值得继续，
   最后用同状态仅单变量对照（两臂除访问顺序外完全一致、之后恢复同一基策略）检验局部预测是否真的兑现——
   该范式把"预测改善"与"实际改善"分开报告，避免把设计样本的平均当作概率保证或全局最优证据。

### 8.4 产物

- 源码：`research/iterative_speed/route_keep.py`、`research/iterative_speed/fallback_neighborhood.py`；
  测试：`test_route_keep.py`（10 项）、`test_fallback_neighborhood.py`（11 项）；轮内产物：
  `results/r97/r98/r99/r102/r102b/r103/r103b/r100/r101/r104_final_report/final_report.json`。
- 单测总计 **161 项通过**（140 + 10 + 11）；生产默认、发布标签、研究外代码未改；未推送。
'''
p = Path('成果/support/OPTIMIZATION_LEDGER.md')
p.write_text(p.read_text(encoding='utf-8').rstrip() + section, encoding='utf-8')
print('ledger §8 + final_report.json written')
