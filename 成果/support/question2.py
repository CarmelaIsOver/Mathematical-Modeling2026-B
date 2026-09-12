"""Q2: safe candidate lens and discrete minimax linearized precision score.

Normalized first observation S=(0,0), measured bearing=0 degrees.
Transform candidates by rotation/translation for any actual observation.
"""
import csv
import json
import math
from pathlib import Path
import numpy as np
from geometry import unit,EPS_DEG,region_from_bearings,enclosing_circle

def main():
    out=Path('results');out.mkdir(exist_ok=True)
    centers=np.array([[0.,0.],1000*unit(-EPS_DEG),1000*unit(EPS_DEG)])
    sources=np.array([r*unit(a) for r in np.linspace(5,1500,151)
                     for a in np.linspace(-EPS_DEG,EPS_DEG,9)])
    r1=np.linalg.norm(sources,axis=1)
    rows=[]
    for a in range(25,1001,25):
        for b in range(25,1001,25):
            q=np.array([a,b])
            if np.max(np.linalg.norm(centers-q,axis=1))>1000-1e-6:
                continue
            d=sources-q
            r2=np.linalg.norm(d,axis=1)
            sin=np.abs(sources[:,0]*d[:,1]-sources[:,1]*d[:,0])/(r1*r2)
            # sigma=1 degree/sqrt(3) is a comparative assumption, not a fact.
            score=float(np.max(np.sqrt(r1*r1+r2*r2)/np.maximum(sin,1e-12)))
            rows.append(dict(a_m=a,b_m=b,score_per_radian=score))
    rows.sort(key=lambda x:x['score_per_radian'])
    with (out/'question2_candidates.csv').open('w',newline='',encoding='utf-8-sig') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    q1=region_from_bearings([([0,0],45),([1000,0],135)])
    c,r=enclosing_circle(q1['vertices'])
    summary={'q2_discrete_best':rows[0],'q2_candidates_upper_half':len(rows),
             'q2_uniform_noise_assumption_rms_m':rows[0]['score_per_radian']*math.radians(1)/math.sqrt(3),
             'q1_example':{'diameter':q1['diameter'],'circle_center':c.tolist(),'circle_radius':r,'vertices':q1['vertices'].tolist()}}
    (out/'geometry_summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    print(json.dumps(summary,indent=2))

if __name__=='__main__':
    main()
