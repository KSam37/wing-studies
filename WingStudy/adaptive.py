"""Budgeted Pareto direct exploration from multiple shape families per span.

Retain nondominated mean-thrust / peak-root-torque tradeoffs, without a torque
ceiling. This is a local sampled frontier, not proof of global optimality.
"""
import copy
import csv
import math
import itertools
from pathlib import Path


DEFAULT={'span_min_m':.4,'span_max_m':.8,'span_count':3,'node_count':8,
    'root_chord_m':.2,'maximum_root_chord_m':.2,'tip_chord_m':.01,'minimum_chord_m':.01,'maximum_chord_m':None,
    'initial_step_m':.02,'minimum_step_m':.01,'shrink_factor':.5,
    'simulation_budget':500,'evaluation_budget':1000,'max_passes':20,
    'improvement_pct':.2,'frontier_parents':3,'parallel_workers':1,'poll_candidates':0,'seed_families':['triangle'],
    'acceptance_rule':'coordinate','tradeoff_lambda':.75,'score_tolerance':1e-6,
    'coordinated_moves':True,'decreasing':True,'paired_moves':True,'bounds':[]}

SEED_FAMILIES=('triangle','square','concave','convex','narrow')

def search_jobs(r):
    if r.get('seed_design'):return [(r['span_min_m'],'refined')]
    return [(span,family) for span in levels(r['span_min_m'],r['span_max_m'],r['span_count'])
        for family in r.get('seed_families',['triangle'])]


