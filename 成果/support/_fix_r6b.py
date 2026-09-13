import json
from pathlib import Path

# ---------------- ledger ----------------
p = Path('OPTIMIZATION_LEDGER.md')
s = p.read_text(encoding='utf-8')

s = s.replace(
    "- **修订已真正实现并重测（r106）**：`max_defer_age=3` 现在被实际读取（`patched()` 里按公开延迟年龄判定，计数器可动）。\n  r106（3499700–3499723，24 场）：`q3_keep` 与 `q3_keep_m1` 结果一致（+1.42%，中位 0.00%，最坏 +16.46%，1 场 >5%），\n  `route_reuses=12.2/场`、`route_replan_new_task=3.4/场`、**overdue=0**、与对照逐位相同的场次 10/24。\n  即：目标在这些场景里从未等待 ≥3 个站点 → 退化不是“目标饿死”，而是**站点顺序陈旧**；修订未触发是可核验的事实（计数器可动而值为 0）。",
    "- **修订（第二次更正后为真实现，并已重测）**：`plan_reuse()` 现**读取** `max_defer_age`（纯函数，可单测），`patched()` 按公开延迟年龄传入；\n  新增 4 项单测（目标超龄→`overdue`、未超龄→`reused`、站点永不触发、新任务优先）与 1 项集成断言\n  （`max_defer_age=1` 时 `route_replan_overdue > 0`，证明计数器可达、非死代码）。\n  **r110（3500000–3500023，24 场，真实现）**：`q3_keep` +0.69%（3 场 >5%、最坏 +8.03%、复用 13.1/场）\n  vs `q3_keep_m1` **+0.64%**（2 场 >5%、最坏 +8.03%、复用 **6.4/场**、**overdue 触发 160 次**、与对照逐位相同 19/24）。\n  即修订确实生效（每场约 6.7 次超龄刷新，把"保序"减半、行为更接近基线），但**结论不变：两个版本都劣于强基线**；\n  此前 r106 声称"q3_keep == q3_keep_m1、overdue=0"是**未接线的死代码**造成的，该结论已作废。")

s = s.replace(
    "2. **独立结果与复杂度**：Q3 开发 24 场 +0.41%/+1.98%（更差，尾重）、压力类 −1.4%~−6.0%（更好）；",
    "2. **独立结果与复杂度**：Q3 开发 24 场 +0.41%/+1.98%/+1.42%（更差，尾重）、r110 真修订版 +0.64% vs +0.69%（仍更差）、压力五类均 0.00%（逐位相同）；")

s = s.rstrip() + '''

### 8.7 第二次更正（overdue 修订的真正接线）

审计指出 8.1 声称的"修订已真正实现"与代码不符：`route_keep_max_defer` 当时**只被赋值未被读取**，
`plan_reuse` 不可能返回 `'overdue'`，因此 `route_replan_overdue` 是死计数器，r106 的"q3_keep == q3_keep_m1、overdue=0"
是**未接线造成的假象**。本轮已按可单测的纯函数重做：

- `plan_reuse(saved_ids, current_ids, defer_age=None, max_defer_age=None)` 现在真正读取年龄上界，
  并在"计划本来可复用"时优先返回 `'overdue'`；`patched()` 用公开的 `self.deferred` 年龄构造 `defer_age`。
- 新增单测：目标超龄→`overdue`、未超龄→`reused`、站点永不触发、新任务优先于超龄；集成测试用 `max_defer_age=1`
  断言 `route_replan_overdue > 0`（**计数器可达**）。
- **重测 r110（3500000–3500023，24 场）**：`q3_keep` +0.69%（复用 13.1/场、3 场 >5%、最坏 +8.03%）；
  `q3_keep_m1` **+0.64%**（复用 6.4/场、**overdue 160 次**、2 场 >5%、最坏 +8.03%、19/24 与对照逐位相同）。
  修订生效且把行为推向基线，但**两版仍劣于强基线** → Q3 结论不变（不采用）。
- 作废清单（本文件内已更正）：r106 关于"修订未触发"的段落、8.3 第 2 项残留的"压力类 −1.4%~−6.0%（更好）"、
  `final_report.json` 中 `q3.verdict` 的"class-dependent"表述与 `corrections.voided` 里关于计数器的那一条。
'''
p.write_text(s, encoding='utf-8')

# ---------------- final_report.json ----------------
OUT = Path('research/iterative_speed/results/r104_final_report')
rep = json.loads((OUT / 'final_report.json').read_text(encoding='utf-8'))
rep['q3']['revision'] = ("max_defer_age=3 is now genuinely wired (pure plan_reuse reads it; unit tests cover the "
                         "overdue path and an integration test with max_defer_age=1 asserts route_replan_overdue>0). "
                         "r110 (24 fresh seeds): q3_keep +0.69% (reuses 13.1/scene, 3 scenes >5%, worst +8.03%) vs "
                         "q3_keep_m1 +0.64% (reuses 6.4/scene, overdue fired 160 times, 2 scenes >5%, worst +8.03%, "
                         "19/24 bit-identical to control). The revision fires and moves behaviour toward the "
                         "baseline, but both variants are still slower than the strong baseline. The earlier r106 "
                         "statement (q3_keep == q3_keep_m1, overdue=0) came from the un-wired dead counter and is void.")
rep['q3']['verdict'] = ("rejected for production: +0.41%/+0.69%/+1.42%/+1.98% across four independent 24-seed "
                        "batches with heavy tails (worst +8%~+18%), and 0.00% (bit-identical) in all five stress "
                        "classes; the overdue revision fires (160 times in 24 scenes) and slightly reduces the harm "
                        "but does not change the conclusion. This does not prove route keeping is globally bad - "
                        "only the strict keep-plan form tested here.")
rep['corrections'] = {
    'voided': ['Q3 stress row (-1.43/-2.95/-5.97 computed against the old off arm)',
               'r106 claim that the overdue revision was measured with a live counter (it was dead code; '
               'the wired version is r110)'],
    'authoritative_rounds': ['r102 (Q3 stress, vs skip12_probe60)', 'r110 (Q3 overdue revision, wired)',
                             'r109 (Q4 forced worst order)', 'r105 (Q4 smoke)'],
}
(OUT / 'final_report.json').write_text(json.dumps(rep, indent=2, ensure_ascii=False), encoding='utf-8')
print('ledger 8.1/8.3 corrected, 8.7 added, final_report.json updated')
