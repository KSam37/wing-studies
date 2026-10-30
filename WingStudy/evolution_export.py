"""Export the recorded ancestry of a selected wing, never later descendants."""
import hashlib
import io
import math
import re
from pathlib import Path


def lineage(model,study,case_id):
    if not re.fullmatch(r'case_\d{4,}',case_id):raise ValueError('Invalid case identifier.')
    study=Path(study)
    rows=model.read_json(study/'results.json') if (study/'results.json').exists() else []
    lookup={r['id']:r for r in rows}
    if case_id not in lookup:raise ValueError('Selected case has no completed result yet.')
    events=model.read_json(study/'evolution.json') if (study/'evolution.json').exists() else []
    hits=[i for i,e in enumerate(events) if e.get('case',{}).get('id')==case_id]
    if hits and (events[hits[-1]].get('search_algorithm')=='independent_coordinate_v1' or
            lookup[case_id].get('adaptive_trial',{}).get('objective')!='pareto_mean_thrust_peak_root_torque_v1'):
        end=hits[-1];job=events[end]['job']
        path=[e['case'] for e in events[:end+1] if e['job']==job]
    else:
        path=[];seen=set();current=case_id
        while current:
            if current in seen:raise ValueError('Recorded ancestry contains a cycle.')
            seen.add(current)
            if current not in lookup:raise ValueError('Recorded ancestry is incomplete for this wing.')
            row=lookup[current];path.append(row)
            meta=row.get('adaptive_trial')
            if not isinstance(meta,dict):raise ValueError('No adaptive design history was recorded for this wing.')
            current=meta.get('parent_case')
        path.reverse()
    unique=[]
    for row in path:
        if not unique or unique[-1]['id']!=row['id']:unique.append(row)
    if not unique or unique[-1]['id']!=case_id:raise ValueError('Recorded path does not end at the selected wing.')
    return unique


def export_gif(model,study,case_id):
    import numpy as np
    from PIL import Image
    study=Path(study);path=lineage(model,study,case_id)
    indices=np.unique(np.linspace(0,len(path)-1,min(len(path),200),dtype=int))
    shown=[path[i] for i in indices]
    polygons=[]
    for row in shown:
        if not row.get('sections'):raise ValueError('Recorded section geometry is unavailable.')
        positions,frames=model.custom_frames(row)
        positions=np.asarray(positions)
        trail=np.asarray([p+r@np.array([s['chord_m'],0.,0.]) for p,r,s in zip(positions,frames,row['sections'])])
        polygons.append(np.vstack([positions[:,[1,0]],trail[::-1][:,[1,0]]]))
    all_points=np.vstack(polygons);lo=all_points.min(axis=0);hi=all_points.max(axis=0)
    pad=max(float(np.max(hi-lo))*.06,.002)
    plt=model.ieee_style();images=[]
    def value(x):return f'{x:.4g}' if isinstance(x,(int,float)) and math.isfinite(x) else 'unavailable'
    for index,row,polygon in zip(indices,shown,polygons):
        fig,ax=plt.subplots(figsize=(6,3.6),layout='constrained')
        ax.fill(polygon[:,0],polygon[:,1],facecolor='#a7d8d0',edgecolor='#007f78',lw=1.2)
        ax.set(xlim=(lo[0]-pad,hi[0]+pad),ylim=(hi[1]+pad,lo[1]-pad),xlabel='Root-to-tip position (m)',ylabel='Chord direction (m)')
        ax.set_aspect('equal');ax.grid(alpha=.15)
        thrust=row.get('single_wing_mean_thrust_N');torque=row.get('single_wing_peak_abs_roll_moment_Nm')
        ratio=thrust/torque if isinstance(thrust,(int,float)) and isinstance(torque,(int,float)) and torque>1e-9 else None
        ax.set_title(f"Design evolution to {case_id} · state {index+1}/{len(path)} · {row['id']}\nThrust {value(thrust)} N · peak torque {value(torque)} N m · ratio {value(ratio)} 1/m",fontsize=9)
        buffer=io.BytesIO();fig.savefig(buffer,format='png',dpi=100);plt.close(fig)
        images.append(Image.open(buffer).convert('RGB'))
    dest=study/'comparisons';dest.mkdir(exist_ok=True)
    digest=hashlib.sha256(str([(r['id'],r['sections']) for r in path]).encode()).hexdigest()[:10]
    file=dest/f'evolution_{case_id}_{digest}.gif'
    temporary=file.with_suffix('.gif.tmp')
    images[0].save(temporary,format='GIF',save_all=True,append_images=images[1:],duration=500,loop=0,disposal=2)
    temporary.replace(file)
    for frame in images:frame.close()
    return {'file':str(file.relative_to(model.OUTPUTS)).replace(chr(92),'/'),'case_ids':[r['id'] for r in path],
        'frame_count':len(shown),'recorded_states':len(path),'note':('Starting seed: one recorded state.' if len(path)==1 else 'Recorded design path ending at the selected wing.')+(' Animation sampled to 200 frames; recorded history is unchanged.' if len(path)>200 else '')}
