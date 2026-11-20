"""Bounded, repeatable validation; saves results outside the campaign/master catalogs.

python WingStudy/check_spanwise_elastic.py [--animation]
"""
import argparse
import copy
import json
from pathlib import Path
import numpy as np
import elastic
import elastic_runner as R


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--animation',action='store_true')
    args=ap.parse_args()
    out=R.ROOT/'outputs'/'elastic'/'span_validation'
    out.mkdir(parents=True,exist_ok=True)
    case,settings=R.load_catalog_case(7657)
    rod=elastic.Rod(diameter_m=.005,hollow_inner_diameter_m=.003)
    tests=[('rigid',case,None,.01),
           ('stiff_limit',case,elastic.ElasticConfig(spanwise_bending=True,material=elastic.Material(youngs_modulus_pa=5e15,shear_modulus_pa=4.5e14)),.01)]
    for fac in (.35,.7):
        tests.append((f'rod_factor_{fac}',case,elastic.ElasticConfig(spanwise_bending=True,rod=rod,added_mass_factor=fac),.01))
    tests.append(('rod_dt_half',case,elastic.ElasticConfig(spanwise_bending=True,rod=rod),.005))
    tests.append(('bare_1mm',case,elastic.ElasticConfig(spanwise_bending=True,thickness_m=.001),.01))
    for dt in (.01,.005):
        tests.append((f'bare_0.5mm_dt_{dt}',case,elastic.ElasticConfig(spanwise_bending=True),dt))
    short=copy.deepcopy(case)
    for s in short['sections']: s['y_m']*=.12/.28
    tests.append(('bare_0.5mm_short',short,elastic.ElasticConfig(spanwise_bending=True),.005))
    results={}
    for name,c,cfg,dt in tests:
        print('Running '+name,flush=True)
        r=R.run(c,settings,cfg,{'dt_s':dt,'cycles':4},
                output_dir=out/'rod_animation' if args.animation and name=='rod_dt_half' else None)
        results[name]=r
        (out/'validation.json').write_text(json.dumps(results,indent=1),encoding='utf8')
        print(name,{k:r.get(k) for k in ('status','settled','mean_thrust_N','peak_abs_root_torque_Nm','tip_bend_amplitude_m','error')},flush=True)
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,ax=plt.subplots(3,1,figsize=(8,8),layout='constrained')
    for name in ('rigid','rod_factor_0.35','rod_factor_0.7','rod_dt_half','bare_1mm','bare_0.5mm_short'):
        r=results[name]
        if r['status']!='ok': continue
        fc=r['final_cycle']; phase=fc['phase']
        for a,k in zip(ax,('thrust','torque','tip_deflection_m')):
            if k in fc:a.plot(phase,np.array(fc[k])*(1000 if k=='tip_deflection_m' else 1),label=name)
    for a,label in zip(ax,('Single-wing thrust (N)','Fluid root torque (N m)','Tip span deflection (mm)')):
        a.set(xlabel='Cycle fraction',ylabel=label); a.grid(alpha=.2)
    ax[0].legend(fontsize=8,ncol=2)
    fig.suptitle('Span-flex implementation checks · different thicknesses / span labeled')
    fig.savefig(out/'span_flex_validation.png',dpi=200)
    print(out,flush=True)


if __name__=='__main__': main()
