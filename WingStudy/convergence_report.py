"""Measured search progress; never infer convergence from a budget stop."""
import csv
import math
from collections import defaultdict

THRUST='single_wing_mean_thrust_N'


def analyze(events,results,targets,options):
    paths=defaultdict(list)
    for e in events:
        if e.get('torque_target_nm') is not None:paths[e['job']].append(e)
    end=len(results);cutoff=.8*end;records=[]
    seed_end=max((e.get('evaluation',0) for e in events if e.get('kind')=='seed'),default=0)
    for job,path in sorted(paths.items()):
        start=path[0];last=path[-1];initial=start['case'][THRUST];final=last['case'][THRUST]
        previous=next((e['case'][THRUST] for e in reversed(path) if e.get('evaluation',0)<=cutoff),None)
        records.append({'job':job,'reference_total_span_m':start['span_m'],'available_root_torque_Nm':start['torque_target_nm'],
            'baseline':'seed' if start.get('evaluation',0)<=seed_end else 'first_feasible',
            'baseline_thrust_N':initial,'final_thrust_N':final,'gain_pct':100*(final/initial-1),
            'last_20pct_gain_pct':100*(final/previous-1) if previous is not None else None,
            'selected_updates':len(path)-1,'last_update_evaluation':last.get('evaluation',0),
            'monotone_thrust':all(b['case'][THRUST]>=a['case'][THRUST]-1e-12 for a,b in zip(path,path[1:])),
            'case_id':last['case']['id']})
    trials=[r for r in results if r.get('adaptive_trial',{}).get('poll_steps_m')]
    minimum=options.get('minimum_step_m',.01)
    fine=sum(max(r['adaptive_trial']['poll_steps_m'])<=minimum*(1+1e-12) for r in trials)
    return {'records':records,'paths':dict(paths),'evaluated_cases':end,'trial_cases':len(trials),
        'fine_trial_cases':fine,'minimum_nominal_step_m':min((max(r['adaptive_trial']['poll_steps_m']) for r in trials),default=None),
        'requested_minimum_step_m':minimum,'target_count':len(targets),
        'exhausted_targets':sum(bool(t.get('local_search_exhausted')) for t in targets),
        'unique_winners':len({t['case_id'] for t in targets if t.get('case_id')})}


def write(model,study,events,basename='adaptive_progress'):
    results=model.read_json(study/'results.json') if (study/'results.json').exists() else []
    targets=model.read_json(study/'torque_targets.json').get('targets',[]) if (study/'torque_targets.json').exists() else []
    manifest=model.read_json(study/'manifest.json');summary=model.read_json(study/'adaptive_summary.json') if (study/'adaptive_summary.json').exists() else {}
    data=analyze(events,results,targets,manifest['adaptive_search']);records=data['records']
    dest=study/'comparisons';dest.mkdir(exist_ok=True)
    fields=['job','reference_total_span_m','available_root_torque_Nm','baseline','baseline_thrust_N','final_thrust_N','gain_pct',
        'last_20pct_gain_pct','selected_updates','last_update_evaluation','monotone_thrust','case_id']
    with (dest/(basename+'.csv')).open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(records)
    spans=sorted({r['reference_total_span_m'] for r in records}) or [None]
    cols=min(3,len(spans));blocks=math.ceil(len(spans)/cols)
    plt=model.ieee_style();fig,axes=plt.subplots(2*blocks,cols,figsize=(3.58*cols,(6. if cols==1 else 4.8)*blocks),squeeze=False)
    for i,span in enumerate(spans):
        top=axes[2*(i//cols),i%cols];bottom=axes[2*(i//cols)+1,i%cols]
        group=[r for r in records if r['reference_total_span_m']==span]
        collapsed={}
        for r in group:
            path=data['paths'][r['job']]
            key=tuple((e.get('evaluation',0),e['case']['id'],e['case'][THRUST]) for e in path)
            collapsed.setdefault(key,[]).append(r)
        colors=plt.get_cmap('viridis')
        for j,(key,aliases) in enumerate(collapsed.items()):
            path=data['paths'][aliases[0]['job']];base=aliases[0]['baseline_thrust_N']
            x=[e.get('evaluation',0) for e in path];y=[100*(e['case'][THRUST]/base-1) for e in path]
            if x and x[-1]<len(results):x.append(len(results));y.append(y[-1])
            top.step(x,y,where='post',color=colors(j/max(1,len(collapsed)-1)),lw=1.,
                linestyle='--' if aliases[0]['baseline']=='first_feasible' else '-')
        top.set_title(f'{span:g} m reference total span' if span is not None else 'No feasible target history',fontsize=9)
        top.set(xlabel='Unique evaluated designs',ylabel='Thrust gain from baseline (%)');top.grid(alpha=.2)
        top.text(.03,.96,f'{len(group)} targets / {len(collapsed)} distinct histories',transform=top.transAxes,va='top',fontsize=7)
        for r in group:
            late=r['last_20pct_gain_pct'];bottom.scatter(r['available_root_torque_Nm'],r['gain_pct'],
                color='#0072b2' if late is not None and late<.5 else '#d55e00',s=15,
                marker='o' if r['baseline']=='seed' else '^')
        bottom.set(xlabel='Available root torque (N m)',ylabel='Final thrust gain (%)');bottom.grid(alpha=.2)
    for i in range(len(spans),blocks*cols):
        axes[2*(i//cols),i%cols].set_visible(False);axes[2*(i//cols)+1,i%cols].set_visible(False)
    reason=summary.get('stop_reason','Search in progress')
    fig.suptitle('Search progress: measured improvement\nConvergence is not certified' if cols==1 else
        'Search audit: measured improvement; convergence is not certified',fontsize=9 if cols==1 else 11)
    note=(f"{reason}. {data['evaluated_cases']} unique cases; {data['fine_trial_cases']}/{data['trial_cases']} trials at the requested minimum adjustment. "
        f"{data['exhausted_targets']}/{data['target_count']} local searches exhausted.\n"
        'Solid: gain versus best feasible seed; dashed / triangles: first feasible sample. Duplicate histories collapsed. '
        'Orange: >=0.5% late gain, or no earlier feasible baseline; blue: <0.5% late gain.\n'
        'Late gain uses the final 20% of evaluated cases. Flat traces do not establish a global optimum or solver/mesh convergence.')
    fig.text(.02,.015,note,fontsize=6.5,va='bottom',wrap=True)
    fig.tight_layout(rect=(0,.27 if cols==1 else .15,1,.95));fig.savefig(dest/(basename+'.png'),dpi=300);plt.close(fig)
    return data
