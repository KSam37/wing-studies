"""Best observed thrust for every allowable single-wing root torque."""
import csv
import hashlib
import math
from decimal import Decimal, ROUND_FLOOR, ROUND_CEILING
from .torque_study import classify
from .wing_dimensions import dimensions

TORQUE='single_wing_peak_abs_roll_moment_Nm'
THRUST='single_wing_mean_thrust_N'

def envelope(rows,allow_aeroelastic=False):
    eligible=sorted((r for r in rows if classify(r,float('inf'),allow_aeroelastic=allow_aeroelastic)=='Within limit'),
        key=lambda r:(r[TORQUE],-r[THRUST],str(r.get('comparison_key',r['id']))))
    points=[];best=float('-inf')
    for row in eligible:
        if row[THRUST]>best:
            points.append({**row,**dimensions(row)})
            best=row[THRUST]
    return eligible,points


def spaced_points(points,spacing):
    """Thin display markers only, retaining the highest-thrust end first."""
    kept=[]
    for row in reversed(points):
        if not kept or kept[-1][TORQUE]-row[TORQUE]>=spacing-1e-12:
            kept.append(row)
    return list(reversed(kept))


def identity(row):
    return (row.get('_study'),row.get('comparison_key',row['id']))


def band_winners(rows,left,right,width):
    """Highest observed mean thrust in each occupied torque interval.

    Bands start at the plot minimum. Internal upper edges belong to the next
    band; the final upper edge is included. This only selects displayed results.
    """
    if not math.isfinite(width) or width<=0:raise ValueError('Torque band width must be positive and finite.')
    start=Decimal(str(left));stop=Decimal(str(right));increment=Decimal(str(width))
    groups={};last=max(0,int(((stop-start)/increment).to_integral_value(rounding=ROUND_CEILING))-1)
    for row in rows:
        if not left<=row[TORQUE]<=right:continue
        index=min(last,max(0,int(((Decimal(str(row[TORQUE]))-start)/increment).to_integral_value(rounding=ROUND_FLOOR))))
        groups.setdefault(index,[]).append(row)
    winners=[]
    for index,group in sorted(groups.items()):
        winner=min(group,key=lambda r:(-r[THRUST],r[TORQUE],str(identity(r))))
        winners.append({**winner,'torque_band_min_nm':float(start+index*increment),
            'torque_band_max_nm':float(min(stop,start+(index+1)*increment)),
            'torque_band_count':len(group),'torque_band_includes_upper':index==last})
    return winners


def sample_background(rows,frontier,shown,spacing,left,right):
    """Screen-space sampling in torque and proportionally scaled thrust."""
    frontier_ids={identity(r) for r in frontier}
    candidates=[r for r in rows if identity(r) not in frontier_ids]
    if spacing==0:return candidates
    ys=[r[THRUST] for r in rows]
    thrust_spacing=max(max(ys,default=0)-min(ys,default=0),1e-12)*spacing/max(right-left,1e-12)
    kept=[];occupied=list(shown)
    for row in sorted(candidates,key=lambda r:(-r[THRUST]/r[TORQUE] if r[TORQUE]>0 else float('-inf'),r[TORQUE],str(identity(r)))):
        if all(((row[TORQUE]-p[TORQUE])/spacing)**2+((row[THRUST]-p[THRUST])/thrust_spacing)**2>=1-1e-12 for p in occupied):
            kept.append(row);occupied.append(row)
    return kept


