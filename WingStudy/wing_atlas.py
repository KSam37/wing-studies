"""All retained successful simulations, exact identities and matched conditions.

Legacy paired-wing forces are indexed but never substituted for single-wing
loads or root torque. No simulations are run by this module.
"""
import csv
import hashlib
import json
import math
from collections import Counter
import catalog
import study_organization
from wing_dimensions import dimensions

METRICS={'torque':'Peak single-wing root torque (N m)','thrust':'Mean thrust (N)',
    'span':'Root-to-tip span (m)','area':'Single-wing area (m²)','root':'Root chord (m)',
    'aspect':'Single-wing aspect ratio','fullness':'Area / (span × root chord)',
    'taper':'Tip / root chord','ratio':'Mean thrust / peak root torque (1/m)'}
AXES=('torque','thrust','span','area','root','aspect','fullness','taper','ratio')


def finite(value):return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value)


def conditions(row):
    """Use effective per-case motion and numerical values, not only study defaults."""
    s=row['_settings'];single=row.get('simulation_mode')=='isolated_single_wing_v1'
    values={k:row.get(k,s.get(k)) for k in ('rho','nu','frequency_hz','speed_mps','amplitude_deg','dt_s','cycles','span_panels','chord_panels','wake_model','wake_cycles')}
    values.update(waveform=row.get('waveform') or s.get('waveform') or {'mode':'sine'},
        tail=s.get('tail',{'enabled':False}),aeroelastic=bool(row.get('aeroelastic_enabled',s.get('aeroelastic_enabled',False))),
        load_scope='single' if single else 'paired',moment_definition=row.get('shape_objective_version'),
        ptera=row.get('_ptera_version'),verified=bool(row.get('_verified')))
    if values['aeroelastic']:
        values.update({k:s.get(k) for k in ('spring_constant_rad','damping_constant_rad','wing_density','step_discards')})
    if not values['verified']:values['unverified_source']=row['_study']
    return values


def outline(model,row):
    if row.get('sections'):
        from lambda_review import polygon
        return polygon(model,row)
    st=model.stations(row,row['_settings'].get('gap_m',0))
    base=st[0][0]
    return [[float(y-base),float(x)] for y,x,c in st]+[[float(y-base),float(x+c)] for y,x,c in reversed(st)]


def bundle(model):
    data=catalog.generations(model,['current','old']);org=study_organization.read(model)
    locations={}
    stores=[catalog.connect(model)]
    if (model.OUTPUTS.parent/'master_runs_old.sqlite3').is_file():stores.append(catalog.old_connection(model))
    for db in stores:
        with db:
            for o in db.execute("SELECT c.signature,o.study,o.local_case FROM cases c JOIN occurrences o ON o.case_no=c.case_no WHERE o.state='ok'"):
                if study_organization.visible(org,o['study']):locations.setdefault(o['signature'],set()).add((o['study'],o['local_case']))
    rows=[];groups={};excluded=Counter();studies={}
    for r in data['rows']:
        if r.get('status')!='ok':excluded['Unsuccessful or not simulated']+=1;continue
        try:poly=outline(model,r)
        except (ValueError,KeyError,TypeError):excluded['Geometry unavailable']+=1;continue
        if not poly or not all(finite(v) for p in poly for v in p):excluded['Geometry unavailable']+=1;continue
        c=conditions(r);key='C-'+hashlib.sha256(catalog.compact(c).encode()).hexdigest()[:12]
        groups.setdefault(key,{'id':key,'conditions':c,'count':0})['count']+=1
        dims=dimensions(r);span=dims.get('single_wing_span_m') or max(p[0] for p in poly)-min(p[0] for p in poly)
        section=r.get('sections') or []
        root=section[0]['chord_m'] if section else r.get('root_chord_m')
        tip=section[-1]['chord_m'] if section else root*r.get('tip_ratio',1)
        area=r.get('area_m2')
        if c['load_scope']=='paired' and finite(area):area/=2
        thrust=r.get('single_wing_mean_thrust_N') if c['load_scope']=='single' else r.get('mean_thrust_N')
        torque=r.get('single_wing_peak_abs_roll_moment_Nm') if c['load_scope']=='single' else None
        occ=sorted(locations.get(r['_signature'],{(r['_study'],r['id'])}));gens=set()
        for study,case in occ:
            group=org.get('studies',{}).get(study,{}).get('group')
            generation='old' if group=='old' or study in data.get('partition',{}).get('archived_studies',[]) else 'current'
            gens.add(generation)
            studies[study]={'id':study,'name':study_organization.name(org,study),'generation':generation}
        rows.append({'key':r['_signature'],'geometry_id':r.get('geometry_id'),'simulation_id':r.get('simulation_id'),
            'study':r['_study'],'id':r['id'],'number':r['global_case_no'],'name':r.get('design_name',r['id']),
            'cohort':key,'generations':sorted(gens),'studies':sorted({s for s,_ in occ}),
            'locations':[{'study':s,'case':i} for s,i in occ],'outline':poly,
            'chords':[s['chord_m'] for s in section] if section else [root,tip],
            'settled':bool(r.get('cycle_repeatable')),'load_scope':c['load_scope'],
            'thrust':thrust,'torque':torque,'span':span,'area':area,'root':root,
            'aspect':span*span/area if finite(span) and finite(area) and area>0 else None,
            'fullness':area/(span*root) if all(finite(x) and x>0 for x in (area,span,root)) else None,
            'taper':tip/root if finite(root) and root>0 and finite(tip) else None,
            'ratio':thrust/torque if finite(thrust) and finite(torque) and torque>0 else None})
    cohorts=sorted(groups.values(),key=lambda g:-g['count'])
    for i,g in enumerate(cohorts,1):
        c=g['conditions'];g['label']=(f"{g['count']} cases · {c['load_scope']} · {c['frequency_hz']:g} Hz · {c['speed_mps']:g} m/s · "
            f"dt {c['dt_s']:g} s · {c['span_panels']}×{c['chord_panels']} panels · {c['wake_model']}/{c['wake_cycles']} cycles · {c['waveform'].get('mode','sine')} · group {i}")
    return {'rows':rows,'cohorts':cohorts,'studies':sorted(studies.values(),key=lambda s:s['id'],reverse=True),
        'successful':len(rows),'single_count':sum(r['load_scope']=='single' for r in rows),
        'paired_count':sum(r['load_scope']=='paired' for r in rows),'excluded':dict(excluded),
        'geometry_count':len({r['geometry_id'] for r in rows}),'metrics':METRICS,
        'note':'All retained New and Old catalogs. Identical simulation signatures are merged; every successful simulation remains available. Previously deleted runs cannot be reconstructed.'}


