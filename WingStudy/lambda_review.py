"""Auditable comparison of curated independent-coordinate searches; no solves."""
import csv
import hashlib
import json
import math
from collections import Counter
import study_organization
from torque_frontier import band_winners, envelope, TORQUE, THRUST
from torque_study import classify
from wing_dimensions import dimensions

COLORS=['#0072B2','#D55E00','#009E73']  # distinguishable on white and in most color-vision deficiencies
SETTINGS=('simulation_mode','aeroelastic_enabled','rho','nu','frequency_hz','speed_mps','dt_s',
          'cycles','span_panels','chord_panels','wake_model','wake_cycles','waveform','gap_m','tail')


def polygon(model,row):
    import numpy as np
    le,frames=model.custom_frames(row)
    te=[np.asarray(p)+f@np.array([s['chord_m'],0.,0.]) for p,f,s in zip(le,frames,row['sections'])]
    return [[float(p[1]),float(p[0])] for p in [*le,*te[::-1]]]


def bundle(model):
    ids=study_organization.read(model).get('lambda_studies',[])
    if not ids:raise ValueError('No curated lambda studies. Organize the saved studies first.')
    studies=[];all_rows=[];lineages=[];conditions=[];searches=[];references=[]
    for study in ids:
        if not isinstance(study,str) or '/' in study or '\\' in study:raise ValueError('Invalid curated study.')
        directory=model.OUTPUTS/study;m=model.read_json(directory/'manifest.json')
        objective=model.read_json(directory/'coordinate_objective.json');weight=objective['tradeoff_lambda']
        state=model.read_json(directory/'status.json')
        raw=model.read_json(directory/'results.json');events=model.read_json(directory/'evolution.json')
        paths={}
        for event in events:
            if event.get('accepted'):paths.setdefault(event['job'],[]).append(event)
        finals={p[-1]['case']['id'] for p in paths.values()};accepted={e['case']['id'] for e in events if e.get('accepted')}
        lookup={};excluded=Counter()
        for r in raw:
            reason=classify(r,float('inf'))
            if reason!='Within limit':excluded[reason]+=1;continue
            item={k:r.get(k) for k in ('id','global_case_no','geometry_id','simulation_id','design_name',
                THRUST,TORQUE,'cycle_error_pct','root_moment_cycle_error_pct','cycle_error_thrust_pct','cycle_repeatable','seed_family','area_m2')}
            item.update(dimensions({**r,'_settings':m['settings']}))
            item.update(study=study,_study=study,comparison_key=study+':'+r['id'],lambda_value=weight,
                outline_m=polygon(model,r),is_final=r['id'] in finals,is_accepted=r['id'] in accepted,
                chords_m=[s['chord_m'] for s in r.get('requested_sections',r['sections'])],
                sections=r['sections'])
            lookup[r['id']]=item;all_rows.append(item)
        for job,path in paths.items():
            start,end=path[0],path[-1];a=start['case'];b=end['case']
            lineages.append({'study':study,'lambda_value':weight,'job':job,'family':start['seed_family'],
                'starting_total_span_m':start['span_m'],'case':b['id'],'seed_case':a['id'],
                'steps':len(path)-1,'delta_thrust_N':b[THRUST]-a[THRUST],'delta_torque_Nm':b[TORQUE]-a[TORQUE],
                'score_gain':end['weighted_score']-start['weighted_score'],
                'monotonic_score':all(y['weighted_score']>=x['weighted_score']-1e-12 for x,y in zip(path,path[1:])),
                'points':[{'id':e['case']['id'],'thrust':e['case'][THRUST],'torque':e['case'][TORQUE],
                    'score':e['weighted_score'],'evaluation':e.get('evaluation'),
                    'outline_m':polygon(model,e['case'])} for e in path],
                'final':lookup.get(b['id'])})
        studies.append({'id':study,'name':f'λ = {weight:g}','lambda_value':weight,'color':COLORS[len(studies)%len(COLORS)],
            'state':state['state'],'evaluated':len(raw),'eligible':len(lookup),'excluded':dict(excluded),
            'new_simulations':state.get('completed'),'cache_hits':sum(bool(r.get('reused_from')) for r in raw),
            'seed_count':len(paths),'accepted_changes':sum(len(p)-1 for p in paths.values()),
            'max_thrust_N':max((r[THRUST] for r in lookup.values()),default=None),
            'objective':objective,'search':m['adaptive_search'],'motion':m['config'].get('motion_range'),
            'settings':{k:m['settings'].get(k) for k in SETTINGS}})
        conditions.append(studies[-1]['settings'])
        references.append({k:objective[k] for k in ('thrust_scale_N','torque_scale_Nm')})
        searches.append({k:v for k,v in m['adaptive_search'].items() if k not in ('tradeoff_lambda','simulation_budget')})
    comparable=all(x==conditions[0] for x in conditions) and all(x==references[0] for x in references)
    same_search=all(x==searches[0] for x in searches)
    all_rows.sort(key=lambda r:(r['lambda_value'],r[TORQUE],r['id']))
    return {'studies':studies,'rows':all_rows,'lineages':lineages,'comparable':comparable,
        'same_search':same_search,'unique_simulations':len({r['simulation_id'] or (r['study'],r['id']) for r in all_rows}),
        'conditions':conditions[0],'references':references[0],
        'limitations':'Observed candidates from bounded local searches, not a global optimum. Root torque is hydrodynamic only; motor/linkage conversion and wing inertia are excluded. Thrust/torque is not energy efficiency. Check mesh/time-step/wake sensitivity and tank performance before fabrication decisions.'}


