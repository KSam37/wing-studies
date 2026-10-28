"""Maximize native single-wing mean thrust subject to a root-moment limit.

The limit is a decision constraint, never a solver setting or drivetrain model.
Existing physical results can be re-ranked without a new Ptera solve.
"""
import copy
import csv
import math
from wing_dimensions import dimensions
from pathlib import Path

WORKFLOW='root_torque'


def default_config(model):
    c=copy.deepcopy(model.DEFAULT)
    c.update(workflow=WORKFLOW,name='Thrust under root moment limit',mode='shape_sweep',
        optimization={'max_root_moment_nm':.625},motion_range={'minimum_deg':-26.,'maximum_deg':34.})
    c['settings'].update(frequency_hz=1.,amplitude_deg=30.,aeroelastic_enabled=False,wake_model='prescribed',wake_cycles=2)
    c['shape_sweep']['span_m']=.8
    c['shape_sweep']['ranges'][0]={'min_m':.12,'max_m':.20,'count':3}
    return c


def prepare(model,config):
    c=copy.deepcopy(config)
    if c.get('adaptive_search',{}).get('enabled'):
        c['optimization']={'objective':'single_wing_thrust_roll_ratio_1pm','constraint':'none'}
    else:
        limit=model.number(c.get('optimization',{}).get('max_root_moment_nm'),'Maximum root moment',1e-12)
        c['optimization']={'max_root_moment_nm':limit,'objective':'single_wing_mean_thrust_N',
            'constraint':'final_cycle_peak_absolute_single_wing_root_roll_moment'}
    c['settings']['aeroelastic_enabled']=c['settings'].get('aeroelastic_enabled',False) if c.get('adaptive_search',{}).get('enabled') else False
    c['settings']['save_solver']=False
    c['tail']={'enabled':False}
    motion=c.get('motion_range',{'minimum_deg':-26.,'maximum_deg':34.})
    lo=model.number(motion.get('minimum_deg'),'Minimum flap angle',-89.9,0.)
    hi=model.number(motion.get('maximum_deg'),'Maximum flap angle',0.,89.9)
    if hi<=lo:raise ValueError('Maximum flap angle must exceed minimum.')
    center=(lo+hi)/2;amplitude=(hi-lo)/2
    if abs(center)<1e-12:
        c['waveform']={'mode':'sine'};c['settings']['amplitude_deg']=amplitude
    else:
        phase0=math.asin(-center/amplitude)
        points=[[i/32,center+amplitude*math.sin(2*math.pi*i/32+phase0)] for i in range(33)]
        points[0][1]=points[-1][1]=0.
        c['waveform']={'mode':'custom','points':points}
        c['settings']['amplitude_deg']=model.FlapWave(c['waveform']).scale
    c['motion_range']={'minimum_deg':lo,'maximum_deg':hi}
    if c.get('span_search',{}).get('enabled'):
        import refinement
        c['designs']=refinement.span_designs(model,c)
        c['mode']='custom'
    elif c.get('refinement',{}).get('enabled'):
        if c['refinement'].get('search_method')=='linspace':
            # Reuse the original exact grid, taper pruning and case-budget guard.
            c['mode']='shape_sweep';c['designs']=[]
        else:
            import refinement
            c['designs']=refinement.designs(model,c)
            c['mode']='custom'
    return c


def classify(row,limit,repeat_only=True,aeroelastic=False,allow_aeroelastic=False):
    if row.get('status')!='ok':return 'Failed'
    if (aeroelastic or row.get('aeroelastic_enabled',False)) and not allow_aeroelastic:return 'Aeroelastic result excluded'
    if row.get('simulation_mode')!='isolated_single_wing_v1':return 'Single-wing result required'
    thrust=row.get('single_wing_mean_thrust_N');moment=row.get('single_wing_peak_abs_roll_moment_Nm')
    if not all(isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v) for v in (thrust,moment)) or moment<0:
        return 'Invalid loads'
    if repeat_only and not row.get('cycle_repeatable',False):return 'Unsettled'
    if thrust<=0:return 'No positive thrust'
    return 'Within limit' if moment<=limit else 'Over limit'