def evolution_rows(model,rows,include_seeds=True):
    """Only recorded seeds or changes satisfying the strict parent rule.

    Resolve occurrences as well as origin paths because a reused simulation
    can be a winner in another study. Never infer a history from all trials.
    """
    from . import adaptive
    histories={};target_histories={};memberships={};final_histories={};selected=[]
    for row in rows:
        locations=[{'study':row.get('_study'),'local_case':row['id']},*row.get('occurrences',[])]
        roles=[]
        for location in locations:
            study=location.get('study')
            if not study:continue
            if study not in histories:
                path=model.OUTPUTS/study/'evolution.json'
                events=model.read_json(path) if path.is_file() else []
                curve_path=model.OUTPUTS/study/'torque_targets.json'
                curve=model.read_json(curve_path) if curve_path.is_file() else None
                lookup={e['case']['id']:e['case'] for e in events}
                latest={}
                for e in events:
                    if e.get('accepted',True):latest[e.get('job',0)]=e['case']['id']
                final_histories[study]=set(latest.values())
                accepted={};target_histories[study]={};memberships[study]={}
                for sequence,e in enumerate(events):
                    parent=e.get('parent_case');case=e['case']
                    if e.get('kind')=='seed' or curve is None and parent is None:accepted[case['id']]='seed'
                    elif e.get('search_algorithm')=='independent_coordinate_v1' and e.get('accepted'):
                        accepted[case['id']]='improvement'
                    elif curve is None and parent in lookup and adaptive.improves(case,lookup[parent]):accepted[case['id']]='improvement'
                    if e.get('search_algorithm')=='independent_coordinate_v1' and e.get('accepted'):
                        memberships[study].setdefault(case['id'],[]).append({'study':study,'job':e['job'],
                            'sequence':sequence,'seed_family':e['seed_family'],'span_m':e['span_m'],
                            'weighted_score':e['weighted_score'],'parent_case':parent,'local_case':case['id']})
                if curve is not None:
                    # Current best feasible designs across torque targets, not
                    # every historical incumbent or every evaluated candidate.
                    for target in curve['targets']:
                        if target.get('case_id'):
                            accepted[target['case_id']]='improvement'
                            target_histories[study].setdefault(target['case_id'],[]).append(target['available_root_torque_Nm'])
                histories[study]=accepted
            role=histories[study].get(location['local_case'])
            if role=='improvement' or role=='seed' and include_seeds:roles.append(role)
        if roles:
            targets=sorted(set(q for loc in locations for q in target_histories.get(loc.get('study'),{}).get(loc['local_case'],[])))
            nodes=[node for loc in locations for node in memberships.get(loc.get('study'),{}).get(loc['local_case'],[])]
            selected.append({**row,'available_torque_targets_Nm':targets,'evolution_memberships':nodes,
                'is_final_evolution':any(loc['local_case'] in final_histories.get(loc.get('study'),set()) for loc in locations),
                'evolution_role':'improvement' if 'improvement' in roles else 'seed'})
    return selected


def evolution_paths(rows):
    """Group by recorded seed lineage, never by torque order or cache origin."""
    groups={}
    for row in rows:
        for node in row.get('evolution_memberships',[]):
            key=(node['study'],node['job'])
            groups.setdefault(key,{})[node['sequence']]={**node,'torque_Nm':row[TORQUE],'thrust_N':row[THRUST]}
    return [{'study':study,'job':job,'points':[points[k] for k in sorted(points)]}
        for (study,job),points in sorted(groups.items())]


