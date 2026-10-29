"""Budgeted Pareto coordinate exploration from one triangular seed per span.

Retain nondominated mean-thrust / peak-root-torque tradeoffs, without a torque
ceiling. This is a local sampled frontier, not proof of global optimality.
"""
import copy
import csv
import math
from pathlib import Path
import time
import traceback


DEFAULT={'span_min_m':.4,'span_max_m':.8,'span_count':4,'node_count':8,
    'root_chord_m':.2,'maximum_root_chord_m':.2,'tip_chord_m':.01,'minimum_chord_m':.01,'maximum_chord_m':None,
    'initial_step_m':.04,'minimum_step_m':.01,'shrink_factor':.5,
    'simulation_budget':500,'evaluation_budget':1000,'max_passes':20,
    'improvement_pct':.2,'frontier_parents':8,'decreasing':True,'paired_moves':True,'bounds':[]}


def options(model,config):
    r={**DEFAULT,**config.get('adaptive_search',{})}
    for obsolete in ('torque_min_nm','torque_max_nm','torque_count'):r.pop(obsolete,None)
    r['objective']='pareto_mean_thrust_peak_root_torque_v1'
    for key in ('span_count','node_count','simulation_budget','evaluation_budget','max_passes','frontier_parents'):
        r[key]=model.number(r[key],key.replace('_',' '),2 if key=='node_count' else 1,64 if key=='node_count' else None,True)
    for key in ('span_min_m','span_max_m','root_chord_m','tip_chord_m','minimum_chord_m','initial_step_m','minimum_step_m'):
        r[key]=model.number(r[key],key.replace('_',' '),.01 if 'chord' in key else 1e-12)
    upper=r.get('maximum_chord_m')
    r['maximum_chord_m']=None if upper in (None,'') else model.number(upper,'Maximum chord',r['minimum_chord_m'])
    r['shrink_factor']=model.number(r['shrink_factor'],'Step shrink factor',.01,.99)
    r['improvement_pct']=model.number(r['improvement_pct'],'Frontier sampling resolution (%)',0,100)
    for lo,hi,count,label in [('span_min_m','span_max_m','span_count','Span')]:
        if r[hi]<r[lo] or (r[count]==1 and r[lo]!=r[hi]):raise ValueError(label+' linspace needs ordered bounds and at least two samples for different endpoints.')
    jobs=1 if r['span_min_m']==r['span_max_m'] else r['span_count']
    if jobs>r['evaluation_budget']:raise ValueError('Candidate budget must cover at least one request per span search.')
    if r['minimum_step_m']>r['initial_step_m']:raise ValueError('Minimum step must not exceed initial step.')
    n=r['node_count'];raw=r.get('bounds') or [{} for _ in range(n)]
    if len(raw)!=n:raise ValueError('Provide a chord bound/step row for every adaptive node.')
    root_max=r.get('maximum_root_chord_m',.2)
    r['maximum_root_chord_m']=model.number(root_max,'Maximum root width',r['minimum_chord_m'])
    r['bounds']=[]
    for i,b in enumerate(raw):
        lo=model.number(b.get('min_m',r['minimum_chord_m']),f'Chord {i+1} minimum',r['minimum_chord_m'])
        upper=b.get('max_m',r['maximum_chord_m'])
        hi=None if upper in (None,'') else model.number(upper,f'Chord {i+1} maximum',lo,r['maximum_chord_m'])
        if hi is None:hi=r['maximum_chord_m']
        if i==0:hi=min(hi if hi is not None else math.inf,r['maximum_root_chord_m'])
        if hi is not None and hi<lo:raise ValueError('Chord minimum exceeds its maximum.')
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
        value=min(b['max_m'] if b['max_m'] is not None else math.inf,max(b['min_m'],value))
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
    c['workflow']='adaptive_pareto';c['mode']='custom';c['limits']={}
    c['adaptive_search']={**r,'enabled':True}
    import torque_study
    c=torque_study.prepare(model,c)
    c['settings']['span_panels']=max(c['settings']['span_panels'],r['node_count']-1)
    spans=levels(r['span_min_m'],r['span_max_m'],r['span_count'])
    c['settings']['case_budget']=max(c['settings'].get('case_budget',1),len(spans))
    c['designs']=[design(r,s,c['settings']['gap_m'],seed(r),f'Adaptive seed span {s:g}') for s in spans]
    spec=model.plan(c)
    spec['adaptive_search']=r
    spec['simulation_budget']=r['simulation_budget']
    spec['search_job_count']=len(spans)
    return spec


