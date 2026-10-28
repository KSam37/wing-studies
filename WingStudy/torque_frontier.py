"""Best observed thrust for every allowable single-wing root torque."""
import csv
import hashlib
from torque_study import classify
from wing_dimensions import dimensions

TORQUE='single_wing_peak_abs_roll_moment_Nm'
THRUST='single_wing_mean_thrust_N'

def envelope(rows):
    eligible=sorted((r for r in rows if classify(r,float('inf'))=='Within limit'),
        key=lambda r:(r[TORQUE],-r[THRUST],str(r.get('comparison_key',r['id']))))
    points=[];best=float('-inf')
    for row in eligible:
        if row[THRUST]>best:
            points.append({**row,**dimensions(row)})
            best=row[THRUST]
    return eligible,points


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
    eligible,points=envelope(rows)
    if not points:raise ValueError('No settled rigid single-wing designs with valid positive thrust are available.')
    digest=hashlib.sha256(catalog.compact(['wing-markers-v1',[(r.get('_study'),r['id'],r[TORQUE],r[THRUST]) for r in eligible]]).encode()).hexdigest()[:12]
    dest=model.OUTPUTS/('torque-frontier-'+digest);dest.mkdir(exist_ok=True)
    from matplotlib.path import Path as MarkerPath
    plt=model.ieee_style();fig,ax=plt.subplots(figsize=(7.16,4.5),layout='constrained')
    for row in points:
        vertices=[];codes=[]
        for polygon in model.wing_thumbnail(row,row.get('_settings',{}).get('gap_m',0)):
            vertices.extend([*polygon,polygon[0]])
            codes.extend([MarkerPath.MOVETO,*([MarkerPath.LINETO]*(len(polygon)-1)),MarkerPath.CLOSEPOLY])
        ax.scatter([row[TORQUE]],[row[THRUST]],marker=MarkerPath(vertices,codes),s=150,
            facecolors='#c6e6df',edgecolors='#007f78',linewidths=.55,zorder=3)
    ax.set(xlabel='Allowable peak wing-root torque (N m)',ylabel='Maximum mean single-wing thrust (N)')
    ax.margins(.06);ax.grid(alpha=.2)
    ax.set_title('Best available designs · normalized wing silhouettes',fontsize=9)
    fig.savefig(dest/'thrust_torque_frontier.png',dpi=600);plt.close(fig)
    fields=['minimum_allowable_root_torque_Nm','maximum_mean_single_wing_thrust_N','global_case_no','study','case','design_name','single_wing_span_m','effective_total_span_m','frequency_hz','speed_mps','dt_s','cycles']
    with (dest/'thrust_torque_frontier.csv').open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
        for r in points:w.writerow(dict(zip(fields,[r[TORQUE],r[THRUST],r.get('global_case_no'),r.get('_study',study),r['id'],r.get('design_name'),r.get('single_wing_span_m'),r.get('effective_total_span_m'),*[r.get('_settings',{}).get(k) for k in ('frequency_hz','speed_mps','dt_s','cycles')]])))
    return {'points':points,'eligible_count':len(eligible),'maximum_torque_nm':eligible[-1][TORQUE],
        'files':[str((dest/name).relative_to(model.OUTPUTS)).replace(chr(92),'/') for name in ('thrust_torque_frontier.png','thrust_torque_frontier.csv')]}
