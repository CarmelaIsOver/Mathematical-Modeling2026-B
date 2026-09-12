"""Rebuild the experiment ledger from saved paired results, without rerunning solvers."""
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parent


def main():
    folders=sorted(p for p in (ROOT/'results').iterdir() if (p/'summary.json').exists())
    runs=0;failures=0
    lines=['# 策略迭代实验结果','',
      '基线：951df1b。所有数据为 LOCAL_SYNTHETIC，不是官方成绩。每轮协议、源码快照、逐局指标保存在 results 对应目录。',
      '以每局总时间/真实目标数计算每目标时间，再对场景等权平均；真实目标数只用于实验评价。失败按 360000 秒/局计分。',
      '开发集24个种子；冻结后 Q3、Q4 各48个独立种子；压力集每类6个。小样本 P99/CVaR 仅供筛选，不能证明低失败概率。','',
      '## 独立留出结果','',
      '|问题/策略|平均总秒/局|秒/目标|平均移动m|测量/局|P95|P99|CVaR95|最大秒/目标|最坏配对比|失败|实际秒/局|',
      '|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    for problem in (3,4):
        data=json.loads((ROOT/f'results/r4_q{problem}_holdout/summary.json').read_text())
        for name,d in data.items():
            keys=['virtual_time_s','mean','move_m','measure','p95','p99','cvar95','worst','worst_ratio','failures','wall_s']
            lines.append('|Q'+str(problem)+' '+name+'|'+'|'.join(f'{d[k]:.3f}' for k in keys)+'|')
    lines+=['','## 每轮记录','',
      '|实验|方向|样本|均值收益|最坏配对比|失败|',
      '|---|---|---:|---:|---:|---:|']
    for folder in folders:
        data=json.loads((folder/'summary.json').read_text())
        for name,d in data.items():
            runs+=d['n'];failures+=d['failures']
            if name!='baseline':
                lines.append(f"|{folder.name}|{name}|{d['n']}|{100*d['gain']:.3f}%|{d['worst_ratio']:.4f}|{d['failures']}|")
    lines+=['',f'累计 {runs} 次模拟运行（包括重复基线/开发样本），失败 {failures} 次；这不是同等数量的独立场景。','',
      '## 结论和收益来源','',
      '- Q3 guard1123 是本轮最有价值的候选：独立留出均值下降13.47%，48/48场景更快。中心站有真实正观测时才启用1123m七点环；没有则保持原布局。规则只在初始扫描允许切换，避免后续换布局损坏覆盖。',
      '- Q3 平均覆盖移动减少1747.89m、定位移动减少1391.70m，清除接近移动增加739.09m；净减少2400.49m（480.10秒），解释了每局485.93秒收益的绝大部分。测量仅减少1.02次/局。',
      '- Q3 边界源、窄接收半径聚集源压力组保持基线；宽接收半径聚集源快21%～24%。但最小半径正误差压力组存在最坏1.0581倍，未通过所有场景退化≤5%的门槛。因此保留可运行实验开关，不自动替换生产默认值。',
      '- Q4 22点布局独立留出只快2.22%，最坏1.2224倍；初始布局选择在普通组选择相同布局，没有解决坏尾部。压力组还出现1.2627倍。拒绝默认采用。',
      '- Q4 固定局部短步只在开发集快约0.5%～1.2%；组合22点后坏尾部加剧。发现结束后重调度、历史正观测凸组合候选、定位中途光学试探收益接近零或为负，停止投入。',
      '- Q3 负观测与缩环组合没有有意义的额外收益；不混合。1300m保护缩环留出快9.39%，弱于1123m。',
      '', '## 正确性边界','',
      'Q3中心覆盖半径1000m以内。外圈对r∈[1000,1800]，最坏距离平方为r²+ρ²−2rρcos30°，它关于r凸，只需验证两端。1123m和1300m都满足≤1000²。选择完整布局不依赖未知真值。',
      '几何可行域、19.99m清除认证、完整后备保持原实现。Q4仅选择已有完整布局；布局切换保留已访问原点索引，并重建其余待访问索引。完备性沿用基线假设，不代表任意场景都更快。',
      '五项回归检查通过：禁用选项时动作轨迹一致、七点覆盖端点验证、无中心信号时轨迹一致、Q4替换布局后无重复/遗漏站点、仅发现阶段结束后重调度。',
      '', '## 运行与复核','',
      '实验独立放在本目录，生产模块未修改。可用 study.py 的 --variants baseline guard1123（Q3）或 baseline choose_layout（Q4）运行；--round 必须是新目录名以防覆盖。',
      '例：python study.py --problem 3 --variants baseline guard1123 --start 4000000 --count 12 --workers 4 --round next_q3 --hypothesis "fresh guard check" --traces',
      'variants.py 定义全部候选；study.py 执行配对实验；test_policies.py 验证策略不变量；report.py 只汇总已有结果。',
      '这轮没有引入不完备极速策略，也没有根据少量零失败场景声称达到0.5%的失败率目标。']
    (ROOT/'RESULTS.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(f'{runs} runs, {failures} failures; report written')


if __name__=='__main__':main()
