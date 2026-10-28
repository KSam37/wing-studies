"""Bounded smooth local geometry search and explicit winner-only retention.

Interpolation creates ordinary native Ptera sections. No solver or material
model is changed. The local sample is reproducible, not an exhaustive optimum.
"""
import copy
import csv
import json
import os
from pathlib import Path
import shutil
import uuid


def resize_span(model,design,total_span_m,settings):
    """Stretch only spanwise positions; preserve every active chord exactly."""
    gap=model.number(settings.get('gap_m'),'Hinge gap',0)
    total=model.number(total_span_m,'Total span',gap+1e-12)
    original=model.custom_case(design,{**settings,'span_panels':max(settings['span_panels'],len(design.get('sections',[]))-1)})
    sections=original['sections'];factor=(total-gap)/(2*sections[-1]['y_m'])
    resized={**copy.deepcopy(design),'name':design.get('name','Resized wing'),
        'sections':[{**s,'y_m':s['y_m']*factor} for s in sections]}
    resized.pop('outline_function',None);resized.pop('curve_fit',None)
    model.custom_case(resized,{**settings,'span_panels':max(settings['span_panels'],len(sections)-1)})
    return {'baseline':resized,'total_span_m':total,'single_wing_span_m':(total-gap)/2,'span_scale_factor':factor}


def resample(model,design,count,variation_pct,settings,linspace=False):
    import numpy as np
    from scipy.interpolate import PchipInterpolator
    count=model.number(count,'Refinement chord nodes',2,64,True)
    variation=model.number(variation_pct,'Local chord variation (%)',0,100)/100
    original=model.custom_case(design,{**settings,'span_panels':max(settings['span_panels'],len(design.get('sections',[]))-1)})
    source=original['sections']  # Absent zero suffixes must not extend the wing.
    y=np.array([s['y_m'] for s in source]);new_y=np.linspace(y[0],y[-1],count)
    fields={key:PchipInterpolator(y,[s[key] for s in source])(new_y) for key in ('x_m','chord_m','pitch_deg','roll_deg')}
    sections=[{'y_m':float(v),**{key:float(values[i]) for key,values in fields.items()}} for i,v in enumerate(new_y)]
    return {'baseline':{'name':design.get('name','Refined wing'),'sections':sections},
        'ranges':[{'min_m':s['chord_m']*(1 if linspace else 1-variation),'max_m':s['chord_m']*(1 if linspace else 1+variation),'count':1} for s in sections],
        'required_span_panels':max(settings['span_panels'],count-1)}