def generate(model,data):
    from . import catalog
    study=data.get('study')
    if study=='master':
        catalog.sync(model)
        rows=catalog.generations(model,data.get('generations',['current']))['rows']
    else:
        directory=model.OUTPUTS/study
        manifest=model.read_json(directory/'manifest.json')
        rows=[{**r,'_study':study,'_settings':manifest['settings']} for r in model.read_json(directory/'results.json')]
    from . import torque_study
    mode=data.get('model_mode','rigid') if study=='master' else ('aeroelastic' if manifest['settings'].get('aeroelastic_enabled',False) else 'rigid')
    rows=torque_study.select_model(rows,mode)
    from .case_identity import families,FAMILY_LABELS,FAMILY_COLORS
    family=data.get('seed_family','all');color_mode=data.get('color_mode','ratio')
    if family!='all' and family not in FAMILY_LABELS:raise ValueError('Unknown seed family.')
    if color_mode not in ('family','ratio'):raise ValueError('Unknown wing color mode.')
    if family!='all':rows=[r for r in rows if family in families(r)]
    from .wing_dimensions import span_class
    chosen_span=data.get('span_class','all')
    if chosen_span!='all':rows=[r for r in rows if span_class(r)==chosen_span]
    comparison=data.get('comparison_mode','frontier')
    history=evolution_rows(model,rows,data.get('include_seeds',True) if comparison=='evolution' else True)
    if comparison=='evolution':rows=history
    else:
        finals={identity(r) for r in history if r.get('is_final_evolution')}
        rows=[{**r,'is_final_evolution':identity(r) in finals} for r in rows]
    eligible,points=envelope(rows,allow_aeroelastic=mode=='aeroelastic')
    if comparison=='evolution':points=[{**r,**dimensions(r)} for r in eligible]
    if not points:
        if comparison=='evolution':raise ValueError('No eligible recorded winning evolution designs in this selection. Include seeds or choose another comparison view for all trials.')
        raise ValueError('No settled single-wing designs for the selected model with valid positive thrust are available.')
    def bound(key,label):
        value=data.get(key)
        return None if value in (None,'') else model.number(value,label,0)
    lower=bound('torque_min_nm','Minimum plot torque')
    upper=bound('torque_max_nm','Maximum plot torque')
    left=0. if lower is None else lower
    right=eligible[-1][TORQUE] if upper is None else upper
    if right<=left:raise ValueError('Maximum plot torque must exceed minimum plot torque.')
    if left>eligible[-1][TORQUE]:raise ValueError('The torque range is above the available data.')
    in_range=[r for r in points if left<=r[TORQUE]<=right]
    spacing=model.number(data.get('minimum_spacing_nm',.1),'Minimum marker torque spacing',0)
    size=model.number(data.get('wing_size_percent',100),'Wing marker size (%)',10,400)
    shown=spaced_points(in_range,spacing)
    all_range=[{**r,**dimensions(r)} for r in eligible if left<=r[TORQUE]<=right]
    if comparison not in ('frontier','bands','evolution'):raise ValueError('Choose winning evolution, full frontier or torque-band winners.')
    band_width=model.number(data.get('torque_band_width_nm',.25),'Torque band width',1e-12) if comparison=='bands' else None
    winners=band_winners(all_range,left,right,band_width) if comparison=='bands' else []
    if comparison=='bands':shown=winners
    if comparison=='evolution':shown=all_range
    background=[] if comparison in ('bands','evolution') else sample_background(all_range,points,shown,spacing,left,right)
    paths=evolution_paths(all_range) if comparison=='evolution' else []
    digest=hashlib.sha256(catalog.compact(['physical-wing-markers-v12',paths,family,color_mode,comparison,band_width,mode,lower,upper,spacing,size,[(r.get('_study'),r['id'],r[TORQUE],r[THRUST],r.get('is_final_evolution',False)) for r in eligible]]).encode()).hexdigest()[:12]
    dest=model.OUTPUTS/('torque-frontier-'+digest);dest.mkdir(exist_ok=True)
    from matplotlib.offsetbox import DrawingArea, AnnotationBbox
    from matplotlib.patches import Polygon
    plt=model.ieee_style();fig,ax=plt.subplots(figsize=(7.16,4.5),layout='constrained')
    from matplotlib.colors import Normalize
    from matplotlib.cm import ScalarMappable
    ratios=[r[THRUST]/r[TORQUE] for r in all_range if r[TORQUE]>0]
    low=min(ratios,default=0);high=max(ratios,default=1)
    norm=Normalize(low,high if high>low else low+1e-9);cmap=plt.get_cmap('viridis')
    frontier_ids={identity(r) for r in points};winner_map={identity(r):r for r in winners};displayed=[]
    import numpy as np
    for path in paths:
        ps=path['points'];color=FAMILY_COLORS.get(ps[0]['seed_family'],'#777')
        ax.plot([p['torque_Nm'] for p in ps],[p['thrust_N'] for p in ps],linestyle='--',
            lw=.7,color=color,alpha=.7,zorder=1)
    for row in [*background,*shown]:
        leading,frames=model.custom_frames(row)
        leading=np.asarray(leading);trailing=[p+f@np.array([s['chord_m'],0,0]) for p,f,s in zip(leading,frames,row['sections'])]
        polygon=[[float(p[1]),float(p[0])] for p in [*leading,*trailing[::-1]]]
        displayed.append({**row,'outline_m':polygon,'is_frontier':identity(row) in frontier_ids,'is_representative':identity(row) in winner_map})
    extent=max((max(max(p[k] for p in r['outline_m'])-min(p[k] for p in r['outline_m']) for k in (0,1)) for r in displayed),default=.4)
    points_per_m=30/max(extent,1e-9)*size/100
    for row in displayed:
        polygon=np.asarray(row['outline_m']);lo=polygon.min(axis=0);hi=polygon.max(axis=0)
        width,height=(hi-lo)*points_per_m
        box=DrawingArea(max(width,1),max(height,1),0,0)
        vertices=(polygon-lo)*points_per_m;vertices[:,1]=height-vertices[:,1]
        emphasized=row.get('is_final_evolution',False)
        color=FAMILY_COLORS[families(row)[0]] if color_mode=='family' else cmap(norm(row[THRUST]/row[TORQUE])) if row[TORQUE]>0 else '#aaa'
        box.add_artist(Polygon(vertices,facecolor=color,edgecolor='#000000' if emphasized else '#b0b0b0',linewidth=.8 if emphasized else .5))
        ax.add_artist(AnnotationBbox(box,(row[TORQUE],row[THRUST]),frameon=False,pad=0,zorder=3 if emphasized else 2))
        ax.plot(row[TORQUE],row[THRUST],alpha=0)
    ax.set(xlabel='Peak wing-root torque (N m)',ylabel='Mean single-wing thrust (N)')
    ax.margins(.06);ax.grid(alpha=.2)
    if lower is not None or upper is not None:ax.set_xlim(left,right)
    if not shown and not background:ax.text(.5,.5,'No improving designs in this torque range',ha='center',transform=ax.transAxes,fontsize=9)
    title=(f'Highest observed thrust per {band_width:g} N m torque band' if comparison=='bands' else 'Independent seed evolutions' if paths else 'Winning evolution designs' if comparison=='evolution' else 'Observed thrust–torque frontier')
    ax.set_title(title+' · common physical wing scale',fontsize=9)
    from matplotlib.lines import Line2D
    from matplotlib.text import Text
    legend=DrawingArea(points_per_m*.1+46,18,0,0)
    legend.add_artist(Line2D([0,points_per_m*.1],[8,8],color='#17313d',linewidth=1.5))
    legend.add_artist(Text(points_per_m*.1+4,5,'0.10 m',fontsize=7))
    ax.add_artist(AnnotationBbox(legend,(.03,.96),xycoords='axes fraction',box_alignment=(0,1),frameon=True,pad=.3))
    if color_mode=='family':
        ax.legend(handles=[Line2D([],[],marker='s',linestyle='',color=FAMILY_COLORS[f],label=FAMILY_LABELS[f]) for f in FAMILY_LABELS if any(f in families(r) for r in displayed)],fontsize=6,loc='lower right')
    else:fig.colorbar(ScalarMappable(norm=norm,cmap=cmap),ax=ax,label='Mean thrust / peak root torque (1/m)',pad=.02)
    fig.savefig(dest/'thrust_torque_frontier.png',dpi=600);plt.close(fig)
    fields=['available_torque_targets_Nm','evolution_role','seed_families','geometry_id','simulation_id','peak_root_torque_Nm','mean_single_wing_thrust_N','global_case_no','study','case','design_name','single_wing_span_m','effective_total_span_m','frequency_hz','speed_mps','dt_s','cycles','thrust_to_torque_1pm','is_frontier','displayed','model_mode','spring_constant_rad','damping_constant_rad','wing_density','peak_abs_native_twist_deg','is_band_winner','band_min_torque_Nm','band_max_torque_Nm','band_design_count','is_final_evolution']
    with (dest/'thrust_torque_frontier.csv').open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
        displayed_ids={identity(r) for r in [*shown,*background]}
        for r in all_range:
            winner=winner_map.get(identity(r),{})
            w.writerow(dict(zip(fields,[';'.join(str(q) for q in r.get('available_torque_targets_Nm',[])),r.get('evolution_role'),';'.join(families(r)),r.get('geometry_id'),r.get('simulation_id'),r[TORQUE],r[THRUST],r.get('global_case_no'),r.get('_study',study),r['id'],r.get('design_name'),r.get('single_wing_span_m'),r.get('effective_total_span_m'),*[r.get('_settings',{}).get(k) for k in ('frequency_hz','speed_mps','dt_s','cycles')],r[THRUST]/r[TORQUE] if r[TORQUE]>0 else None,identity(r) in frontier_ids,identity(r) in displayed_ids,mode,*[r.get(k,r.get('_settings',{}).get(k)) for k in ('spring_constant_rad','damping_constant_rad','wing_density','peak_abs_native_twist_deg')],bool(winner),winner.get('torque_band_min_nm'),winner.get('torque_band_max_nm'),winner.get('torque_band_count'),bool(r.get('is_final_evolution'))])))
    curve_path=model.OUTPUTS/study/'torque_targets.json' if study!='master' else None
    curve=model.read_json(curve_path) if curve_path and curve_path.is_file() else {}
    return {'evolution_paths':paths,'torque_targets':curve.get('targets',[]),'curve_csv':str((model.OUTPUTS/study/'comparisons/torque_curve.csv').relative_to(model.OUTPUTS)).replace(chr(92),'/') if curve else None,'seed_family':family,'color_mode':color_mode,'family_colors':FAMILY_COLORS,'family_labels':FAMILY_LABELS,'comparison_mode':comparison,'torque_band_width_nm':band_width,'model_mode':mode,'points':winners if comparison=='bands' else all_range if comparison=='evolution' else points,'displayed':displayed,'wing_size_percent':size,'plotted_count':len(shown),'background_count':len(background),'range_count':len(in_range),'range_eligible_count':len(all_range),'minimum_spacing_nm':spacing,'minimum_torque_nm':left,'plot_maximum_torque_nm':right,'slider_maximum_torque_nm':right if comparison=='bands' else min(right,eligible[-1][TORQUE]),'eligible_count':len(eligible),'maximum_torque_nm':eligible[-1][TORQUE],
        'files':[str((dest/name).relative_to(model.OUTPUTS)).replace(chr(92),'/') for name in ('thrust_torque_frontier.png','thrust_torque_frontier.csv')]}