def valid(chords,r):
    return all(b['min_m']-1e-12<=c<=(b['max_m'] if b['max_m'] is not None else math.inf)+1e-12 for c,b in zip(chords,r['bounds'])) and (not r['decreasing'] or all(a>=b-1e-12 for a,b in zip(chords,chords[1:])))


def score(row):
    """Unconstrained mean thrust / peak root torque; no upper torque bound."""
    if row.get('status')!='ok' or row.get('simulation_mode')!='isolated_single_wing_v1' or not row.get('cycle_repeatable',False):return None
    thrust=row.get('single_wing_mean_thrust_N');moment=row.get('single_wing_peak_abs_roll_moment_Nm')
    if not all(isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v) for v in (thrust,moment)):return None
    if thrust<=0 or moment<=1e-9:return None
    return thrust/moment


def objectives(row):
    if row.get('status')!='ok' or row.get('simulation_mode')!='isolated_single_wing_v1' or not row.get('cycle_repeatable',False):return None
    t=row.get('single_wing_mean_thrust_N');m=row.get('single_wing_peak_abs_roll_moment_Nm')
    if not all(isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v) for v in (t,m)):return None
    return (t,m) if t>0 and m>=0 else None


def dominates(a,b):
    """Exact observed dominance: at least as much thrust and no more torque."""
    return a[0]>=b[0] and a[1]<=b[1] and (a[0]>b[0] or a[1]<b[1])


def offer(archive,entry):
    value=objectives(entry['case'])
    if value is None:return False
    if any(objectives(e['case'])==value or dominates(objectives(e['case']),value) for e in archive):return False
    archive[:]=[e for e in archive if not dominates(value,objectives(e['case']))]
    archive.append(entry)
    return True


def nearby(a,b,resolution):
    return all(abs(x-y)<=resolution*max(abs(x),abs(y),1e-9) for x,y in zip(a,b))


def frontier_parents(archive,expanded,count,resolution):
    """Protect the two extremes and prioritize gaps in normalized objective space.

    Resolution only thins parent expansion; all measured nondominated results
    remain in the archive and in the results. It never imposes a torque cutoff.
    """
    ordered=sorted(archive,key=lambda e:objectives(e['case'])[1])
    distance={id(e):0. for e in ordered}
    if ordered:
        distance[id(ordered[0])]=distance[id(ordered[-1])]=math.inf
    for axis in (0,1):
        values=[objectives(e['case'])[axis] for e in ordered]
        width=max(values,default=0)-min(values,default=0)
        if width>0:
            for i in range(1,len(ordered)-1):distance[id(ordered[i])]+=abs(values[i+1]-values[i-1])/width
    selected=[]
    for e in sorted(ordered,key=lambda e:(-distance[id(e)],objectives(e['case'])[1])):
        if tuple(e['chords']) in expanded:continue
        value=objectives(e['case'])
        if any(nearby(value,v,resolution) for v in [*expanded.values(),*[objectives(p['case']) for p in selected]]):continue
        selected.append(e)
        if len(selected)>=count:break
    return selected


def neighbor(chords,nodes,direction,steps,r):
    candidate=chords[:]
    for i in nodes:candidate[i]=round(candidate[i]+direction*steps[i],12)
    if len(nodes)==1:
        i=nodes[0];b=r['bounds'][i]
        lo=b['min_m'];hi=b['max_m'] if b['max_m'] is not None else math.inf
        if r['decreasing']:
            if i:hi=min(hi,chords[i-1])
            if i+1<len(chords):lo=max(lo,chords[i+1])
        candidate[i]=round(max(lo,min(hi,candidate[i])),12)
    return candidate if candidate!=chords and valid(candidate,r) else None


