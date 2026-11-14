"""Independent cyclic coordinate differences, remembered signs, one half-step.

Native simulations decide acceptance. Lambda and seed-derived study-wide scales
stay fixed. A failed full step gets exactly one half-step trial, then that chord
is retired for this run even if the half step succeeds. This is a deliberately
bounded local heuristic, not a global or derivative-stationarity certificate.
"""
import csv
import math
import adaptive

ALGORITHM='independent_coordinate_v1'


def loads(row):
    """Permit negative thrust during recovery, but reject failed/unsettled loads."""
    if row.get('status')!='ok' or row.get('simulation_mode')!='isolated_single_wing_v1' or not row.get('cycle_repeatable',False):return None
    t=row.get('single_wing_mean_thrust_N');m=row.get('single_wing_peak_abs_roll_moment_Nm')
    if not all(isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v) for v in (t,m)) or m<0:return None
    return t,m


def score(row,scales,weight):
    value=loads(row)
    return None if value is None else value[0]/scales['thrust_scale_N']-weight*value[1]/scales['torque_scale_Nm']


def move(chords,node,delta,r):
    """Change only this width; clip at neighbors/bounds and snap tiny tips to 0."""
    out=chords[:];b=r['bounds'][node];positive=r['minimum_chord_m']
    lo=b['min_m'];hi=b['max_m'] if b['max_m'] is not None else math.inf
    if r['decreasing']:
        if node:hi=min(hi,out[node-1])
        if node+1<len(out):lo=max(lo,out[node+1])
    # Only the active tip can disappear, and only the next zero can regrow.
    zero=next((i for i,c in enumerate(out) if c==0),len(out))
    if node>zero:return None
    if node<zero-1:lo=max(lo,positive)
    if hi<lo:return None
    value=min(hi,max(lo,out[node]+delta))
    if 0<value<positive:
        value=0. if delta<0 and lo==0 and node>=2 and node==zero-1 else positive
    out[node]=round(value,12)
    return out if out!=chords and adaptive.valid(out,r) else None


def event(r,row,chords,meta,scales):
    t,m=loads(row)
    return {**meta,'accepted':True,'evolution_role':'seed' if meta['kind']=='seed' else 'improvement',
        'case':row,'chords':chords[:],'weighted_score':score(row,scales,r['tradeoff_lambda']),
        'tradeoff_lambda':r['tradeoff_lambda'],**scales,'frontier_case_ids':[row['id']],
        'frontier_size':1,'frontier_max_thrust_N':t,'frontier_min_torque_Nm':m}


def climb(r,span,job,family,initial,scales,score_fn=None):
    """Generator batches only +/- trials of the same parent; never other seeds.

    score_fn(row) -> float|None optionally replaces the lambda score (default unchanged).
    """
    sc=score_fn or (lambda row:score(row,scales,r['tradeoff_lambda']))
    chords,row=initial;directions=[None]*len(chords);finished=[False]*len(chords)
    base={'job':job,'lineage_id':f'seed_{job:03d}','span_m':span,'seed_family':family,
        'objective':r['objective'],'search_algorithm':ALGORITHM}
    yield ('accepted',event(r,row,chords,{**base,'pass':0,'node':None,'step_m':0.,'parent_case':None,'kind':'seed'},scales))
    passes=0
    while not all(finished):
        passes+=1
        for node in range(len(chords)):
            if finished[node]:continue
            step=r['bounds'][node]['step_m'];signs=(1,-1) if directions[node] is None else (directions[node],)
            for refinement in (False,True):
                amount=step*(.5 if refinement else 1);pending=[]
                for sign in signs:
                    proposed=move(chords,node,sign*amount,r)
                    if proposed is None:continue
                    meta={**base,'pass':passes,'node':node,'kind':'half_step' if refinement else 'coordinate',
                        'direction':sign,'step_m':amount,'parent_case':row['id'],
                        'actual_delta_m':proposed[node]-chords[node],'refinement':refinement}
                    pending.append((proposed,meta))
                # Blocked coordinates need no solver or synchronization turn.
                results=(yield ('batch',pending)) if pending else []
                current_score=sc(row);best=None
                for (proposed,meta),trial in zip(pending,results):
                    value=sc(trial)
                    if value is None:continue
                    if value>current_score+r['score_tolerance'] and (best is None or value>best[0]):best=(value,proposed,meta,trial)
                if best:
                    value,proposed,meta,trial=best
                    meta={**meta,'score_change':value-current_score,
                        'directional_score_slope_per_m':(value-current_score)/meta['actual_delta_m']}
                    chords=proposed;row=trial;directions[node]=meta['direction']
                    # A newly exposed tip has a new feasible lower boundary.
                    # Give it a turn even if it stalled behind the old tip.
                    if chords[node]==0 and node>=3:finished[node-1]=False
                    yield ('accepted',event(r,row,chords,meta,scales))
                if refinement:
                    finished[node]=True
                    break
                if best:break  # Next chord, not another step on this chord.
                # No initial winner: test both signs once at half size, then stop.
                # Remembered sign failed: test only that sign at half size.
    return {'job':job,'lineage_id':base['lineage_id'],'span_m':span,'seed_family':family,
        'case_id':row['id'],'passes':passes,'score':sc(row),
        'status':'one_refinement_per_chord_complete','chord_directions':directions}


