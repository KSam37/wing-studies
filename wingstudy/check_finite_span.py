"""Bounded validation of the 0.5 mm bare wing at finite deflection, no catalog writes."""
import argparse
from concurrent.futures import ProcessPoolExecutor,as_completed
import json
from pathlib import Path


def evaluate(job):
    name,opts,overrides=job
    from . import elastic, elastic_runner as R
    from . import cases as _cases
    c,s=_cases.load_case(7657)
    cfg=elastic.ElasticConfig.from_dict(dict(spanwise_bending=True,large_deflection=True,
        max_bend_deg=75.,max_tip_deflection_fraction=.95,**opts))
    r=R.run(c,s,cfg,{'cycles':4,'dt_s':.01,**overrides})
    return name,r


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--animation',action='store_true')
    p.add_argument('--extended',action='store_true',help='add two finer checks to an existing validation file')
    p.add_argument('--fine-coupling',action='store_true',help='check stronger stabilization at the finest time step')
    args=p.parse_args()
    root=Path(__file__).resolve().parent.parent
    out=root/'outputs/elastic/span_validation'
    out.mkdir(parents=True,exist_ok=True)
    jobs=[('factor_0.35',{'added_mass_factor':.35},{}),('factor_0.7',{'added_mass_factor':.7},{}),
          ('dt_half',{}, {'dt_s':.005}),('mesh_16_dt_half',{}, {'dt_s':.005,'span_panels':16}),
          ('stiff_limit',{'material':{'youngs_modulus_pa':5e15,'shear_modulus_pa':4.5e14}}, {})]
    data={}
    if args.extended:
        data=json.loads((out/'finite_validation.json').read_text())
        jobs=[('mesh_16_factor_0.7',{'added_mass_factor':.7},{'dt_s':.005,'span_panels':16}),
              ('mesh_16_dt_quarter',{}, {'dt_s':.0025,'span_panels':16})]
    if args.fine_coupling:
        data=json.loads((out/'finite_validation.json').read_text())
        jobs=[('mesh_16_dt_quarter_factor_0.7',{'added_mass_factor':.7},{'dt_s':.0025,'span_panels':16}),
              ('mesh_16_dt_quarter_factor_1.0',{'added_mass_factor':1.},{'dt_s':.0025,'span_panels':16})]
    with ProcessPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(evaluate,j) for j in jobs]
        for fu in as_completed(futures):
            name,r=fu.result(); data[name]=r
            (out/'finite_validation.json').write_text(json.dumps(data,indent=1),encoding='utf8')
            print(name,{k:r.get(k) for k in ('status','settled','mean_thrust_N','peak_abs_root_torque_Nm','tip_bend_amplitude_m','peak_abs_bend_deg','error')},flush=True)
    if args.animation and data['mesh_16_dt_half']['status']=='ok':
        import contextlib
        from . import elastic, elastic_runner as R
        from . import cases as _cases
        c,s=_cases.load_case(7657)
        cfg=elastic.ElasticConfig(spanwise_bending=True,large_deflection=True,max_bend_deg=75,max_tip_deflection_fraction=.95)
        with (out/'finite_animation.log').open('w',encoding='utf8') as log,contextlib.redirect_stdout(log),contextlib.redirect_stderr(log):
            r=R.run(c,s,cfg,{'dt_s':.005,'cycles':4,'span_panels':16},output_dir=out/'bare_0p5mm_animation')
        print('Animation:',r['status'],r.get('error',''),flush=True)
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import numpy as np
    fig,axes=plt.subplots(3,1,figsize=(8,8),layout='constrained')
    for name in ('factor_0.35','factor_0.7','dt_half','mesh_16_dt_half','mesh_16_factor_0.7','mesh_16_dt_quarter','mesh_16_dt_quarter_factor_0.7','mesh_16_dt_quarter_factor_1.0'):
        if name not in data:continue
        r=data[name]
        if r['status']!='ok':continue
        for ax,key,scale in zip(axes,('thrust','torque','tip_deflection_m'),(1,1,1000)):
            fc=r['final_cycle']; ax.plot(fc['phase'],scale*np.array(fc[key]),label=name)
    for a,label in zip(axes,('Thrust per wing (N)','Fluid root torque (N m)','Tip deflection (mm)')):
        a.set(xlabel='Cycle fraction',ylabel=label);a.grid(alpha=.2)
    axes[0].legend(ncol=2,fontsize=8)
    fig.suptitle('0.5 mm carbon sheet · no rod · wing 7657\nFinite-rotation model: numerical sensitivity')
    fig.savefig(out/'bare_0p5mm_finite_checks.png',dpi=200)
    print(out,flush=True)


if __name__=='__main__':main()