def rank(rows,limit,repeat_only=True,aeroelastic=False,allow_aeroelastic=False):
    if not isinstance(limit,(int,float)) or isinstance(limit,bool) or not math.isfinite(limit) or limit<=0:
        raise ValueError('Enter a positive maximum root moment in N m.')
    evaluated=[{**r,**dimensions(r),'torque_status':classify(r,limit,repeat_only,aeroelastic,allow_aeroelastic)} for r in rows]
    eligible=sorted((r for r in evaluated if r['torque_status']=='Within limit'),
        key=lambda r:(-r['single_wing_mean_thrust_N'],r['single_wing_peak_abs_roll_moment_Nm'],r['id']))
    ranks={r.get('comparison_key',r['id']):i for i,r in enumerate(eligible,1)}
    for r in evaluated:
        r['thrust_rank']=ranks.get(r.get('comparison_key',r['id']));r['root_moment_limit_Nm']=limit
        if isinstance(r.get('single_wing_peak_abs_roll_moment_Nm'),(int,float)):
            r['root_moment_margin_Nm']=limit-r['single_wing_peak_abs_roll_moment_Nm']
    evaluated.sort(key=lambda r:(r['thrust_rank'] is None,r['thrust_rank'] or 0,r['id']))
    return {'maximum_root_moment_nm':limit,'winner':eligible[0] if eligible else None,
        'feasible_count':len(eligible),'total_count':len(rows),'rows':evaluated,
        'note':'Maximum final-cycle mean single-wing thrust subject to final-cycle peak absolute root roll moment. Native isolated wings only. This is not a motor-shaft torque limit.'}


def results(model,study,limit=None,repeat_only=True,export=False):
    study=Path(study);manifest=model.read_json(study/'manifest.json')
    if limit is None:limit=manifest.get('config',{}).get('optimization',{}).get('max_root_moment_nm')
    rows=model.read_json(study/'results.json') if (study/'results.json').exists() else []
    elastic=manifest['settings'].get('aeroelastic_enabled',False)
    report=rank(rows,limit,repeat_only,elastic,allow_aeroelastic=elastic)
    report['model_mode']='aeroelastic' if elastic else 'rigid'
    if not export:return report
    return export_report(model,study,report,manifest['settings'])


def select_model(rows,mode):
    if mode not in ('rigid','aeroelastic'):raise ValueError('Choose rigid or native aeroelastic results.')
    return [r for r in rows if bool(r.get('aeroelastic_enabled',r.get('_settings',{}).get('aeroelastic_enabled',False)))==(mode=='aeroelastic')]


def master_results(model,selected,limit,export=False,model_mode='rigid'):
    import catalog
    data=catalog.generations(model,selected)
    rows=select_model(data['rows'],model_mode)
    report={**rank(rows,limit,allow_aeroelastic=model_mode=='aeroelastic'),**{k:v for k,v in data.items() if k!='rows'},'model_mode':model_mode}
    if export:
        import hashlib
        name='compiled-master-'+hashlib.sha256(catalog.compact([sorted(selected),model_mode]).encode()).hexdigest()[:8]
        study=model.OUTPUTS/name;study.mkdir(exist_ok=True)
        export_report(model,study,report,{})
    return report