def run(r,pipeline):
    jobs=adaptive.search_jobs(r);initial=[];states=[];active=[]
    for job,(span,family) in enumerate(jobs,1):
        meta={'job':job,'lineage_id':f'seed_{job:03d}','span_m':span,'seed_family':family,
            'objective':r['objective'],'search_algorithm':ALGORITHM,'pass':0,'node':None,
            'step_m':0.,'parent_case':None,'kind':'seed'}
        initial.append((adaptive.seed(r,family),meta))
    rows=pipeline.evaluate_many(initial);valid=[loads(row) for row in rows if loads(row) is not None]
    if not valid:raise ValueError('No settled seed loads are available. Inspect the native case errors.')
    scales={'thrust_scale_N':max(max(abs(t) for t,m in valid),1e-9),
        'torque_scale_Nm':max(max(m for t,m in valid),1e-9)}
    inherited=bool(r.get('seed_design') and r.get('reference_scales'))
    if inherited:scales=dict(r['reference_scales'])
    pipeline.model.write_json(pipeline.study/'coordinate_objective.json',{
        'algorithm':ALGORITHM,'tradeoff_lambda':r['tradeoff_lambda'],**scales,
        'score_tolerance':r['score_tolerance'],'reference_source':r.get('refinement_source') if inherited else None,
        'note':'Fixed scales inherited from the source study; no torque ceilings.' if inherited else 'Fixed scales from maximum absolute seed thrust and maximum seed torque; no torque ceilings.'})
    for (chords,meta),row in zip(initial,rows):
        state={**meta,'case_id':row['id'],'status':'running' if loads(row) else 'invalid_seed'};states.append(state)
        if loads(row):
            g=climb(r,meta['span_m'],meta['job'],meta['seed_family'],(chords,row),scales)
            active.append((g,next(g),state))
    def save():
        pipeline.model.write_json(pipeline.study/'coordinate_lineages.json',{'algorithm':ALGORITHM,'lineages':states})
    while active:
        waiting=[]
        for g,pending,state in active:
            try:
                while pending[0]=='accepted':
                    pipeline.accept(pending[1]);state.update(case_id=pending[1]['case']['id'],score=pending[1]['weighted_score'],passes=pending[1]['pass'])
                    pending=next(g)
                waiting.append((g,pending,state))
            except StopIteration as done:state.update(done.value or {})
        save();active=[]
        if pipeline.stop_reason:
            for g,pending,state in waiting:state['status']='budget_reached'
            save();raise adaptive.BudgetReached(pipeline.stop_reason)
        combined=[];indices=[]
        for g,pending,state in waiting:
            start=len(combined);combined.extend(pending[1]);indices.append((start,len(combined)))
        returned=pipeline.evaluate_many(combined) if combined else []
        for (g,pending,state),(start,end) in zip(waiting,indices):
            if end>len(returned):state['status']='budget_reached';continue
            try:active.append((g,g.send(returned[start:end]),state))
            except StopIteration as done:state.update(done.value or {})
        save()
    if pipeline.stop_reason:raise adaptive.BudgetReached(pipeline.stop_reason)


def artifacts(model,study,events):
    """Readable per-lineage progress with fixed score scales, plus measured CSV."""
    dest=study/'comparisons';dest.mkdir(exist_ok=True)
    fields=['job','seed_family','span_m','evaluation','pass','node','kind','step_m','weighted_score',
        'score_change','directional_score_slope_per_m','case','mean_thrust_N','peak_root_torque_Nm']
    with (dest/'adaptive_progress.csv').open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
        for e in events:w.writerow({**{k:e.get(k) for k in fields if k not in ('case','mean_thrust_N','peak_root_torque_Nm')},
            'case':e['case']['id'],'mean_thrust_N':loads(e['case'])[0],'peak_root_torque_Nm':loads(e['case'])[1]})
    plt=model.ieee_style();fig,axes=plt.subplots(3,1,figsize=(7.16,6),layout='constrained')
    for job in sorted({e['job'] for e in events}):
        path=[e for e in events if e['job']==job];x=list(range(len(path)))
        label=f"{job}: {path[0]['seed_family']} / {path[0]['span_m']:g} m start"
        for ax,key in zip(axes,('weighted_score','thrust','torque')):
            y=[e['weighted_score'] if key=='weighted_score' else loads(e['case'])[0 if key=='thrust' else 1] for e in path]
            ax.plot(x,y,marker='.',lw=.8,label=label);ax.grid(alpha=.2)
    for ax,label in zip(axes,('Weighted score','Mean thrust (N)','Peak root torque (N m)')):ax.set_ylabel(label)
    axes[0].set_title('Independent seed evolution · accepted changes only; no global convergence claim',fontsize=9)
    axes[0].legend(fontsize=5,ncol=3);axes[-1].set_xlabel('Accepted evolution step within each seed')
    fig.savefig(dest/'adaptive_progress.png',dpi=300);plt.close(fig)