def select(b,data):
    cohort=data.get('cohort','all_single');known={g['id'] for g in b['cohorts']}
    if cohort!='all_single' and cohort not in known:raise ValueError('Choose a saved conditions group.')
    generations=data.get('generations',['current','old'])
    if not isinstance(generations,list) or any(g not in ('current','old') for g in generations):raise ValueError('Choose New and/or Old.')
    x=data.get('x','torque');y=data.get('y','thrust');color=data.get('color','span')
    if any(k not in METRICS for k in (x,y,color)):raise ValueError('Unknown plot metric.')
    rows=[r for r in b['rows'] if (r['load_scope']=='single' if cohort=='all_single' else r['cohort']==cohort)
        and any(g in generations for g in r['generations']) and (not data.get('study') or data['study'] in r['studies'])]
    ranges=(('span','span_min','span_max'),('root','root_min','root_max'),(x,'xmin','xmax'),(y,'ymin','ymax'))
    for field,low,high in ranges:
        left=data.get(low);right=data.get(high)
        left=None if left in (None,'') else float(left);right=None if right in (None,'') else float(right)
        if any(v is not None and not math.isfinite(v) for v in (left,right)):raise ValueError('Filter bounds must be finite.')
        if left is not None and right is not None and right<left:raise ValueError('Maximum must be at least minimum.')
        rows=[r for r in rows if finite(r.get(field)) and (left is None or r[field]>=left) and (right is None or r[field]<=right)]
    return rows,x,y,color


def sample(rows,x,y,limit=24):
    """One actual case near each occupied output-space cell center, then spread cells."""
    if not rows or limit==0:return []
    xmin=min(r[x] for r in rows);xmax=max(r[x] for r in rows);ymin=min(r[y] for r in rows);ymax=max(r[y] for r in rows)
    cells={}
    for r in rows:
        a=(r[x]-xmin)/(xmax-xmin or 1);b=(r[y]-ymin)/(ymax-ymin or 1);ix=min(7,int(a*8));iy=min(5,int(b*6))
        distance=(a-(ix+.5)/8)**2+(b-(iy+.5)/6)**2;key=(ix,iy)
        if key not in cells or distance<cells[key][0]:cells[key]=(distance,r)
    candidates=[v[1] for k,v in sorted(cells.items())]
    if len(candidates)<=limit:return candidates
    chosen=[candidates[0]]
    def distance(a,b):return ((a[x]-b[x])/(xmax-xmin or 1))**2+((a[y]-b[y])/(ymax-ymin or 1))**2
    while len(chosen)<limit:
        next_row=max((r for r in candidates if r not in chosen),key=lambda r:min(distance(r,q) for q in chosen));chosen.append(next_row)
    return chosen