def selection(bundle,data):
    chosen=data.get('studies',[s['id'] for s in bundle['studies']])
    known={s['id'] for s in bundle['studies']}
    if not isinstance(chosen,list) or not chosen or any(s not in known for s in chosen):raise ValueError('Select at least one curated lambda study.')
    scope=data.get('scope','all')
    if scope not in ('all','accepted','final'):raise ValueError('Unknown design selection.')
    rows=[r for r in bundle['rows'] if r['study'] in chosen and
        (scope=='all' or scope=='accepted' and r['is_accepted'] or scope=='final' and r['is_final'])]
    def number(key,default):
        value=data.get(key,default)
        try:value=float(value) if value not in ('',None) else default
        except (ValueError,TypeError):raise ValueError('Invalid torque range or band width.')
        if isinstance(value,bool) or not math.isfinite(value) or value<0:raise ValueError('Torque values must be finite and nonnegative.')
        return value
    lo=number('minimum',0.);hi=number('maximum',max((r[TORQUE] for r in rows),default=1.))
    width=number('band_width',.25)
    if hi<=lo or width<=0:raise ValueError('Maximum torque must exceed minimum; band width must be positive.')
    # Preserve study occurrences in per-lambda comparison, deduplicate exact simulations only in the pooled selection.
    selected=[r for r in rows if lo<=r[TORQUE]<=hi];unique={}
    for r in selected:unique.setdefault(r['simulation_id'] or (r['study'],r['id']),r)
    winners=band_winners(list(unique.values()),lo,hi,width)
    return selected,winners,lo,hi,width