def overview(model,study,selected=('current',),model_mode='rigid',export=False,span_class='all'):
    """Full-range result view. No optimization constraint or implied winner."""
    import catalog
    import torque_frontier
    if study=='master':
        data=catalog.generations(model,selected)
        rows=select_model(data['rows'],model_mode)
        extra={k:v for k,v in data.items() if k!='rows'}
    else:
        directory=model.OUTPUTS/study;manifest=model.read_json(directory/'manifest.json')
        model_mode='aeroelastic' if manifest['settings'].get('aeroelastic_enabled',False) else 'rigid'
        rows=model.read_json(directory/'results.json') if (directory/'results.json').exists() else []
        rows=[{**r,'_study':study,'_settings':manifest['settings']} for r in rows]
        extra={}
    from wing_dimensions import span_class as classify_span
    classes={}
    for r in rows:
        k=classify_span(r);classes[k]=classes.get(k,0)+1
    available=sorted(classes,key=lambda k:float(k) if k!='unknown' else float('inf'))
    if span_class not in classes:span_class='all'
    if span_class!='all':rows=[r for r in rows if classify_span(r)==span_class]
    eligible,frontier=torque_frontier.envelope(rows,allow_aeroelastic=model_mode=='aeroelastic')
    key=lambda r:r.get('comparison_key',r['id'])
    frontier_keys={key(r) for r in frontier}
    ranked=sorted(eligible,key=lambda r:(-r['single_wing_mean_thrust_N'],r['single_wing_peak_abs_roll_moment_Nm'],key(r)))
    ranks={key(r):i for i,r in enumerate(ranked,1)}
    evaluated=[]
    for row in rows:
        status=classify(row,float('inf'),allow_aeroelastic=model_mode=='aeroelastic')
        on_frontier=key(row) in frontier_keys
        evaluated.append({**row,**dimensions(row),'is_frontier':on_frontier,'thrust_rank':ranks.get(key(row)),
            'torque_status':('Frontier' if on_frontier else 'Eligible') if status=='Within limit' else status})
    def ratio(r):
        t=r.get('single_wing_mean_thrust_N');m=r.get('single_wing_peak_abs_roll_moment_Nm')
        return t/m if key(r) in ranks and isinstance(m,(int,float)) and m>1e-9 else None
    evaluated.sort(key=lambda r:(ratio(r) is None,-ratio(r) if ratio(r) is not None else 0,key(r)))
    for i,r in enumerate(evaluated,1):r['ratio_rank']=i if ratio(r) is not None else None
    report={**extra,'model_mode':model_mode,'span_class':span_class,'span_classes':[{'key':k,'count':classes[k]} for k in available],'rows':evaluated,'total_count':len(rows),
        'eligible_count':len(eligible),'frontier_count':len(frontier),'full_range':True,
        'note':'All eligible measured designs across peak root torque. No single torque cutoff; the frontier is the best observed thrust at or below each torque.'}
    if export:
        if not frontier:raise ValueError('No eligible designs to export for this comparison.')
        report['files']=torque_frontier.generate(model,{'study':study,'generations':list(selected),'model_mode':model_mode,'span_class':span_class})['files']
    return report


def export_report(model,study,report,settings):
    limit=report['maximum_root_moment_nm']
    dest=study/'comparisons';dest.mkdir(exist_ok=True)
    name='thrust_under_root_limit';csv_path=dest/(name+'.csv')
    exported=[{**r,'study':r.get('_study',study.name),**{k:r.get('_settings',settings).get(k) for k in
        ('frequency_hz','amplitude_deg','speed_mps','rho','nu','dt_s','cycles','span_panels','chord_panels','wake_model','wake_cycles')},
        'waveform':r.get('_settings',settings).get('waveform')} for r in report['rows']]
    keys=list(dict.fromkeys(['thrust_rank','id','torque_status','root_moment_limit_Nm','root_moment_margin_Nm',
        'single_wing_mean_thrust_N','estimated_two_wing_mean_thrust_N','single_wing_peak_abs_roll_moment_Nm',
        *[k for r in exported for k in r]]))
    with csv_path.open('w',newline='',encoding='utf-8') as f:
        writer=csv.DictWriter(f,fieldnames=keys);writer.writeheader();writer.writerows(model.csv_row(r) for r in exported)
    plt=model.ieee_style();fig,ax=plt.subplots(figsize=(3.5,2.7),layout='constrained')
    for status,color in [('Within limit','#007f78'),('Over limit','#c76b2a'),('Unsettled','#88949e')]:
        selected=[r for r in report['rows'] if r['torque_status']==status]
        if selected:ax.scatter([r['single_wing_peak_abs_roll_moment_Nm'] for r in selected],
            [r['single_wing_mean_thrust_N'] for r in selected],s=12,label=status,color=color)
    ax.axvline(limit,color='#a33a29',ls='--',lw=.8,label=f'Limit {limit:g} N m')
    if report['winner']:
        r=report['winner'];ax.scatter([r['single_wing_peak_abs_roll_moment_Nm']],[r['single_wing_mean_thrust_N']],
            marker='*',s=75,edgecolors='black',linewidths=.5,color='#007f78',label='Best feasible')
    else:ax.text(.5,.5,'No feasible design',ha='center',va='center',transform=ax.transAxes,fontsize=9)
    ax.set(xlabel='Peak absolute wing-root moment (N m)',ylabel='Mean single-wing thrust (N)')
    ax.legend(fontsize=6);ax.grid(alpha=.2)
    fig.savefig(dest/(name+'.png'),dpi=600);plt.close(fig)
    report['files']=[str((dest/(name+ext)).relative_to(model.OUTPUTS)).replace('\\','/') for ext in ('.png','.csv')]
    return report
