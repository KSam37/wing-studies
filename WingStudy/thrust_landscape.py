"""Area / single-wing aspect ratio / measured mean thrust comparison."""
import hashlib
import json
import math
import numpy as np
import catalog
import torque_study
from landscape_interpolation import interpolate


def data(model,rows):
    points=[];conditions=set()
    for row in rows:
        area=row.get('area_m2');aspect=row.get('aspect_ratio');thrust=row.get('single_wing_mean_thrust_N')
        if not all(isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v) for v in (area,aspect,thrust)) or area<=0 or aspect<=0:
            raise ValueError('Every selected wing needs finite single-wing area, aspect ratio and thrust.')
        if row.get('torque_status') not in ('Within limit','Over limit','No positive thrust'):
            raise ValueError('Select settled rigid single-wing cases with valid forces and moments.')
        key=row.get('comparison_key',row['id']);settings=row['_settings']
        points.append({'case_id':key,'coords':[area,aspect,thrust],'value':thrust,'aspect_ratio':aspect,
            'repeatable':bool(row.get('cycle_repeatable')),'thumbnail':model.wing_thumbnail(row,settings['gap_m']),
            'chords_m':[s['chord_m'] for s in row.get('sections',[])],
            'single_wing_mean_thrust_N':thrust,'single_wing_peak_abs_roll_moment_Nm':row['single_wing_peak_abs_roll_moment_Nm'],
            'global_case_no':row.get('global_case_no'),'source_study':row['_study'],'source_case':row['id']})
        conditions.add(catalog.compact(catalog.physical_settings(settings)))
    if not points:raise ValueError('No measured cases match the 3D filters.')
    spans2=np.array([p['coords'][0]*p['coords'][1] for p in points])
    fixed_span=bool(np.allclose(spans2,spans2[0],rtol=1e-8,atol=1e-14))
    vertices,triangles,curve,kind,selected=interpolate(points,force_curve=fixed_span)
    if fixed_span and curve:
        # The descriptor relation is exact: single-wing AR = length² / area.
        for vertex in curve:vertex[1]=float(spans2[0]/vertex[0])
    compatible=len(conditions)==1 and all(r.get('_verified',False) for r in rows)
    if not compatible:triangles=[];curve=[];kind='points'
    note=('Measured points only: driving/solver settings differ or provenance is unverified. Filter to one consistent study to enable interpolation.' if not compatible else
        'Fixed-span data: area and aspect ratio are linked. A smooth bounded 3D curve follows the measured upper thrust envelope; no surface is invented.' if fixed_span else
        'Smooth bounded surface inside the measured convex hull only; no extrapolation. Each patch stays within its measured corner thrust values.' if triangles else
        'Smooth bounded curve through measured locations.' if curve else 'Measured points only; more distinct locations are needed for interpolation.')
    note+=' Every wing marker is a measured case. Interpolation does not create simulations or affect rankings. Duplicate area/AR locations use the highest measured thrust for interpolation.'
    return {'axes':['area_m2','aspect_ratio','single_wing_mean_thrust_N'],
        'axis_labels':['Single-wing area (m²)','Single-wing aspect ratio','Mean single-wing thrust (N)'],
        'color_label':'Mean single-wing thrust (N)','value_key':'single_wing_mean_thrust_N','export_stem':'wing_area_aspect_thrust',
        'points':points,'vertices':vertices.tolist(),'triangles':triangles,'curve':curve,'interpolation_kind':kind,
        'vertex_case_ids':[points[i]['case_id'] for i in selected] if compatible else [],
        'distinct_locations':len(selected),'duplicate_locations':len(points)-len(selected),'note':note,'fixed_span':fixed_span}


def generate(model,request):
    limit=request['maximum_root_moment_nm'];study=request.get('study')
    if study=='master':
        report=torque_study.master_results(model,request.get('generations',['current']),limit)
    else:
        # The route resolves/validates the study path before entering this function.
        directory=model.OUTPUTS/study;manifest=model.read_json(directory/'manifest.json')
        report=torque_study.results(model,directory,limit)
        verified=catalog.verified_import(model,manifest)
        for row in report['rows']:
            row.update(_study=study,_settings=manifest['settings'],_verified=verified)
    keys=request.get('case_keys')
    if not isinstance(keys,list) or not keys or len(keys)>10000 or any(not isinstance(k,str) for k in keys) or len(set(keys))!=len(keys):
        raise ValueError('Choose 1–10,000 distinct measured cases for the 3D plot.')
    lookup={r.get('comparison_key',r['id']):r for r in report['rows']}
    if any(key not in lookup for key in keys):raise ValueError('The selected cases changed. Refresh the comparison and try again.')
    rows=[lookup[key] for key in keys];spec=data(model,rows)
    digest=hashlib.sha256(catalog.compact([(p['source_study'],p['source_case'],p['coords']) for p in spec['points']]).encode()).hexdigest()[:16]
    directory=model.OUTPUTS/('thrust-landscape-'+digest)
    export_rows=[{**row,'id':row.get('comparison_key',row['id'])} for row in rows]
    return model.shape_landscape(directory,True,True,selected_rows=export_rows,selected_spec=spec)
