"""Budgeted coordinate search of native isolated wings, with an auditable trial log.

Each span/torque allowance owns a local ascent. Jobs advance round-robin, share
exact geometry results and keep all trials for the observed torque frontier.
This is a local search, not a certificate of a global optimum.
"""
import copy
import csv
import math
from pathlib import Path
import time
import traceback


DEFAULT={'span_min_m':.6,'span_max_m':.8,'span_count':3,'node_count':6,
    'root_chord_m':.2,'tip_chord_m':.01,'minimum_chord_m':.01,'maximum_chord_m':.2,
    'initial_step_m':.01,'minimum_step_m':.001,'shrink_factor':.5,
    'torque_min_nm':.2,'torque_max_nm':1.2,'torque_count':4,
    'simulation_budget':100,'evaluation_budget':500,'max_passes':20,
    'improvement_pct':.2,'decreasing':True,'paired_moves':True,'bounds':[]}


def options(model,config):
    r={**DEFAULT,**config.get('adaptive_search',{})}
    for key in ('span_count','node_count','torque_count','simulation_budget','evaluation_budget','max_passes'):
        r[key]=model.number(r[key],key.replace('_',' '),2 if key=='node_count' else 1,64 if key=='node_count' else None,True)
    for key in ('span_min_m','span_max_m','root_chord_m','tip_chord_m','minimum_chord_m','maximum_chord_m','initial_step_m','minimum_step_m','torque_min_nm','torque_max_nm'):
        r[key]=model.number(r[key],key.replace('_',' '),.01 if 'chord' in key else 1e-12)
    r['shrink_factor']=model.number(r['shrink_factor'],'Step shrink factor',.01,.99)
    r['improvement_pct']=model.number(r['improvement_pct'],'Minimum improvement (%)',0,100)
    for lo,hi,count,label in [('span_min_m','span_max_m','span_count','Span'),('torque_min_nm','torque_max_nm','torque_count','Torque')]:
        if r[hi]<r[lo] or (r[count]==1 and r[lo]!=r[hi]):raise ValueError(label+' linspace needs ordered bounds and at least two samples for different endpoints.')
    jobs=(1 if r['span_min_m']==r['span_max_m'] else r['span_count'])*(1 if r['torque_min_nm']==r['torque_max_nm'] else r['torque_count'])
    if jobs>r['evaluation_budget']:raise ValueError('Candidate budget must cover at least one request per span/torque search.')
    if r['minimum_step_m']>r['initial_step_m']:raise ValueError('Minimum step must not exceed initial step.')
    if r['minimum_chord_m']>r['maximum_chord_m']:raise ValueError('Minimum chord must not exceed maximum chord.')
    n=r['node_count'];raw=r.get('bounds') or [{} for _ in range(n)]
    if len(raw)!=n:raise ValueError('Provide a chord bound/step row for every adaptive node.')
    r['bounds']=[]
    for i,b in enumerate(raw):
        lo=model.number(b.get('min_m',r['minimum_chord_m']),f'Chord {i+1} minimum',r['minimum_chord_m'])
        hi=model.number(b.get('max_m',r['maximum_chord_m']),f'Chord {i+1} maximum',lo,r['maximum_chord_m'])
        step=model.number(b.get('step_m',r['initial_step_m']),f'Chord {i+1} step',r['minimum_step_m'])
        r['bounds'].append({'min_m':lo,'max_m':hi,'step_m':step})
    if r['span_min_m']<=config['settings']['gap_m']:raise ValueError('Adaptive span must exceed the hinge gap.')
    # Validate a feasible decreasing seed, including the per-node bounds.
    seed(r)
    return r


def levels(lo,hi,count):
    import numpy as np
    return list(dict.fromkeys(float(x) for x in np.linspace(lo,hi,count)))