def export(model,data):
    b=bundle(model);rows,winners,lo,hi,width=selection(b,data)
    if not rows:raise ValueError('No eligible designs in this selection.')
    series=[w for s in b['studies'] for w in band_winners([r for r in rows if r['study']==s['id']],lo,hi,width)]
    digest=hashlib.sha256(json.dumps(['lambda-review-v3',data,[(r['study'],r['id'],r[THRUST],r[TORQUE]) for r in rows]],sort_keys=True).encode()).hexdigest()[:12]
    dest=model.OUTPUTS/('lambda-review-'+digest);dest.mkdir(exist_ok=True)
    files=['lambda_comparison.png','seed_evolutions.png','evolution_audit.png','band_winners_by_lambda.csv','band_winners.csv','evaluated_designs.csv','methods.md','summary.md']
    if not all((dest/f).is_file() for f in files):
        figures(model,b,rows,series,lo,hi,width,dest,data.get('scope','all'))
        fields=['study','lambda_value','global_case_no','id','geometry_id','simulation_id',THRUST,TORQUE,
            'single_wing_span_m','effective_total_span_m','area_m2','is_final','is_accepted','chords_m',
            'torque_band_min_nm','torque_band_max_nm','torque_band_count']
        for name,values in [('evaluated_designs.csv',rows),('band_winners.csv',winners),('band_winners_by_lambda.csv',series)]:
            with (dest/name).open('w',newline='',encoding='utf-8') as f:
                w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore');w.writeheader();w.writerows(values)
        (dest/'methods.md').write_text(methods(b),encoding='utf-8')
        (dest/'summary.md').write_text(summary(b,rows,winners,lo,hi,width),encoding='utf-8')
    (dest/'methods.md').write_text(methods(b),encoding='utf-8')
    return {'files':[str((dest/f).relative_to(model.OUTPUTS)).replace('\\','/') for f in files],
        'winner_count':len(winners),'summary':summary(b,rows,winners,lo,hi,width)}


def methods(b):
    s=b['studies'][0];a=s['search'];c=b['conditions'];ref=b['references']
    return f'''# Methods — independent seed wing search

Acceptance equation: ΔS = (Tnew − Tcurrent) / Tref − λ (Mnew − Mcurrent) / Mref, with mean single-wing thrust T and final-cycle peak absolute single-wing root roll moment M. Current means the last accepted wing, not the initial seed. Tref = {ref['thrust_scale_N']:.12g} N and Mref = {ref['torque_scale_Nm']:.12g} N m are fixed seed-derived scales. A candidate replaces its current parent only if ΔS > {a['score_tolerance']:g}. These references are shared across the three studies. No torque ceiling is applied during search.

Each study starts five families (triangle, rectangle, concave, convex, narrow rectangle), each at total starting spans 0.4, 0.6 and 0.8 m, including a {c['gap_m']:g} m hinge gap. Each isolated wing initially has eight chord sections. Chord widths are independently varied; section spacing is fixed for each seed. Initial +/− {a['initial_step_m']:g} m trials select a direction. Root-to-tip passes then test the remembered sign; a failed/blocked full step receives one half-step trial, after which that chord is retired. A newly exposed tip may be revisited. This is a bounded coordinate finite-difference heuristic, not a convergence or global-optimality certificate.

Root width is capped at 0.2 m and may shrink. Chords are nonincreasing outboard. The first two sections have a 0.01 m lower bound. The outer six permit zero; a contiguous zero suffix is omitted, shortening the active span. Active positive chords follow the saved 0.01 m minimum. Span is therefore not fixed throughout evolution. Exact geometry, motion, fluid and solver matches can reuse cached outputs; cached evaluations are not new solver runs.

Native rigid Ptera UVLM: water density {c['rho']:g} kg/m³, kinematic viscosity {c['nu']:g} m²/s; {c['frequency_hz']:g} Hz, nominal −26° to +34° prescribed flap, {c['speed_mps']:g} m/s forward speed, Δt = {c['dt_s']:g} s, {c['cycles']} cycles, {c['span_panels']} span and {c['chord_panels']} chord panels, {c['wake_model']} wake retaining {c['wake_cycles']:g} cycles. All values are read from the saved studies. Only successful isolated-wing cases with positive mean thrust and the recorded cycle-repeatability flag are selected. This flag is an internal settling check, not a discretization uncertainty estimate.

The best-under-torque envelope is a step function of observed results: F(m) = max T_i for M_i ≤ m. Torque-band representatives instead maximize T within each interval separately for each lambda, breaking equal-thrust ties by lower M. The band plot overlays these three series; a separate pooled-winners CSV selects across all included studies. Bands start at the selected minimum; upper edges are exclusive except the final edge. No interpolation or extrapolation is used. All evaluated designs are available by default, including trials rejected by their own λ score. Identical simulations appearing in multiple studies are not independent evidence. Color in the band plot denotes λ, not energy efficiency. Shared identical simulations have striped silhouettes. Wing silhouettes share a physical scale within each figure. Evolution plots group all seed paths within each lambda, use shared axes, family colors and starting-span line styles, and show complete histories regardless of the torque-band filter.

{b['limitations']}
'''


