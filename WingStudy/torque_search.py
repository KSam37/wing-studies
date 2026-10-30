"""Shared-sample, multi-start local searches of max thrust subject to M <= Q.

Q is swept across a range. It is not a single hardware cutoff. Native Ptera
physics and simulation identity are unchanged; only candidate selection changes.
"""
import csv
import math
import adaptive
from pareto_poll import candidate, directions

ALGORITHM='torque_envelope_search_v5'


def best(samples,span,target):
    feasible=[s for s in samples if s['span']==span and adaptive.objectives(s['row']) is not None
        and adaptive.objectives(s['row'])[1]<=target]
    return max(feasible,key=lambda s:(adaptive.objectives(s['row'])[0],-adaptive.objectives(s['row'])[1]),default=None)


def target_levels(r,samples):
    values=[adaptive.objectives(s['row'])[1] for s in samples if adaptive.objectives(s['row']) is not None]
    if not values:raise ValueError('No repeatable positive-thrust seed results; inspect case errors and settling before searching.')
    low=r.get('curve_torque_min_nm');high=r.get('curve_torque_max_nm')
    low=max(1e-9,min(values)*.5) if low is None else low
    high=max(low*1.1,max(values)*1.25) if high is None else high
    return adaptive.levels(low,high,r['curve_torque_samples'])


def poll_directions(parent,samples,r,steps):
    """Coordinates plus opposite-sign redistribution, optionally torque-balanced.

    Fit local torque sensitivities only when a full-rank neighborhood exists.
    The linear fit proposes moves; every move still requires a native solve.
    """
    import numpy as np
    n=len(parent['chords']);vectors=directions(n,r['paired_moves'],r.get('coordinated_moves',True))
    nearby=[]
    for s in samples:
        if s['span']!=parent['span'] or adaptive.objectives(s['row']) is None:continue
        dx=np.asarray(s['chords'])-parent['chords']
        distance=float(np.linalg.norm(dx/np.maximum(steps,1e-12)))
        if 1e-9<distance<=3:nearby.append((distance,dx,adaptive.objectives(s['row'])[1]-adaptive.objectives(parent['row'])[1]))
    nearby.sort(key=lambda item:item[0]);nearby=nearby[:max(3*n,16)]
    gradient=None
    if len(nearby)>=n:
        matrix=np.array([x[1] for x in nearby])
        if np.linalg.matrix_rank(matrix)==n:gradient=np.linalg.lstsq(matrix,np.array([x[2] for x in nearby]),rcond=None)[0]
    redistribution=[]
    for i in range(n):
        for j in range(i+1,n):
            ratio=1.
            if gradient is not None and abs(gradient[j])>1e-10:
                fitted=gradient[i]*steps[i]/(gradient[j]*steps[j])
                if fitted>0 and math.isfinite(float(fitted)):ratio=float(fitted)
            for sign in (1.,-1.):
                v=[0.]*n;scale=max(1.,ratio);v[i]=sign/scale;v[j]=-sign*ratio/scale
                redistribution.append((tuple(v),'torque_balanced' if gradient is not None else 'redistribute'))
    # Give redistributions guaranteed early turns, including when the optional
    # legacy coordinated-moves checkbox is off. They are central to this method.
    out=[];seen=set()
    for i in range(max(len(vectors),len(redistribution))):
        for group in (vectors,redistribution):
            if i<len(group) and group[i][0] not in seen:seen.add(group[i][0]);out.append(group[i])
    return out


def event(r,sample,job,target,parent=None,kind='winner'):
    row=sample['row'];t,m=adaptive.objectives(row)
    return {'accepted':True,'evolution_role':'seed' if kind=='seed' else 'improvement',
        'case':row,'chords':sample['chords'],'job':job,'span_m':sample['span'],
        'seed_family':row.get('seed_family','historical'),'objective':r['objective'],
        'search_algorithm':ALGORITHM,'torque_target_nm':target,'parent_case':parent,
        'kind':kind,'pass':sample.get('pass',0),'node':None,'step_m':0.,
        'frontier_case_ids':[row['id']],'frontier_size':1,'frontier_max_thrust_N':t,'frontier_min_torque_Nm':m}


def save_targets(model,study,states,samples):
    rows=[]
    for state in states:
        winner=best(samples,state['span'],state['target']);row=winner['row'] if winner else {}
        values=adaptive.objectives(row)
        rows.append({'job':state['job'],'span_m':state['span'],'available_root_torque_Nm':state['target'],
            'case_id':row.get('id'),'mean_thrust_N':values[0] if values else None,
            'peak_root_torque_Nm':values[1] if values else None,
            'status':'best_observed' if winner else 'no_feasible_sample',
            'local_search_exhausted':state['done']})
    model.write_json(study/'torque_targets.json',{'algorithm':ALGORITHM,'targets':rows,
        'note':'Best observed feasible designs at sampled available torques; not certified global optima.'})
    path=study/'comparisons/torque_curve.csv';path.parent.mkdir(exist_ok=True)
    with path.open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]) if rows else []);w.writeheader();w.writerows(rows)