def export(model,data):
    b=bundle(model);rows,x,y,color=select(b,data)
    if not rows:raise ValueError('No simulations match these filters.')
    count=int(data.get('silhouettes',24))
    if not 0<=count<=60:raise ValueError('Choose 0 to 60 silhouette markers.')
    normalized=bool(data.get('normalized',False));mode=data.get('mode','points')
    if mode not in ('points','density'):raise ValueError('Unknown point display mode.')
    digest=hashlib.sha256(catalog.compact(['atlas-v1',data,[r['key'] for r in rows]]).encode()).hexdigest()[:12]
    dest=model.OUTPUTS/('wing-atlas-'+digest);dest.mkdir(exist_ok=True)
    import numpy as np
    from matplotlib.offsetbox import DrawingArea,AnnotationBbox
    from matplotlib.patches import Polygon
    from matplotlib.colors import Normalize
    from matplotlib.cm import ScalarMappable
    plt=model.ieee_style();fig,ax=plt.subplots(figsize=(7.16,4.8),layout='constrained')
    values=[r[color] for r in rows if finite(r.get(color))];vmin=min(values,default=0);vmax=max(values,default=1)
    norm=Normalize(vmin,vmax if vmax>vmin else vmin+1e-9);cmap=plt.get_cmap('viridis')
    if mode=='density':
        hb=ax.hexbin([r[x] for r in rows],[r[y] for r in rows],gridsize=50,mincnt=1,bins='log',cmap='Greys');fig.colorbar(hb,ax=ax,label='Simulations per hexagon (log count)',pad=.01)
    else:ax.scatter([r[x] for r in rows],[r[y] for r in rows],c=[r.get(color) if finite(r.get(color)) else np.nan for r in rows],cmap=cmap,norm=norm,s=5,alpha=.4,linewidths=0,rasterized=True)
    shown=sample(rows,x,y,count);extent=max((max(max(p[k] for p in r['outline'])-min(p[k] for p in r['outline']) for k in (0,1)) for r in rows),default=.4)
    for r in shown:
        poly=np.array(r['outline']);lo=poly.min(axis=0);hi=poly.max(axis=0);scale=24/(max(hi-lo) if normalized else extent);size=(hi-lo)*scale;vertices=(poly-lo)*scale;vertices[:,1]=size[1]-vertices[:,1]
        box=DrawingArea(max(size[0],1),max(size[1],1));box.add_artist(Polygon(vertices,facecolor=cmap(norm(r[color])) if finite(r.get(color)) else '#aaa',edgecolor='#4a4a4a',lw=.45))
        ax.add_artist(AnnotationBbox(box,(r[x],r[y]),frameon=False,pad=0,zorder=3))
    scope=rows[0]['load_scope'];ylabel=METRICS[y] if y!='thrust' else ('Mean single-wing thrust (N)' if scope=='single' else 'Mean paired-wing thrust (N)')
    ax.set(xlabel=METRICS[x],ylabel=ylabel,title=f"{len(rows):,} simulations · "+('mixed conditions overview' if len({r['cohort'] for r in rows})>1 else 'matched saved conditions'))
    ax.grid(alpha=.18);ax.margins(.04);fig.colorbar(ScalarMappable(norm=norm,cmap=cmap),ax=ax,label=METRICS[color],pad=.02)
    ax.text(.02,.98,'Silhouette sizes normalized' if normalized else 'Common physical silhouette scale',transform=ax.transAxes,va='top',fontsize=7)
    fig.savefig(dest/'all_tested_wings.png',dpi=600);plt.close(fig)
    fields=['number','study','id','geometry_id','simulation_id','cohort','load_scope','settled',*AXES,'chords','generations','studies','silhouette_shown',
        'frequency_hz','speed_mps','amplitude_deg','rho','nu','dt_s','cycles','span_panels','chord_panels','wake_model','wake_cycles','waveform']
    conditions_by_id={g['id']:g['conditions'] for g in b['cohorts']};shown_keys={r['key'] for r in shown}
    with (dest/'selected_simulations.csv').open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore');w.writeheader()
        for r in rows:w.writerow({**r,**conditions_by_id[r['cohort']],'silhouette_shown':r['key'] in shown_keys})
    return {'files':[str((dest/n).relative_to(model.OUTPUTS)).replace('\\','/') for n in ('all_tested_wings.png','selected_simulations.csv')],
        'count':len(rows),'cohorts':len({r['cohort'] for r in rows}),'silhouette_count':len(shown)}