def seed(r):
    n=r['node_count'];out=[]
    for i,b in enumerate(r['bounds']):
        value=r['root_chord_m']+(r['tip_chord_m']-r['root_chord_m'])*i/(n-1)
        value=min(b['max_m'],max(b['min_m'],value))
        if r['decreasing'] and out:value=min(value,out[-1])
        if value<b['min_m']-1e-12:raise ValueError('Per-node bounds cannot form a decreasing seed.')
        out.append(round(value,12))
    return out


def design(r,span,gap,chords,name='Adaptive wing'):
    half=(span-gap)/2
    return {'name':name,'sections':[{'y_m':half*i/(len(chords)-1),'x_m':0.,'chord_m':c,'pitch_deg':0.,'roll_deg':0.} for i,c in enumerate(chords)]}


def plan(model,config):
    c=copy.deepcopy(config);r=options(model,c)
    c.pop('span_search',None);c.pop('refinement',None)
    c['workflow']='root_torque';c['mode']='custom';c['limits']={}
    c['adaptive_search']={**r,'enabled':True}
    c['optimization']={'max_root_moment_nm':r['torque_max_nm']}
    c['settings']['span_panels']=max(c['settings']['span_panels'],r['node_count']-1)
    spans=levels(r['span_min_m'],r['span_max_m'],r['span_count'])
    c['settings']['case_budget']=max(c['settings'].get('case_budget',1),len(spans))
    c['designs']=[design(r,s,c['settings']['gap_m'],seed(r),f'Adaptive seed span {s:g}') for s in spans]
    spec=model.plan(c)
    spec['adaptive_search']=r
    spec['simulation_budget']=r['simulation_budget']
    spec['search_job_count']=len(spans)*len(levels(r['torque_min_nm'],r['torque_max_nm'],r['torque_count']))
    return spec


def valid(chords,r):
    return all(b['min_m']-1e-12<=c<=b['max_m']+1e-12 for c,b in zip(chords,r['bounds'])) and (not r['decreasing'] or all(a>=b-1e-12 for a,b in zip(chords,chords[1:])))


def score(row,limit):
    import torque_study
    status=torque_study.classify(row,limit,allow_aeroelastic=True)
    if status not in ('Within limit','Over limit'):return None
    t=row['single_wing_mean_thrust_N'];m=row['single_wing_peak_abs_roll_moment_Nm']
    # Feasible designs rank by thrust. Infeasible seeds move toward feasibility,
    # rather than getting stuck because all nearby wings exceed the allowance.
    return (1,t) if status=='Within limit' else (0,-(m-limit)/limit,t)


def better(row,incumbent,limit,tolerance):
    a=score(row,limit);b=score(incumbent,limit)
    if a is None:return False
    if b is None:return True
    if a[0]!=b[0]:return a[0]>b[0]
    if a[0]:return a[1]>b[1]+max(abs(b[1])*tolerance,1e-10)
    return a[1]>b[1]+max(abs(b[1])*tolerance,1e-10) or (abs(a[1]-b[1])<1e-12 and a[2]>b[2]*(1+tolerance))


def climb(r,span,limit,job):
    """Coroutine yields trial chords, accepts complete results via send()."""
    chords=seed(r);steps=[b['step_m'] for b in r['bounds']]
    meta={'job':job,'span_m':span,'torque_limit_Nm':limit,'pass':0,'node':None,'step_m':0.,'parent_case':None}
    current=yield (chords[:],{**meta,'kind':'seed'})
    yield_event={'accepted':True,'case':current,'chords':chords[:],**meta}
    yield ('accepted',yield_event)
    for iteration in range(1,r['max_passes']+1):
        improved=False
        moves=[(i,) for i in range(len(chords))]
        if r['paired_moves']:moves += [(i,i+1) for i in range(len(chords)-1)]
        for nodes in moves:
            parent=current;best=current;best_chords=chords
            for direction in (1,-1):
                candidate=chords[:]
                for i in nodes:candidate[i]=round(candidate[i]+direction*steps[i],12)
                if not valid(candidate,r):continue
                meta={'job':job,'span_m':span,'torque_limit_Nm':limit,'pass':iteration,'node':list(nodes),'step_m':max(steps[i] for i in nodes),'parent_case':parent.get('id'),'kind':'paired' if len(nodes)>1 else 'coordinate'}
                trial=yield (candidate,meta)
                if better(trial,best,limit,r['improvement_pct']/100):best=trial;best_chords=candidate
            if best is not current:
                current=best;chords=best_chords;improved=True
                yield ('accepted',{'accepted':True,'case':current,'chords':chords[:],**meta})
        if not improved:
            if max(steps)<=r['minimum_step_m']*(1+1e-12):return
            steps=[max(r['minimum_step_m'],s*r['shrink_factor']) for s in steps]