def options(model,config):
    r={**DEFAULT,**config.get('adaptive_search',{})}
    for obsolete in ('torque_min_nm','torque_max_nm','torque_count'):r.pop(obsolete,None)
    r['objective']='pareto_mean_thrust_peak_root_torque_v1'
    r['search_algorithm']='strict_parent_ascent_v4' if r['acceptance_rule']=='strict_thrust_nonincreasing_torque' else 'family_beam_direct_poll_v3'
    if r['acceptance_rule']=='coordinate':
        r['search_algorithm']='independent_coordinate_v1'
        r['objective']='normalized_thrust_minus_lambda_torque_v1'
        r['tradeoff_lambda']=model.number(r['tradeoff_lambda'],'Torque weight lambda',0)
        r['score_tolerance']=model.number(r['score_tolerance'],'Minimum positive score change',0)
    if r['acceptance_rule']=='torque_curve':
        r['search_algorithm']='torque_envelope_search_v5'
        r['objective']='max_mean_thrust_across_root_torque_targets_v1'
        r['curve_torque_samples']=model.number(r.get('curve_torque_samples',12),'Available torque samples',2,200,True)
        for key in ('curve_torque_min_nm','curve_torque_max_nm'):
            raw=r.get(key);r[key]=None if raw in (None,'') else model.number(raw,key,0)
        if r['curve_torque_min_nm'] is not None and r['curve_torque_max_nm'] is not None and r['curve_torque_max_nm']<=r['curve_torque_min_nm']:
            raise ValueError('Maximum available torque must exceed minimum available torque.')
    # New GUI studies have one user-facing budget. Retain legacy limits only
    # for old saved configurations and direct callers that explicitly use them.
    budget_only=bool(r.get('budget_only',False)) or r['acceptance_rule'] in ('torque_curve','coordinate')
    r['budget_only']=budget_only
    if budget_only:
        r.update(max_passes=None,evaluation_budget=None,poll_candidates=8)
    if r.get('seed_design'):
        if r['acceptance_rule']!='coordinate':raise ValueError('Selected-wing refinement requires the coordinate objective.')
        r['seed_families']=['refined']
    families=r['seed_families']
    if not isinstance(families,list) or not families or any(f not in (*SEED_FAMILIES,'refined') or (f=='refined' and not r.get('seed_design')) for f in families):
        raise ValueError('Select at least one supported seed family.')
    r['seed_families']=list(dict.fromkeys(families))
    r['parallel_workers']=model.number(r['parallel_workers'],'Parallel Ptera processes',1,61,True)
    r['poll_candidates']=model.number(r['poll_candidates'],'Candidates per local poll',0,256,True)
    for key in ('span_count','node_count','simulation_budget','evaluation_budget','max_passes','frontier_parents'):
        if budget_only and key in ('evaluation_budget','max_passes'):continue
        r[key]=model.number(r[key],key.replace('_',' '),2 if key=='node_count' else 1,64 if key=='node_count' else None,True)
    for key in ('span_min_m','span_max_m','root_chord_m','tip_chord_m','minimum_chord_m','initial_step_m','minimum_step_m'):
        r[key]=model.number(r[key],key.replace('_',' '),0 if key in ('tip_chord_m','minimum_chord_m') else 1e-12)
    if r['acceptance_rule']=='coordinate':
        # One half-step per chord, not recursive shrink-to-convergence.
        r['minimum_step_m']=r['initial_step_m']*.5
    upper=r.get('maximum_chord_m')
    r['maximum_chord_m']=None if upper in (None,'') else model.number(upper,'Maximum chord',r['minimum_chord_m'])
    r['shrink_factor']=model.number(r['shrink_factor'],'Step shrink factor',.01,.99)
    r['improvement_pct']=model.number(r['improvement_pct'],'Frontier sampling resolution (%)',0,100)
    for lo,hi,count,label in [('span_min_m','span_max_m','span_count','Span')]:
        if r[hi]<r[lo] or (r[count]==1 and r[lo]!=r[hi]):raise ValueError(label+' linspace needs ordered bounds and at least two samples for different endpoints.')
    jobs=(1 if r['span_min_m']==r['span_max_m'] else r['span_count'])*len(r['seed_families'])
    if not budget_only and jobs>r['evaluation_budget']:raise ValueError('Candidate budget must cover at least one request per span search.')
    if r['minimum_step_m']>r['initial_step_m']:raise ValueError('Minimum step must not exceed initial step.')
    n=r['node_count'];raw=r.get('bounds') or [{} for _ in range(n)]
    if len(raw)!=n:raise ValueError('Provide a chord bound/step row for every adaptive node.')
    root_max=r.get('maximum_root_chord_m',.2)
    r['maximum_root_chord_m']=model.number(root_max,'Maximum root width',max(r['minimum_chord_m'],1e-12))
    r['bounds']=[]
    r['allow_zero_outboard']=bool(r.get('allow_zero_outboard',r['acceptance_rule'] in ('torque_curve','coordinate')))
    for i,b in enumerate(raw):
        floor=r['minimum_chord_m'] if i<2 else 0.
        default_min=0. if i>=2 and r['allow_zero_outboard'] else r['minimum_chord_m']
        lo=model.number(b.get('min_m',default_min),f'Chord {i+1} minimum',floor)
        if 0<lo<r['minimum_chord_m']:raise ValueError('Chord bounds must be zero or at least the positive chord minimum.')
        upper=b.get('max_m',r['maximum_chord_m'])
        hi=None if upper in (None,'') else model.number(upper,f'Chord {i+1} maximum',lo,r['maximum_chord_m'])
        if hi is None:hi=r['maximum_chord_m']
        if i==0:hi=min(hi if hi is not None else math.inf,r['maximum_root_chord_m'])
        if hi is not None and hi<lo:raise ValueError('Chord minimum exceeds its maximum.')
        step=model.number(b.get('step_m',r['initial_step_m']),f'Chord {i+1} step',1e-12 if r['acceptance_rule']=='coordinate' else r['minimum_step_m'])
        r['bounds'].append({'min_m':lo,'max_m':hi,'step_m':step})
    if r['span_min_m']<=config['settings']['gap_m']:raise ValueError('Adaptive span must exceed the hinge gap.')
    if r.get('seed_design'):
        import refinement
        r['seed_sections']=refinement.coordinate_seed(model,r['seed_design'],n,config['settings'])['sections']
        span=2*r['seed_sections'][-1]['y_m']+config['settings']['gap_m']
        r.update(span_min_m=span,span_max_m=span,span_count=1)
        scales=r.get('reference_scales')
        if scales is not None:
            r['reference_scales']={k:model.number(scales.get(k),k,1e-12) for k in ('thrust_scale_N','torque_scale_Nm')}
    # Validate a feasible decreasing seed, including the per-node bounds.
    for family in r['seed_families']:seed(r,family)
    return r


def levels(lo,hi,count):
    import numpy as np
    return list(dict.fromkeys(float(x) for x in np.linspace(lo,hi,count)))