def climb(r,span,job):
    """Branch over a sampled Pareto archive from one triangle; yield each solve."""
    chords=seed(r);steps=[b['step_m'] for b in r['bounds']]
    meta={'job':job,'span_m':span,'objective':r['objective'],'pass':0,'node':None,'step_m':0.,'parent_case':None,'kind':'seed'}
    current=yield (chords[:],meta)
    archive=[];visited={tuple(chords)};expanded={}
    initial={'case':current,'chords':chords[:],**meta}
    def event(entry):
        return {'accepted':True,**entry,'frontier_case_ids':[e['case']['id'] for e in archive],
            'frontier_size':len(archive),'frontier_max_thrust_N':max(objectives(e['case'])[0] for e in archive),
            'frontier_min_torque_Nm':min(objectives(e['case'])[1] for e in archive)}
    if offer(archive,initial):yield ('accepted',event(initial))
    moves=[(i,) for i in range(len(chords))]
    if r['paired_moves']:moves += [(i,i+1) for i in range(len(chords)-1)]
    for iteration in range(1,r['max_passes']+1):
        parents=frontier_parents(archive,expanded,r['frontier_parents'],r['improvement_pct']/100)
        if not parents:
            if not archive and not expanded:parents=[initial] # Probe neighbors of an unsettled/failed seed.
            else:
                if max(steps)<=r['minimum_step_m']*(1+1e-12):return
                steps=[max(r['minimum_step_m'],s*r['shrink_factor']) for s in steps];expanded={}
                parents=frontier_parents(archive,expanded,r['frontier_parents'],r['improvement_pct']/100) or [initial]
        for parent in parents:
            expanded[tuple(parent['chords'])]=objectives(parent['case']) or (0.,0.)
            for nodes in moves:
                for direction in (1,-1):
                    candidate=neighbor(parent['chords'],nodes,direction,steps,r)
                    if candidate is None or tuple(candidate) in visited:continue
                    visited.add(tuple(candidate))
                    meta={'job':job,'span_m':span,'objective':r['objective'],'pass':iteration,'node':list(nodes),
                        'step_m':max(abs(candidate[i]-parent['chords'][i]) for i in nodes),
                        'parent_case':parent['case'].get('id'),'kind':'paired' if len(nodes)>1 else 'coordinate'}
                    trial=yield (candidate,meta)
                    entry={'case':trial,'chords':candidate,**meta}
                    if offer(archive,entry):yield ('accepted',event(entry))


def run_search(r,evaluate,on_accept=lambda event:None):
    """Fair interleaving; evaluator owns cache, persistence, and strict budgets."""
    jobs=[]
    for span in levels(r['span_min_m'],r['span_max_m'],r['span_count']):
        g=climb(r,span,len(jobs)+1);jobs.append([g,next(g)])
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
            if fresh:w.writerow(['request','case','global_case_no','job','span_m','thrust_to_peak_torque_1pm','pass','nodes','step_m','parent_case','reuse','status','mean_thrust_N','peak_root_torque_Nm','chords_m'])
            w.writerow([requests,row['id'],row.get('global_case_no'),meta['job'],meta['span_m'],score(row),meta['pass'],meta['node'],meta['step_m'],meta['parent_case'],reuse,row['status'],row.get('single_wing_mean_thrust_N'),row.get('single_wing_peak_abs_roll_moment_Nm'),chords])
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
        state(f"Adaptive trial {case['id']} · span {meta['span_m']:g} m · exploring thrust–torque frontier",current=case['id'],current_case_started=time.time())
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
        state('Adaptive search: evaluating neighbors')
        return row
    reason='Pareto searches reached their stopping condition'
    try:
        state('Preparing Pareto search from one triangle per span')
        run_search(r,evaluate,accept)
    except BudgetReached as exc:reason=str(exc)
    except Exception as exc:
        traceback.print_exc();reason='Search interrupted: '+str(exc)
        model.write_json(study/'status.json',{'state':'failed','completed':simulations,'total':r['simulation_budget'],'message':reason})
        raise
    finally:
        model.write_json(study/'evolution.json',events)
    model.write_json(study/'adaptive_summary.json',{'new_simulations':simulations,'cache_hits':cache_hits,'candidate_requests':requests,'unique_cases':len(rows),'accepted_changes':len(events),'objective':r['objective'],'frontier_case_ids':{str(job):next(e['frontier_case_ids'] for e in reversed(events) if e['job']==job) for job in {e['job'] for e in events}},'stop_reason':reason})
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
    return catalog.export(model,metric=catalog.OBJECTIVE,browser_url=browser_url,filename='master_runs_adaptive.xlsx',study_filter=study_ids(model))