def run_search(r,evaluate,on_accept=lambda event:None):
    """Fair interleaving; evaluator owns cache, persistence, and strict budgets."""
    jobs=[]
    for span in levels(r['span_min_m'],r['span_max_m'],r['span_count']):
        for limit in levels(r['torque_min_nm'],r['torque_max_nm'],r['torque_count']):
            g=climb(r,span,limit,len(jobs)+1);jobs.append([g,next(g)])
    while jobs:
        active=[]
        for g,pending in jobs:
            try:
                if pending[0]=='accepted':
                    on_accept(pending[1]);pending=next(g)
                row=evaluate(pending[0],pending[1]);pending=g.send(row)
                while pending[0]=='accepted':on_accept(pending[1]);pending=next(g)
                active.append([g,pending])
            except StopIteration:pass
        jobs=active


class BudgetReached(Exception):pass


def worker(model,study):
    import catalog
    study=Path(study);manifest=model.read_json(study/'manifest.json');r=manifest['adaptive_search']
    manifest['catalog_engine']=catalog.engine(model,manifest['settings'])
    manifest['cases']=[];manifest['case_count']=0
    model.write_json(study/'manifest.json',manifest)
    rows=[];events=[];lookup={};simulations=0;requests=0;cache_hits=0
    def state(message,**extra):
        model.write_json(study/'status.json',{'state':'running','total':r['simulation_budget'],'completed':simulations,
            'evaluated_cases':len(rows),'candidate_requests':requests,'cache_hits':cache_hits,'accepted_count':len(events),'message':message,**extra})
    def accept(event):
        events.append({**event,'evaluation':len(rows),'simulations':simulations})
        model.write_json(study/'evolution.json',events)
    def log_trial(chords,meta,row,reuse):
        path=study/'comparisons'/'adaptive_trials.csv';path.parent.mkdir(exist_ok=True)
        fresh=not path.exists()
        with path.open('a',newline='',encoding='utf-8') as f:
            w=csv.writer(f)
            if fresh:w.writerow(['request','case','global_case_no','job','span_m','torque_limit_Nm','pass','nodes','step_m','parent_case','reuse','status','mean_thrust_N','peak_root_torque_Nm','chords_m'])
            w.writerow([requests,row['id'],row.get('global_case_no'),meta['job'],meta['span_m'],meta['torque_limit_Nm'],meta['pass'],meta['node'],meta['step_m'],meta['parent_case'],reuse,row['status'],row.get('single_wing_mean_thrust_N'),row.get('single_wing_peak_abs_roll_moment_Nm'),chords])
    def evaluate(chords,meta):
        nonlocal simulations,requests,cache_hits
        if requests>=r['evaluation_budget']:raise BudgetReached('Candidate-request budget reached')
        requests+=1
        cfg=copy.deepcopy(manifest['config']);cfg.pop('adaptive_search',None)
        cfg['mode']='custom';cfg['designs']=[design(r,meta['span_m'],manifest['settings']['gap_m'],chords,'Adaptive wing')]
        case=model.plan(cfg)['cases'][0]
        sig=catalog.signature(model,case,manifest['settings'])
        if sig in lookup:
            log_trial(chords,meta,lookup[sig],'within study');return lookup[sig]
        existing=catalog.cache_entries(model,{sig}).get(sig)
        if existing is None and simulations>=r['simulation_budget']:raise BudgetReached('New-simulation budget reached')
        case['id']=f'case_{len(rows)+1:04d}';case['design_name']=f'Adaptive {len(rows)+1:04d}'
        case['adaptive_trial']=meta
        manifest['cases'].append(case);manifest['case_count']=len(manifest['cases'])
        model.write_json(study/'manifest.json',manifest)
        directory=study/case['id'];directory.mkdir(exist_ok=True)
        state(f"Adaptive trial {case['id']} · span {meta['span_m']:g} m · allowance {meta['torque_limit_Nm']:g} N m",current=case['id'],current_case_started=time.time())
        start=time.time();row={**case}
        try:
            cached=catalog.reuse(model,case,manifest['settings'],directory) if existing is not None else None
            if cached is None:
                if simulations>=r['simulation_budget']:
                    manifest['cases'].pop();manifest['case_count']=len(manifest['cases']);model.write_json(study/'manifest.json',manifest)
                    raise BudgetReached('New-simulation budget reached')
                simulations+=1
                cached=model.run_case(case,manifest['settings'],directory)
            else:cache_hits+=1
            row.update(cached,status='ok')
        except BudgetReached:raise
        except Exception as exc:
            traceback.print_exc();row.update(status='failed',error=str(exc))
            model.write_json(directory/'error.json',{'error':str(exc)})
        row['elapsed_s']=round(time.time()-start,3)
        catalog.record(model,manifest,study.name,row)
        rows.append(row);lookup[sig]=row
        log_trial(chords,meta,row,'catalog' if row.get('reused_from') else 'new solve')
        model.write_summary(study,rows)
        if manifest['settings'].get('aeroelastic_enabled',False):
            import torque_study
            report=torque_study.results(model,study)
            keys=list(dict.fromkeys(k for item in report['rows'] for k in item))
            with (study/'comparisons'/'top_performers.csv').open('w',newline='',encoding='utf-8') as f:
                writer=csv.DictWriter(f,fieldnames=['shape_rank',*keys]);writer.writeheader()
                writer.writerows({'shape_rank':i,**model.csv_row(item)} for i,item in enumerate((r for r in report['rows'] if r['thrust_rank'] is not None),1) if i<=10)
        state('Adaptive search: evaluating neighbors')
        return row
    reason='All coordinate searches reached their stopping condition'
    try:
        state('Preparing adaptive coordinate search')
        run_search(r,evaluate,accept)
    except BudgetReached as exc:reason=str(exc)
    except Exception as exc:
        traceback.print_exc();reason='Search interrupted: '+str(exc)
        model.write_json(study/'status.json',{'state':'failed','completed':simulations,'total':r['simulation_budget'],'message':reason})
        raise
    finally:
        model.write_json(study/'evolution.json',events)
    model.write_json(study/'adaptive_summary.json',{'new_simulations':simulations,'cache_hits':cache_hits,'candidate_requests':requests,'unique_cases':len(rows),'accepted_changes':len(events),'stop_reason':reason})
    artifacts(model,study,events)
    export_master(model,manifest.get('browser_url','http://127.0.0.1:8766'))
    if any(row.get('status')=='ok' for row in rows):
        import torque_frontier
        try:
            frontier=torque_frontier.generate(model,{'study':study.name})
            model.write_json(study/'frontier.json',frontier)
        except ValueError:pass
    model.write_json(study/'status.json',{'state':'complete' if not any(x['status']=='failed' for x in rows) else 'complete_with_errors',
        'total':simulations,'completed':simulations,'evaluated_cases':len(rows),'message':reason+f'; {len(rows)} unique cases, {simulations} new simulations, {cache_hits} reused.'})