def run(r,pipeline):
    samples=[];requested=set();initial=[]
    for i,(span,family) in enumerate(adaptive.search_jobs(r),1):
        chords=adaptive.seed(r,family)
        meta={'job':-i,'span_m':span,'seed_family':family,'objective':r['objective'],
            'search_algorithm':ALGORITHM,'pass':0,'kind':'seed','node':None,'step_m':0.,'parent_case':None}
        initial.append((chords,meta))
    returned=pipeline.evaluate_many(initial)
    for (chords,meta),row in zip(initial,returned):
        s={'row':row,'chords':chords,'span':meta['span_m'],'seed':True}
        samples.append(s);requested.add((s['span'],tuple(chords)))
        if adaptive.objectives(row):pipeline.accept(event(r,s,meta['job'],None,kind='seed'))
    if not any(adaptive.objectives(s['row']) for s in samples):
        if pipeline.stop_reason:raise adaptive.BudgetReached(pipeline.stop_reason)
        raise ValueError('No valid seeds. Inspect native solve and repeatability results.')
    targets=target_levels(r,samples);states=[]
    for span in adaptive.levels(r['span_min_m'],r['span_max_m'],r['span_count']):
        for q in targets:
            states.append({'job':len(states)+1,'span':span,'target':q,'last':None,'anchor':None,
                'steps':[b['step_m'] for b in r['bounds']],'offset':0,'visited':set(),'done':False,'pass':0})
    def update():
        for state in states:
            winner=best(samples,state['span'],state['target'])
            if winner and (state['last'] is None or winner['row']['id']!=state['last']['row']['id']):
                pipeline.accept(event(r,winner,state['job'],state['target'],state['last']['row']['id'] if state['last'] else None))
                state.update(last=winner,anchor=winner,offset=0,done=False)
        save_targets(pipeline.model,pipeline.study,states,samples)
    update()
    if pipeline.stop_reason:raise adaptive.BudgetReached(pipeline.stop_reason)
    while any(not s['done'] for s in states):
        groups=[]
        for state in states:
            if state['done']:continue
            if state['anchor'] is None:
                choices=[s for s in samples if s['span']==state['span'] and adaptive.objectives(s['row'])
                    and s['row']['id'] not in state['visited'] and (s.get('seed') or s is state['last'])]
                if not choices:state['done']=True;continue
                feasible=[s for s in choices if adaptive.objectives(s['row'])[1]<=state['target']]
                anchor=max(feasible,key=lambda s:adaptive.objectives(s['row'])[0]) if feasible else min(choices,key=lambda s:adaptive.objectives(s['row'])[1])
                state.update(anchor=anchor,offset=0,steps=[b['step_m'] for b in r['bounds']])
            anchor=state['anchor'];state['pass']+=1
            basis=poll_directions(anchor,samples,r,state['steps']);start=state['offset'];cap=8
            block=basis[start:start+cap];state['offset']+=len(block);pending=[]
            for weights,kind in block:
                chords=candidate(anchor['chords'],weights,state['steps'],r,adaptive.valid)
                if chords is None or (state['span'],tuple(chords)) in requested:continue
                meta={'job':state['job'],'span_m':state['span'],'seed_family':anchor['row'].get('seed_family','triangle'),
                    'objective':r['objective'],'search_algorithm':ALGORITHM,'torque_target_nm':state['target'],
                    'pass':state['pass'],'kind':kind,'node':[i for i,(a,b) in enumerate(zip(chords,anchor['chords'])) if a!=b],
                    'step_m':max(abs(a-b) for a,b in zip(chords,anchor['chords'])),'poll_steps_m':state['steps'][:],
                    'parent_case':anchor['row']['id']}
                pending.append((chords,meta))
            groups.append(pending)
            if state['offset']>=len(basis):
                if max(state['steps'])<=r['minimum_step_m']*(1+1e-12):
                    state['visited'].add(anchor['row']['id']);state['anchor']=None
                else:state['steps']=[max(r['minimum_step_m'],s*r['shrink_factor']) for s in state['steps']]
                state['offset']=0
        # Interleave targets and deduplicate before planning native simulations.
        inputs=[]
        for i in range(max(map(len,groups),default=0)):
            for group in groups:
                if i>=len(group):continue
                chords,meta=group[i];key=(meta['span_m'],tuple(chords))
                if key in requested:continue
                requested.add(key);inputs.append((chords,meta))
        if inputs:
            chunk_size=max(1,r.get('parallel_workers',1)*2)
            for start in range(0,len(inputs),chunk_size):
                chunk=inputs[start:start+chunk_size];returned=pipeline.evaluate_many(chunk)
                for (chords,meta),row in zip(chunk,returned):
                    samples.append({'row':row,'chords':chords,'span':meta['span_m'],'pass':meta['pass']})
                update()
                if pipeline.stop_reason:raise adaptive.BudgetReached(pipeline.stop_reason)
        # Feasibility restoration: infeasible anchors may move toward lower
        # torque even if thrust falls; they never become feasible winners early.
        for state in states:
            if state['last'] is not None:continue
            choices=[s for s in samples if s['span']==state['span'] and adaptive.objectives(s['row'])]
            if choices:
                lower=min(choices,key=lambda s:adaptive.objectives(s['row'])[1])
                if state['anchor'] and adaptive.objectives(lower['row'])[1]<adaptive.objectives(state['anchor']['row'])[1]:state.update(anchor=lower,offset=0)
        update()
        if pipeline.stop_reason:raise adaptive.BudgetReached(pipeline.stop_reason)
    save_targets(pipeline.model,pipeline.study,states,samples)