def results(model):
    import catalog
    ids=study_ids(model);rows=catalog.listing(model,metric=catalog.OBJECTIVE,check_outputs=False)['rows']
    return [r for r in rows if any(o['study'] in ids for o in r['occurrences'])]


def artifacts(model,study,events):
    """Frontier discovery history, one PNG, and one compact animation."""
    if not events:return
    from PIL import Image
    import io
    dest=study/'comparisons';dest.mkdir(exist_ok=True)
    plt=model.ieee_style();fig,axes=plt.subplots(3,1,figsize=(7.16,6),layout='constrained')
    for job in sorted({e['job'] for e in events}):
        path=[e for e in events if e['job']==job and e['case'].get('status')=='ok']
        x=list(range(len(path)))
        for ax,key,label in zip(axes,['frontier_max_thrust_N','frontier_min_torque_Nm','frontier_size'],['Frontier max thrust (N)','Frontier min torque (N m)','Frontier design count']):
            ax.plot(x,[e.get(key,float('nan')) for e in path],marker='.',lw=.8,label=f"J{job}: {path[0]['span_m']:g} m" if path else f'J{job}')
            ax.set_ylabel(label);ax.grid(alpha=.2)
    if len({e['job'] for e in events})<=12:axes[0].legend(fontsize=5,ncol=2)
    axes[-1].set_xlabel('Frontier discoveries (per span)')
    axes[0].set_title('Pareto exploration · frontier progress at each span')
    fig.savefig(dest/'adaptive_progress.png',dpi=300);plt.close(fig)
    frames=[]
    # Bound media size independently of the auditable, complete event history.
    import numpy as np
    ordered=sorted(enumerate(events),key=lambda pair:(pair[1]['job'],pair[0]))
    ordered=[e for _,e in ordered]
    frame_events=[ordered[i] for i in np.unique(np.linspace(0,len(ordered)-1,min(len(ordered),200),dtype=int))]
    maximum_span=max(e['case']['sections'][-1]['y_m'] for e in frame_events)
    maximum_chord=max(s['chord_m'] for e in frame_events for s in e['case']['sections'])
    for e in frame_events:
        fig,ax=plt.subplots(figsize=(5,3),layout='constrained')
        row=e['case'];sections=row['sections'];y=[s['y_m'] for s in sections];c=[s['chord_m'] for s in sections]
        ax.fill([*y,*reversed(y)],[*[0]*len(y),*reversed(c)],color='#92c9c2',edgecolor='#007f78')
        ax.set_xlim(0,maximum_span*1.03);ax.set_ylim(maximum_chord*1.03,0);ax.set_aspect('equal');ax.set(xlabel='Root-to-tip position (m)',ylabel='Chord (m)')
        ax.set_title(f"Job {e['job']} · {row['id']} · span {e['span_m']:g} m\nThrust {row.get('single_wing_mean_thrust_N',0):.4g} N · ratio {score(row) or 0:.4g} 1/m",fontsize=9)
        buffer=io.BytesIO();fig.savefig(buffer,format='png',dpi=100);plt.close(fig)
        frames.append(Image.open(buffer).convert('RGB'))
    frames[0].save(dest/'adaptive_evolution.webp',save_all=True,append_images=frames[1:],duration=450,loop=0)