_STUDY_FLAGS={}
def study_ids(model):
    ids=set()
    for p in model.OUTPUTS.glob('*/manifest.json'):
        stamp=p.stat().st_mtime_ns
        if p not in _STUDY_FLAGS or _STUDY_FLAGS[p][0]!=stamp:
            try:flag=bool(model.read_json(p).get('config',{}).get('adaptive_search',{}).get('enabled'))
            except (OSError,ValueError):continue
            _STUDY_FLAGS[p]=(stamp,flag)
        if _STUDY_FLAGS[p][1]:ids.add(p.parent.name)
    return ids


def export_master(model,browser_url):
    import catalog
    return catalog.export(model,metric='single_wing_mean_thrust_N',browser_url=browser_url,filename='master_runs_adaptive.xlsx',study_filter=study_ids(model))


def results(model):
    import catalog
    ids=study_ids(model);rows=catalog.listing(model,metric='single_wing_mean_thrust_N',check_outputs=False)['rows']
    return [r for r in rows if any(o['study'] in ids for o in r['occurrences'])]


def artifacts(model,study,events):
    """Accepted-path history, one PNG, and one compact evolution animation."""
    if not events:return
    from PIL import Image
    import io
    dest=study/'comparisons';dest.mkdir(exist_ok=True)
    plt=model.ieee_style();fig,axes=plt.subplots(3,1,figsize=(7.16,6),layout='constrained')
    for job in sorted({e['job'] for e in events}):
        path=[e for e in events if e['job']==job and e['case'].get('status')=='ok']
        x=list(range(len(path)))
        for ax,key,label in zip(axes,['single_wing_mean_thrust_N','single_wing_peak_abs_roll_moment_Nm','single_wing_thrust_roll_ratio_1pm'],['Mean thrust (N)','Peak root torque (N m)','Thrust / torque (1/m)']):
            ax.plot(x,[e['case'].get(key,float('nan')) for e in path],marker='.',lw=.8,label=f"J{job}: {path[0]['span_m']:g} m / {path[0]['torque_limit_Nm']:g} Nm" if path else f'J{job}')
            ax.set_ylabel(label);ax.grid(alpha=.2)
    if len({e['job'] for e in events})<=12:axes[0].legend(fontsize=5,ncol=2)
    axes[-1].set_xlabel('Accepted design changes (per search)')
    axes[0].set_title('Coordinate ascent · each path has a fixed span and torque allowance')
    fig.savefig(dest/'adaptive_progress.png',dpi=300);plt.close(fig)
    frames=[]
    # Bound media size independently of the auditable, complete event history.
    import numpy as np
    ordered=sorted(enumerate(events),key=lambda pair:(pair[1]['job'],pair[0]))
    ordered=[e for _,e in ordered]
    frame_events=[ordered[i] for i in np.unique(np.linspace(0,len(ordered)-1,min(len(ordered),200),dtype=int))]
    for e in frame_events:
        fig,ax=plt.subplots(figsize=(5,3),layout='constrained')
        row=e['case'];sections=row['sections'];y=[s['y_m'] for s in sections];c=[s['chord_m'] for s in sections]
        ax.fill([*y,*reversed(y)],[*[0]*len(y),*reversed(c)],color='#92c9c2',edgecolor='#007f78')
        ax.invert_yaxis();ax.set_aspect('equal');ax.set(xlabel='Root-to-tip position (m)',ylabel='Chord (m)')
        ax.set_title(f"Job {e['job']} · {row['id']} · span {e['span_m']:g} m\nAllowance {e['torque_limit_Nm']:g} N m · thrust {row.get('single_wing_mean_thrust_N',0):.4g} N",fontsize=9)
        buffer=io.BytesIO();fig.savefig(buffer,format='png',dpi=100);plt.close(fig)
        frames.append(Image.open(buffer).convert('RGB'))
    frames[0].save(dest/'adaptive_evolution.webp',save_all=True,append_images=frames[1:],duration=450,loop=0)