def designs(model,config):
    """Smooth, correlated local perturbations within every editable node bound."""
    import numpy as np
    from scipy.ndimage import gaussian_filter1d
    raw=config['refinement'];shape=config['shape_sweep'];base=shape.get('baseline')
    if not isinstance(base,dict):raise ValueError('Choose a baseline wing before local refinement.')
    sections=base.get('sections',[]);n=len(sections)
    if not 2<=n<=64 or len(shape.get('ranges',[]))!=n:raise ValueError('Provide one chord bound for every refinement node (2–64).')
    count=model.number(raw.get('candidates',41),'Local candidate count',1,10000,True)
    budget=model.number(config['settings']['case_budget'],'Case budget',1,None,True)
    if count>budget:raise ValueError('Local candidate count exceeds the case budget.')
    seed=model.number(raw.get('seed',7),'Local search seed',0,2**32-1,True)
    lo=[];hi=[]
    for i,r in enumerate(shape['ranges']):
        a=model.number(r.get('min_m'),f'Chord {i+1} minimum',0)
        b=model.number(r.get('max_m'),f'Chord {i+1} maximum',a)
        lo.append(a);hi.append(b)
    lo=np.array(lo);hi=np.array(hi);chord=np.array([s['chord_m'] for s in sections])
    if not np.isfinite(chord).all() or np.any(chord<lo-1e-12) or np.any(chord>hi+1e-12):
        raise ValueError('Local bounds must include every baseline chord; change bounds or reapply the node count.')
    decreasing=shape.get('decreasing',False)
    if not isinstance(decreasing,bool):raise ValueError('Decreasing chord selection must be true/false.')
    rng=np.random.default_rng(seed);unique={};sigma=max(1.,n/6)
    centers=np.linspace(0,n-1,min(n,max(1,(count-3)//4)))
    for attempt in range(max(100,count*80)):
        if attempt==0:offset=np.zeros(n)
        elif attempt<=2:offset=np.full(n,1. if attempt==1 else -1.)
        elif attempt<=2+2*len(centers):
            index=centers[(attempt-3)//2]
            offset=np.exp(-.5*((np.arange(n)-index)/sigma)**2)*(1 if attempt%2 else -1)
        else:
            offset=gaussian_filter1d(rng.uniform(-1,1,n),sigma,mode='nearest')
            offset/=max(float(np.max(np.abs(offset))),1e-12)
        values=chord+offset*np.where(offset>=0,hi-chord,chord-lo)
        values=np.clip(values,lo,hi)
        # Reject rather than distort a smooth curve to enforce taper/zero rules.
        if decreasing and np.any(np.diff(values)>1e-12):continue
        zero=np.flatnonzero(values==0)
        if len(zero) and (zero[0]<2 or np.any(values[zero[0]:]!=0)):continue
        key=tuple(float(v) for v in values)
        if key not in unique:
            unique[key]={'name':f"Local {len(unique)+1:04d}",
                'sections':[{**s,'chord_m':float(v)} for s,v in zip(sections,values)]}
        if len(unique)>=count:break
        if np.array_equal(lo,hi):break
    if not unique:raise ValueError('No local shapes satisfy the node bounds and decreasing-chord constraint.')
    return list(unique.values())


def recycle(paths,root):
    """Windows recoverable removal, restricted to the application's staging area."""
    import ctypes
    from ctypes import wintypes
    root=Path(root).resolve();paths=[Path(p).resolve() for p in paths]
    if any(p==root or not p.is_relative_to(root) or not p.exists() for p in paths):
        raise ValueError('Discard targets must exist within the retention staging folder.')
    if os.name!='nt':raise OSError('Winner-only cleanup requires the Windows Recycle Bin.')
    class Operation(ctypes.Structure):
        _fields_=[('hwnd',wintypes.HWND),('wFunc',wintypes.UINT),('pFrom',wintypes.LPCWSTR),
            ('pTo',wintypes.LPCWSTR),('fFlags',wintypes.WORD),('aborted',wintypes.BOOL),
            ('mappings',ctypes.c_void_p),('title',wintypes.LPCWSTR)]
    source=ctypes.create_unicode_buffer('\0'.join(str(p) for p in paths)+'\0\0')
    op=Operation(None,3,ctypes.cast(source,wintypes.LPCWSTR),None,0x40|0x10|0x4|0x400,False,None,None)
    function=ctypes.windll.shell32.SHFileOperationW
    function.argtypes=[ctypes.POINTER(Operation)];function.restype=ctypes.c_int
    error=function(ctypes.byref(op))
    if error or op.aborted:raise OSError(f'Recycle Bin cleanup did not finish (code {error}). The original study remains in {root}.')


def keep_best(model,study,limit,expected_id):
    """Keep one finished refinement winner; preserve external catalog references."""
    import catalog
    import torque_study
    study=Path(study).resolve()
    if study.parent!=model.OUTPUTS.resolve():raise ValueError('Choose a study in this output folder.')
    manifest=model.read_json(study/'manifest.json');status=model.read_json(study/'status.json')
    if not manifest['config'].get('refinement',{}).get('enabled'):raise ValueError('Keep best only is available for local refinement studies.')
    if status.get('state') not in ('complete','complete_with_errors'):raise ValueError('Wait for the refinement run to finish before keeping its best wing.')
    report=torque_study.results(model,study,limit)
    winner=report['winner']
    if not winner:raise ValueError('No settled, feasible wing meets the root-moment cap. Nothing was discarded.')
    if winner['id']!=expected_id:raise ValueError('The best wing changed. Refresh the comparison before saving it.')
    keep=winner['id'];cases=manifest['cases'];chosen=next(c for c in cases if c['id']==keep)
    with catalog.connect(model) as db:
        boundary=db.execute("SELECT value FROM meta WHERE key='archive_studies'").fetchone()
        if boundary and study.name in json.loads(boundary[0]):raise ValueError('The Old catalog is preserved. Create a new local refinement first.')
    # Build the complete retained study before touching the original directory.
    maintenance=catalog.root(model)/'maintenance';maintenance.mkdir(exist_ok=True)
    job=maintenance/('retain-'+uuid.uuid4().hex);job.mkdir()
    staged=job/'kept';staged.mkdir();(staged/'comparisons').mkdir()
    shutil.copytree(study/keep,staged/keep)
    saved=copy.deepcopy(manifest['config'])
    saved.update(name=(manifest['name']+' best')[:80],mode='custom',designs=[{'name':chosen.get('design_name',keep),'sections':chosen['sections']}])
    saved.pop('refinement',None)
    saved['optimization']['max_root_moment_nm']=limit
    model.write_json(staged/'best_wing_settings.json',saved)
    retained=copy.deepcopy(manifest)
    retained.update(cases=[chosen],case_count=1,retention={'kept_case':keep,'original_case_count':len(cases),
        'root_moment_limit_nm':limit,'saved_utc':catalog.stamp()})
    retained['config']['optimization']['max_root_moment_nm']=limit
    model.write_json(staged/'manifest.json',retained)
    original_rows=model.read_json(study/'results.json');row=next(r for r in original_rows if r['id']==keep)
    model.write_summary(staged,[row])
    with (study/'comparisons/time_histories.csv').open(newline='',encoding='utf-8') as src, (staged/'comparisons/time_histories.csv').open('w',newline='',encoding='utf-8') as dst:
        reader=csv.reader(src);writer=csv.writer(dst);writer.writerow(next(reader))
        writer.writerows(values for values in reader if values[0]==keep)
    model.write_json(staged/'status.json',{'state':'complete','total':1,'completed':1,'message':'Best feasible wing saved; other refinement cases discarded.'})
    # Keep stable numbers, rehome any original result still used by another study.
    with catalog.connect(model) as db:
        db.execute('BEGIN IMMEDIATE')
        entries=list(db.execute('SELECT DISTINCT c.* FROM cases c JOIN occurrences o USING(case_no) WHERE o.study=? AND o.local_case<>?',(study.name,keep)))
        for entry in entries:
            if entry['origin_study']!=study.name:continue
            others=list(db.execute('SELECT * FROM occurrences WHERE case_no=? AND study<>?',(entry['case_no'],study.name)))
            if others:
                replacement=next((o for o in others if catalog.available(model,{**dict(entry),'origin_study':o['study'],'origin_case':o['local_case']})),None)
                if replacement is None:raise ValueError('Another study references a discarded case without its own complete outputs. Nothing was discarded.')
                origin=model.OUTPUTS/replacement['study'];m=model.read_json(origin/'manifest.json')
                case=next(c for c in m['cases'] if c['id']==replacement['local_case'])
                result=next(r for r in model.read_json(origin/'results.json') if r['id']==case['id'])
                payload=json.loads(entry['payload']);payload.update(case=case,settings=m['settings'],study_name=m['name'])
                db.execute('UPDATE cases SET origin_study=?,origin_case=?,payload=?,result=? WHERE case_no=?',
                    (origin.name,case['id'],catalog.compact(payload),catalog.compact(result),entry['case_no']))
        db.execute('DELETE FROM occurrences WHERE study=? AND local_case<>?',(study.name,keep))
        db.execute('DELETE FROM cases WHERE origin_study=? AND case_no NOT IN (SELECT case_no FROM occurrences)',(study.name,))
        db.execute('DELETE FROM imports WHERE study=?',(study.name,))
        original=job/'discarded'
        os.replace(study,original)
        try:os.replace(staged,study)
        except OSError:
            os.replace(original,study);raise
    cleanup='Other case files sent to the Recycle Bin.'
    try:recycle([original],job)
    except OSError as exc:cleanup=str(exc)  # Never destroy the fallback copy.
    catalog.sync(model);catalog.export(model,metric='single_wing_mean_thrust_N')
    torque_study.results(model,study,limit,export=True)
    return {'kept_case':keep,'discarded_count':len(cases)-1,'settings_file':f'{study.name}/best_wing_settings.json','cleanup':cleanup}