def seed(r,family='triangle'):
    if r.get('seed_sections'):
        chords=[s['chord_m'] for s in r['seed_sections']]
        if not valid(chords,r):raise ValueError('Selected wing lies outside the chord bounds; widen the bounds to include it.')
        return chords
    n=r['node_count'];out=[]
    for i,b in enumerate(r['bounds']):
        eta=i/(n-1);root=r['root_chord_m'];tip=r['tip_chord_m']
        profile={'triangle':1-eta,'square':1.,'concave':(1-eta)**2,
            'convex':1-eta**2,'narrow':1.}[family]
        value=tip+(root-tip)*profile
        if family=='narrow':value*=.5
        value=min(b['max_m'] if b['max_m'] is not None else math.inf,max(b['min_m'],value))
        if r['decreasing'] and out:value=min(value,out[-1])
        if value<b['min_m']-1e-12:raise ValueError('Per-node bounds cannot form a decreasing seed.')
        value=round(value,12)
        if 0<value<r['minimum_chord_m']-1e-12:value=0. if b['min_m']==0 else r['minimum_chord_m']
        out.append(round(value,12))
    if not valid(out,r):raise ValueError('Seed must have two positive sections followed only by optional trailing zeros.')
    return out


def design(r,span,gap,chords,name='Adaptive wing'):
    if r.get('seed_sections'):
        return {'name':name,'sections':[{**s,'chord_m':c} for s,c in zip(r['seed_sections'],chords)]}
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
    jobs=search_jobs(r)
    c['settings']['case_budget']=max(c['settings'].get('case_budget',1),len(jobs))
    c['designs']=[design(r,s,c['settings']['gap_m'],seed(r,f),f'{f.title()} seed span {s:g}') for s,f in jobs]
    spec=model.plan(c)
    spec['adaptive_search']=r
    spec['simulation_budget']=r['simulation_budget']
    spec['search_job_count']=len(spans)*r['curve_torque_samples'] if r['acceptance_rule']=='torque_curve' else len(jobs)
    return spec


def valid(chords,r):
    if len(chords)!=len(r['bounds']):return False
    zero=next((i for i,c in enumerate(chords) if c==0),len(chords))
    return (zero>=2 and all(c==0 for c in chords[zero:])
        and all(math.isfinite(c) and c>=0 and (c==0 or c>=r['minimum_chord_m']-1e-12) for c in chords)
        and all(b['min_m']-1e-12<=c<=(b['max_m'] if b['max_m'] is not None else math.inf)+1e-12 for c,b in zip(chords,r['bounds']))
        and (not r['decreasing'] or all(a>=b-1e-12 for a,b in zip(chords,chords[1:]))))


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
    from pareto_poll import candidate
    weights=[float(direction) if i in nodes else 0. for i in range(len(chords))]
    return candidate(chords,weights,steps,r,valid)


def improves(candidate_row,parent_row):
    """Parent dominance: neither metric worsens and at least one improves."""
    a=objectives(candidate_row);b=objectives(parent_row)
    return a is not None and b is not None and dominates(a,b)


def strict_climb(r,span,job,family):
    from pareto_poll import directions,candidate
    chords=seed(r,family);steps=[b['step_m'] for b in r['bounds']]
    meta={'job':job,'span_m':span,'seed_family':family,'objective':r['objective'],
        'search_algorithm':r['search_algorithm'],'pass':0,'node':None,'step_m':0.,'parent_case':None,'kind':'seed'}
    current=yield (chords[:],meta)
    if objectives(current) is None:return
    def event(row,widths,metadata):
        return {'accepted':True,'evolution_role':'seed' if metadata['kind']=='seed' else 'improvement',
            'case':row,'chords':widths[:],**metadata,'frontier_case_ids':[row['id']],
            'frontier_size':1,'frontier_max_thrust_N':objectives(row)[0],'frontier_min_torque_Nm':objectives(row)[1]}
    yield ('accepted',event(current,chords,meta))
    basis=directions(len(chords),r['paired_moves'],r.get('coordinated_moves',True))
    visited={tuple(chords)};offset=0;iteration=0
    while r.get('max_passes') is None or iteration<r['max_passes']:
        iteration+=1;cap=r.get('poll_candidates',0) or len(basis)
        block=basis[offset:offset+cap];offset+=len(block);pending=[]
        for weights,kind in block:
            proposed=candidate(chords,weights,steps,r,valid)
            if proposed is None or tuple(proposed) in visited:continue
            visited.add(tuple(proposed))
            nodes=[i for i,(a,b) in enumerate(zip(chords,proposed)) if a!=b]
            metadata={**meta,'pass':iteration,'kind':kind,'node':nodes,'poll_steps_m':steps[:],
                'step_m':max(abs(proposed[i]-chords[i]) for i in nodes),'parent_case':current['id']}
            pending.append((proposed,metadata))
        responses=(yield ('batch',pending)) if r.get('parallel_workers',1)>1 and pending else None
        winners=[]
        for i,(proposed,metadata) in enumerate(pending):
            if responses is not None:
                if i>=len(responses):break
                trial=responses[i]
            else:trial=yield (proposed,metadata)
            if improves(trial,current):winners.append((trial,proposed,metadata))
        if winners:
            current,chords,chosen=max(winners,key=lambda item:(objectives(item[0])[0],-objectives(item[0])[1]))
            yield ('accepted',event(current,chords,chosen))
            offset=0
            steps=[max(r['minimum_step_m'],s*r['shrink_factor']) for s in steps]
        elif offset>=len(basis):
            if max(steps)<=r['minimum_step_m']*(1+1e-12):return
            steps=[max(r['minimum_step_m'],s*r['shrink_factor']) for s in steps];offset=0


