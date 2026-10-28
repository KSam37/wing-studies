"""Best observed thrust for every allowable single-wing root torque."""
import csv
import hashlib
from torque_study import classify
from wing_dimensions import dimensions

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


def generate(model,data):
    import catalog
    study=data.get('study')
    if study=='master':
        catalog.sync(model)
        rows=catalog.generations(model,data.get('generations',['current']))['rows']
    else:
        directory=model.OUTPUTS/study
        manifest=model.read_json(directory/'manifest.json')
        rows=[{**r,'_study':study,'_settings':manifest['settings']} for r in model.read_json(directory/'results.json')]
    import torque_study
    mode=data.get('model_mode','rigid') if study=='master' else ('aeroelastic' if manifest['settings'].get('aeroelastic_enabled',False) else 'rigid')
    rows=torque_study.select_model(rows,mode)
    from wing_dimensions import span_class
    chosen_span=data.get('span_class','all')
    if chosen_span!='all':rows=[r for r in rows if span_class(r)==chosen_span]
    eligible,points=envelope(rows,allow_aeroelastic=mode=='aeroelastic')
    if not points:raise ValueError('No settled single-wing designs for the selected model with valid positive thrust are available.')
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
    background=sample_background(all_range,points,shown,spacing,left,right)
    digest=hashlib.sha256(catalog.compact(['wing-markers-v5',mode,lower,upper,spacing,size,[(r.get('_study'),r['id'],r[TORQUE],r[THRUST]) for r in eligible]]).encode()).hexdigest()[:12]
    dest=model.OUTPUTS/('torque-frontier-'+digest);dest.mkdir(exist_ok=True)
    from matplotlib.path import Path as MarkerPath
    plt=model.ieee_style();fig,ax=plt.subplots(figsize=(7.16,4.5),layout='constrained')
    from matplotlib.colors import Normalize
    from matplotlib.cm import ScalarMappable
    ratios=[r[THRUST]/r[TORQUE] for r in all_range if r[TORQUE]>0]
    low=min(ratios,default=0);high=max(ratios,default=1)
    norm=Normalize(low,high if high>low else low+1e-9);cmap=plt.get_cmap('viridis')
    frontier_ids={identity(r) for r in points}
    for row in [*background,*shown]:
        is_frontier=identity(row) in frontier_ids
        vertices=[];codes=[]
        for polygon in model.wing_thumbnail(row,row.get('_settings',{}).get('gap_m',0)):
            polygon=[(x,-y) for x,y in polygon] # Match the downward chord direction of the GUI top view.
            vertices.extend([*polygon,polygon[0]])
            codes.extend([MarkerPath.MOVETO,*([MarkerPath.LINETO]*(len(polygon)-1)),MarkerPath.CLOSEPOLY])
        ax.scatter([row[TORQUE]],[row[THRUST]],marker=MarkerPath(vertices,codes),s=150*(size/100)**2*(1.5**2 if is_frontier else 1),
            facecolors=cmap(norm(row[THRUST]/row[TORQUE])) if row[TORQUE]>0 else '#aaa',
            edgecolors='#172f36' if is_frontier else '#666',linewidths=.7 if is_frontier else .35,zorder=3 if is_frontier else 2)
    ax.set(xlabel='Peak wing-root torque (N m)',ylabel='Mean single-wing thrust (N)')
    ax.margins(.06);ax.grid(alpha=.2)
    if lower is not None or upper is not None:ax.set_xlim(left,right)
    if not shown and not background:ax.text(.5,.5,'No improving designs in this torque range',ha='center',transform=ax.transAxes,fontsize=9)
    ax.set_title(('Native aeroelastic' if mode=='aeroelastic' else 'Rigid')+' designs · frontier wings 50% larger',fontsize=9)
    fig.colorbar(ScalarMappable(norm=norm,cmap=cmap),ax=ax,label='Mean thrust / peak root torque (1/m)',pad=.02)
    fig.savefig(dest/'thrust_torque_frontier.png',dpi=600);plt.close(fig)
    fields=['peak_root_torque_Nm','mean_single_wing_thrust_N','global_case_no','study','case','design_name','single_wing_span_m','effective_total_span_m','frequency_hz','speed_mps','dt_s','cycles','thrust_to_torque_1pm','is_frontier','displayed','model_mode','spring_constant_rad','damping_constant_rad','wing_density','peak_abs_native_twist_deg']
    with (dest/'thrust_torque_frontier.csv').open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
        displayed_ids={identity(r) for r in [*shown,*background]}
        for r in all_range:w.writerow(dict(zip(fields,[r[TORQUE],r[THRUST],r.get('global_case_no'),r.get('_study',study),r['id'],r.get('design_name'),r.get('single_wing_span_m'),r.get('effective_total_span_m'),*[r.get('_settings',{}).get(k) for k in ('frequency_hz','speed_mps','dt_s','cycles')],r[THRUST]/r[TORQUE] if r[TORQUE]>0 else None,identity(r) in frontier_ids,identity(r) in displayed_ids,mode,*[r.get(k,r.get('_settings',{}).get(k)) for k in ('spring_constant_rad','damping_constant_rad','wing_density','peak_abs_native_twist_deg')]])))
    return {'model_mode':mode,'points':points,'plotted_count':len(shown),'background_count':len(background),'range_count':len(in_range),'minimum_spacing_nm':spacing,'minimum_torque_nm':left,'slider_maximum_torque_nm':min(right,eligible[-1][TORQUE]),'eligible_count':len(eligible),'maximum_torque_nm':eligible[-1][TORQUE],
        'files':[str((dest/name).relative_to(model.OUTPUTS)).replace(chr(92),'/') for name in ('thrust_torque_frontier.png','thrust_torque_frontier.csv')]}