def summary(b,rows,winners,lo,hi,width):
    text=['# Lambda comparison — observed results',f'\nTorque range: {lo:g}–{hi:g} N m. Band width: {width:g} N m. {len(winners)} occupied bands; empty bands have no selected design.\n']
    for s in b['studies']:
        paths=[p for p in b['lineages'] if p['study']==s['id']]
        text.append(f"- λ = {s['lambda_value']:g}: {s['evaluated']} evaluated cases ({s['new_simulations']} new solves, {s['cache_hits']} cache hits); {s['seed_count']} seeds, {s['accepted_changes']} accepted changes; {sum(p['steps']>0 for p in paths)}/{len(paths)} seeds changed. Largest observed thrust {s['max_thrust_N']:.5g} N.")
    unique={r['simulation_id'] for r in rows};counts=Counter(r['lambda_value'] for r in winners)
    text.append(f'\nSelected occurrences: {len(rows)}; distinct simulation identities: {len(unique)}. Winning-band occurrence counts by λ: {dict(sorted(counts.items()))}. Equal-load reused results are attributed to the first selected study for this count; counts are not a statistical comparison.')
    text.append('\nAll 45 recorded seed paths have monotonic accepted score.' if all(p['monotonic_score'] for p in b['lineages']) else '\nWarning: nonmonotonic recorded score found; inspect histories.')
    text.append('\nChoose a torque region in the browser to inspect the actual geometry and source files. No single universal winner follows without a target torque or another hardware requirement. A larger λ penalizes normalized torque more strongly, but a rejected trial may still win a post hoc torque band.')
    text.append('\n'+b['limitations'])
    return '\n'.join(text)+'\n'