def climb(r,span,job,family='triangle'):
    """One family/span branch with a bounded, coarse-to-fine active beam."""
    if r.get('acceptance_rule')=='torque_curve':
        raise ValueError('Torque-range searches require torque_search.run and its shared case pipeline.')
    if r.get('acceptance_rule')=='strict_thrust_nonincreasing_torque':
        yield from strict_climb(r,span,job,family)
        return
    from pareto_poll import directions,candidate
    chords=seed(r,family);initial_steps=[b['step_m'] for b in r['bounds']]
    meta={'job':job,'span_m':span,'seed_family':family,'objective':r['objective'],'search_algorithm':r['search_algorithm'],
        'pass':0,'node':None,'step_m':0.,'parent_case':None,'kind':'seed'}
    current=yield (chords[:],meta)
    archive=[];visited={tuple(chords)}
    initial={'case':current,'chords':chords[:],**meta}
    states={tuple(chords):{'steps':initial_steps,'polls':0,'done':False}}
    def event(entry):
        return {'accepted':True,**entry,'frontier_case_ids':[e['case']['id'] for e in archive],
            'frontier_size':len(archive),'frontier_max_thrust_N':max(objectives(e['case'])[0] for e in archive),
            'frontier_min_torque_Nm':min(objectives(e['case'])[1] for e in archive)}
    if offer(archive,initial):yield ('accepted',event(initial))
    poll_directions=directions(len(chords),r['paired_moves'],r.get('coordinated_moves',True))
    parents=[]
    iterations=range(1,r['max_passes']+1) if r.get('max_passes') is not None else itertools.count(1)
    for iteration in iterations:
        # Freeze a small beam for a coarse-to-fine epoch. New discoveries cannot
        # continually displace its champions before they receive finer polls.
        if not parents:
            pool=[e for e in (archive or [initial]) if not states[tuple(e['chords'])]['done']]
            if not pool:return
            parents=frontier_parents(pool,{},r['frontier_parents'],r['improvement_pct']/100) if archive else pool
        next_parents=[]
        for parent in parents:
            state=states[tuple(parent['chords'])];steps=state['steps'][:];tested=[]
            base=[objectives(e['case']) for e in archive]
            pending=[]
            cap=r.get('poll_candidates',0)
            offset=((iteration-1)*(cap or len(poll_directions)))%len(poll_directions)
            for weights,kind in poll_directions[offset:]+poll_directions[:offset]:
                proposed=candidate(parent['chords'],weights,steps,r,valid)
                if proposed is None or tuple(proposed) in visited:continue
                visited.add(tuple(proposed))
                nodes=[i for i,(a,b) in enumerate(zip(parent['chords'],proposed)) if a!=b]
                meta={'job':job,'span_m':span,'seed_family':family,'objective':r['objective'],'search_algorithm':r['search_algorithm'],
                    'pass':iteration,'parent_poll':state['polls']+1,'poll_steps_m':steps[:],'node':nodes,
                    'step_m':max(abs(proposed[i]-parent['chords'][i]) for i in nodes),
                    'parent_case':parent['case'].get('id'),'kind':kind}
                pending.append((proposed,meta))
                if cap and len(pending)>=cap:break
            responses=(yield ('batch',pending)) if r.get('parallel_workers',1)>1 and pending else None
            for index,(proposed,meta) in enumerate(pending):
                if responses is not None:
                    if index>=len(responses):break
                    trial=responses[index]
                else:trial=yield (proposed,meta)
                entry={'case':trial,'chords':proposed,**meta}
                if objectives(trial):tested.append(entry)
                if offer(archive,entry):
                    states[tuple(proposed)]={'steps':steps[:],'polls':0,'done':False}
                    yield ('accepted',event(entry))
            from pareto_poll import hypervolume
            # Compare against the frozen pre-poll archive, independent of order.
            values=base+[objectives(e['case']) for e in tested]
            reference=1.1*max((v[1] for v in values),default=1.)+1e-9
            baseline=hypervolume(base,reference)
            winner=max(tested,key=lambda e:hypervolume([*base,objectives(e['case'])],reference)-baseline,default=None)
            gain=hypervolume([*base,objectives(winner['case'])],reference)-baseline if winner else 0.
            state['polls']+=1
            fine=max(steps)<=r['minimum_step_m']*(1+1e-12)
            state['done']=True
            champion=winner if gain>max(1e-12,baseline*r['improvement_pct']/100) else parent
            if not fine or champion is not parent:
                states[tuple(champion['chords'])]={'steps':[max(r['minimum_step_m'],s*r['shrink_factor']) for s in steps],
                    'polls':state['polls'],'done':False}
                next_parents.append(champion)
        parents=next_parents