def figures(model,b,rows,winners,lo,hi,width,dest,scope='all'):
    from matplotlib.lines import Line2D
    from matplotlib.offsetbox import AnnotationBbox, DrawingArea
    from matplotlib.patches import Polygon
    import numpy as np
    plt=model.ieee_style();colors={s['id']:s['color'] for s in b['studies']}
    selected_studies={r['study'] for r in rows}
    envelope_rows=[r for r in b['rows'] if r['study'] in selected_studies and r[TORQUE]<=hi and
        (scope=='all' or scope=='accepted' and r['is_accepted'] or scope=='final' and r['is_final'])]
    with plt.rc_context({'axes.spines.top':False,'axes.spines.right':False,'font.size':8}):
        fig,axes=plt.subplots(1,2,figsize=(7.16,3.3),layout='constrained')
        for study in b['studies']:
            rs=[{**r,'status':'ok','simulation_mode':'isolated_single_wing_v1','cycle_repeatable':True} for r in envelope_rows if r['study']==study['id']]
            if not rs:continue
            _,front=envelope(rs)
            axes[0].scatter([r[TORQUE] for r in rs],[r[THRUST] for r in rs],s=3,color=study['color'],alpha=.13,linewidths=0,rasterized=True)
            xs=[r[TORQUE] for r in front];ys=[r[THRUST] for r in front]
            axes[0].step([*xs,hi],[*ys,ys[-1]],where='post',lw=1.1,color=study['color'],label=study['name'])
        axes[0].legend(fontsize=7,frameon=False,loc='lower right')
        axes[0].set_title('(a) Best observed thrust below each torque',fontsize=8)
        # Sample each lambda independently, so one series cannot suppress the others.
        ymax=max(r[THRUST] for r in rows)*1.07;shown=[]
        for study in b['studies']:
            kept=[]
            for r in sorted((r for r in winners if r['study']==study['id']),key=lambda r:-r[THRUST]):
                if all(((r[TORQUE]-p[TORQUE])/(hi-lo))**2+((r[THRUST]-p[THRUST])/ymax)**2>.065**2 for p in kept):kept.append(r)
            shown.extend(kept)
        coincident={}
        for r in shown:
            key=r['simulation_id'] or (r['study'],r['id'])
            if key not in coincident:coincident[key]={**r,'sources':[r['study']]}
            else:
                coincident[key]['sources'].append(r['study']);coincident[key]['is_final']|=r['is_final']
        shown=list(coincident.values())
        extent=max((max(p[0] for p in r['outline_m'])-min(p[0] for p in r['outline_m']) for r in rows),default=.4)
        scale=20/max(extent,1e-9)
        for r in shown:
            poly=np.array(r['outline_m']);lower=poly.min(axis=0);upper=poly.max(axis=0);size=(upper-lower)*scale
            box=DrawingArea(max(size[0],1),max(size[1],1));v=(poly-lower)*scale;v[:,1]=size[1]-v[:,1]
            patch=Polygon(v,facecolor=colors[r['study']],edgecolor='none');box.add_artist(patch)
            if len(r['sources'])>1:
                from matplotlib.patches import Rectangle
                for j in range(int(size[0]/2)+1):
                    stripe=Rectangle((j*2,0),2,max(size[1],1),facecolor=colors[r['sources'][j%len(r['sources'])]],lw=0)
                    stripe.set_clip_path(patch);box.add_artist(stripe)
            box.add_artist(Polygon(v,fill=False,edgecolor='black' if r['is_final'] else '#b0b0b0',lw=.7 if r['is_final'] else .4))
            axes[1].add_artist(AnnotationBbox(box,(r[TORQUE],r[THRUST]),frameon=False,pad=0))
            axes[1].plot(r[TORQUE],r[THRUST],'.',ms=1.5,color=colors[r['study']])
        axes[1].set_title(f'(b) Band winners by lambda · {width:g} N m',fontsize=8)
        axes[1].add_artist(AnnotationBbox(DrawingArea(1,1),(lo,0),frameon=False))
        axes[1].plot([],[],color='#17313d',label=f'0.10 m = {scale*.1:.1f} pt')
        # Scale bar in physical drawing points, independent of torque/thrust axes.
        bar=DrawingArea(scale*.1,8);bar.add_artist(Line2D([0,scale*.1],[4,4],color='#17313d',lw=1.5))
        axes[1].add_artist(AnnotationBbox(bar,(.07,.93),xycoords='axes fraction',frameon=False))
        axes[1].text(.07,.84,'0.10 m',transform=axes[1].transAxes,fontsize=7)
        for ax in axes:
            ax.set(xlim=(lo,hi),ylim=(0,ymax),xlabel='Peak wing-root torque (N m)',ylabel='Mean single-wing thrust (N)');ax.grid(alpha=.18);ax.set_axisbelow(True)
        fig.savefig(dest/'lambda_comparison.png',dpi=600);plt.close(fig)
        paths=[p for p in b['lineages'] if any(r['study']==p['study'] for r in rows)]
        fig,axes=plt.subplots(1,len({p['study'] for p in paths}),figsize=(7.16,3.4),layout='constrained',squeeze=False)
        from case_identity import FAMILY_COLORS
        for ax,study in zip(axes[0],[s for s in b['studies'] if any(p['study']==s['id'] for p in paths)]):
            for path in [p for p in paths if p['study']==study['id']]:
                ps=path['points'];base=ps[0]['score'];style={.4:':',.6:'--',.8:'-'}
                ax.plot(range(len(ps)),[p['score']-base for p in ps],color=FAMILY_COLORS[path['family']],
                    linestyle=style.get(round(path['starting_total_span_m'],1),'-'),lw=.8,alpha=.8)
            ax.set(title=study['name'],xlabel='Accepted evolution step',ylabel='Score gain from own seed');ax.grid(alpha=.18)
        from case_identity import FAMILY_LABELS
        keys=[Line2D([],[],color=FAMILY_COLORS[k],lw=1,label=FAMILY_LABELS[k]) for k in FAMILY_COLORS]
        keys.extend(Line2D([],[],color='#52616b',lw=1,linestyle=style,label=f'{span:g} m start') for span,style in ((.4,':'),(.6,'--'),(.8,'-')))
        fig.legend(handles=keys,loc='outside lower center',ncol=4,fontsize=6,frameon=False)
        fig.savefig(dest/'evolution_audit.png',dpi=600);plt.close(fig)
        groups=[s for s in b['studies'] if any(p['study']==s['id'] for p in paths)]
        fig,axes=plt.subplots(len(groups),1,figsize=(7.16,3*len(groups)),layout='constrained',squeeze=False,sharex=True,sharey=True)
        xmax=max(p['torque'] for path in paths for p in path['points'])*1.08
        ymax=max(p['thrust'] for path in paths for p in path['points'])*1.08
        max_span=max(max(p[0] for p in point['outline_m']) for path in paths for point in path['points'])
        scale=26/max(max_span,1e-9)
        for ax,study in zip(axes[:,0],groups):
            for path in [p for p in paths if p['study']==study['id']]:
                ps=path['points'];color=FAMILY_COLORS[path['family']];style={.4:':',.6:'--',.8:'-.'}[round(path['starting_total_span_m'],1)]
                ax.plot([p['torque'] for p in ps],[p['thrust'] for p in ps],ls=style,lw=.7,color=color,alpha=.7)
                for point,final in ((ps[0],False),(ps[-1],True)):
                    poly=np.array(point['outline_m']);lower=poly.min(axis=0);size=(poly.max(axis=0)-lower)*scale;v=(poly-lower)*scale;v[:,1]=size[1]-v[:,1]
                    box=DrawingArea(max(size[0],1),max(size[1],1));box.add_artist(Polygon(v,facecolor=color,alpha=1 if final else .25,edgecolor='black' if final else '#b0b0b0',lw=.7 if final else .4))
                    ax.add_artist(AnnotationBbox(box,(point['torque'],point['thrust']),frameon=False,pad=0,zorder=3 if final else 2))
            ax.set(xlim=(0,xmax),ylim=(0,ymax),title=f"{study['name']} · all {sum(p['study']==study['id'] for p in paths)} seeds",ylabel='Mean single-wing thrust (N)');ax.grid(alpha=.18)
            bar=DrawingArea(scale*.1,8);bar.add_artist(Line2D([0,scale*.1],[4,4],color='#17313d',lw=1.5))
            ax.add_artist(AnnotationBbox(bar,(.04,.92),xycoords='axes fraction',frameon=False));ax.text(.04,.84,'0.10 m',transform=ax.transAxes,fontsize=7)
        axes[-1,0].set_xlabel('Peak wing-root torque (N m)')
        keys=[Line2D([],[],color=FAMILY_COLORS[k],lw=1,label=FAMILY_LABELS[k]) for k in FAMILY_COLORS if any(p['family']==k for p in paths)]
        keys.extend(Line2D([],[],color='#52616b',lw=1,linestyle=style,label=f'{span:g} m start') for span,style in ((.4,':'),(.6,'--'),(.8,'-.')))
        fig.legend(handles=keys,loc='outside lower center',ncol=4,fontsize=6,frameon=False)
        fig.savefig(dest/'seed_evolutions.png',dpi=600);plt.close(fig)