def run_search(r,evaluate,on_accept=lambda event:None):
    """Fair interleaving; evaluator owns cache, persistence, and strict budgets."""
    jobs=[]
    for span,family in search_jobs(r):
        g=climb(r,span,len(jobs)+1,family);jobs.append([g,next(g)])
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
    from parallel_cases import run_worker
    return run_worker(model,study)


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
    import catalog_partition
    if catalog_partition.settings(model):return catalog.export(model,browser_url=browser_url)
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
    curve=any(e.get('search_algorithm')=='torque_envelope_search_v5' for e in events)
    if any(e.get('search_algorithm')=='independent_coordinate_v1' for e in events):
        import coordinate_search
        coordinate_search.artifacts(model,study,events)
    elif curve:
        import convergence_report
        convergence_report.write(model,study,events)
    else:
        plt=model.ieee_style();fig,axes=plt.subplots(3,1,figsize=(7.16,6),layout='constrained')
        curve=any(e.get('search_algorithm')=='torque_envelope_search_v5' for e in events)
        plotted=[e for e in events if not curve or e.get('torque_target_nm') is not None]
        for job in sorted({e['job'] for e in plotted}):
            path=[e for e in events if e['job']==job and e['case'].get('status')=='ok']
            x=[e.get('evaluation',i+1) for i,e in enumerate(path)]
            summary=model.read_json(study/'adaptive_summary.json') if (study/'adaptive_summary.json').exists() else {}
            end=summary.get('unique_cases',x[-1] if x else 0)
            keys=['frontier_max_thrust_N','frontier_min_torque_Nm','torque_target_nm' if curve else 'normalized_hypervolume']
            labels=['Best feasible thrust (N)','Winner peak torque (N m)','Available torque (N m)'] if curve else ['Frontier max thrust (N)','Frontier min torque (N m)','Normalized hypervolume']
            for ax,key,label in zip(axes,keys,labels):
                ys=[e.get(key,float('nan')) for e in path]
                ax.plot([*x,end] if x and end>x[-1] else x,[*ys,ys[-1]] if ys and end>x[-1] else ys,marker='.',lw=.8,label=f"J{job}: {path[0]['span_m']:g} m" if path else f'J{job}')
                ax.set_ylabel(label);ax.grid(alpha=.2)
        if len({e['job'] for e in events})<=12:axes[0].legend(fontsize=5,ncol=2)
        axes[-1].set_xlabel('Unique evaluated designs (including cached results)')
        reference=model.read_json(study/'adaptive_hypervolume.json') if (study/'adaptive_hypervolume.json').exists() else {}
        reference_note=(f"\nHV reference: T = 0 N, M = {reference['reference_torque_Nm']:.4g} N m; scales: T = {reference['thrust_scale_N']:.4g} N, M = {reference['torque_scale_Nm']:.4g} N m" if reference else '')
        axes[0].set_title(('Thrust improvement at each available root torque' if curve else 'Pareto exploration · frontier progress at each span')+reference_note,fontsize=8)
        fig.savefig(dest/'adaptive_progress.png',dpi=300);plt.close(fig)
        with (dest/'adaptive_progress.csv').open('w',newline='',encoding='utf-8') as f:
            reference=model.read_json(study/'adaptive_hypervolume.json') if (study/'adaptive_hypervolume.json').exists() else {}
            reference_fields=['reference_thrust_N','reference_torque_Nm','thrust_scale_N','torque_scale_Nm']
            fields=['evaluation','simulations','job','span_m','torque_target_nm','frontier_max_thrust_N','frontier_min_torque_Nm','frontier_size','normalized_hypervolume',*reference_fields]
            writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader()
            writer.writerows({k:reference.get(k) if k in reference_fields else e.get(k) for k in fields} for e in events)
    plt=model.ieee_style();frames=[]
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
