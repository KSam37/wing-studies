"""Area / thrust-to-peak-root-torque ratio / measured mean thrust comparison."""
import hashlib
import math
from wingstudy import catalog
from wingstudy import torque_study
from wingstudy.landscape_interpolation import interpolate
from wingstudy.wing_dimensions import dimensions

AXIS_PARAMETERS={
    'area_m2':'Single-wing area (m²)',
    'leading_edge_length_m':'Leading-edge length (m)',
    'single_wing_span_m':'Root-to-tip span (m)',
    'aspect_ratio':'Single-wing aspect ratio',
    catalog.OBJECTIVE:'Thrust / peak root torque (1/m)',
    'single_wing_peak_abs_roll_moment_Nm':'Peak wing-root torque (N m)',
    'single_wing_mean_thrust_N':'Mean single-wing thrust (N)'}
DEFAULT_AXES=['area_m2',catalog.OBJECTIVE,'single_wing_mean_thrust_N']

def data(model,rows,axes=None):
    axes=DEFAULT_AXES if axes is None else axes
    if not isinstance(axes,list) or len(axes)!=3 or any(not isinstance(k,str) or k not in AXIS_PARAMETERS for k in axes) or len(set(axes))!=3:
        raise ValueError('Choose three different supported parameters for the X, Y and Z axes.')
    points=[];conditions=set()
    for row in rows:
        area=row.get('area_m2');thrust=row.get('single_wing_mean_thrust_N');moment=row.get('single_wing_peak_abs_roll_moment_Nm')
        if not all(isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v) for v in (area,thrust,moment)) or area<=0 or moment<0:
            raise ValueError('Every selected wing needs finite area/thrust and nonnegative peak root torque.')
        ratio=thrust/moment if moment>0 else None
        values={**row,**dimensions(row),catalog.OBJECTIVE:ratio}
        if any(not isinstance(values.get(k),(int,float)) or isinstance(values[k],bool) or not math.isfinite(values[k]) for k in axes):
            raise ValueError('A selected axis value is missing or undefined (thrust/torque requires positive peak root torque).')
        if row.get('torque_status') not in ('Within limit','Over limit','No positive thrust','Eligible','Frontier'):
            raise ValueError('Select settled single-wing cases for the chosen native model with valid forces and moments.')
        key=row.get('comparison_key',row['id']);settings=row['_settings']
        points.append({'case_id':key,'coords':[values[k] for k in axes],'value':values[axes[2]],'area_m2':area,'aspect_ratio':row.get('aspect_ratio'),
            catalog.OBJECTIVE:ratio,**dimensions(row),
            'repeatable':bool(row.get('cycle_repeatable')),'thumbnail':model.wing_thumbnail(row,settings['gap_m']),
            'chords_m':[s['chord_m'] for s in row.get('sections',[])],
            'single_wing_mean_thrust_N':thrust,'single_wing_peak_abs_roll_moment_Nm':row['single_wing_peak_abs_roll_moment_Nm'],
            'global_case_no':row.get('global_case_no'),'source_study':row['_study'],'source_case':row['id']})
        conditions.add(catalog.compact(catalog.physical_settings(settings)))
    if not points:raise ValueError('No measured cases match the 3D filters.')
    vertices,triangles,curve,kind,selected=interpolate(points)
    compatible=len(conditions)==1 and all(r.get('_verified',False) for r in rows)
    if not compatible:triangles=[];curve=[];kind='points'
    note=('Measured points only: driving/solver settings differ or provenance is unverified. Filter to one consistent study to enable interpolation.' if not compatible else
        'Smooth bounded surface inside the measured X/Y convex hull only; no extrapolation. Each patch stays within its measured corner Z values.' if triangles else
        'Smooth bounded curve through measured locations.' if curve else 'Measured points only; more distinct locations are needed for interpolation.')
    note+=' Color follows Z. Leading-edge length follows the active 3D section segments, excluding removed zero-chord tips. Torque is the peak absolute moment at one wing root. Duplicate X/Y locations use the highest measured Z for interpolation; rankings are unchanged.'
    stem='wing_area_ratio_thrust' if axes==DEFAULT_AXES else 'wing_landscape_'+hashlib.sha256(catalog.compact(axes).encode()).hexdigest()[:8]
    return {'axes':axes,'axis_labels':[AXIS_PARAMETERS[k] for k in axes],
        'color_label':AXIS_PARAMETERS[axes[2]],'value_key':axes[2],'export_stem':stem,
        'points':points,'vertices':vertices.tolist(),'triangles':triangles,'curve':curve,'interpolation_kind':kind,
        'vertex_case_ids':[points[i]['case_id'] for i in selected] if compatible else [],
        'distinct_locations':len(selected),'duplicate_locations':len(points)-len(selected),'note':note}


def generate(model,request):
    limit=request.get('maximum_root_moment_nm');study=request.get('study')
    if request.get('full_range',False):
        report=torque_study.overview(model,study,request.get('generations',['current']),request.get('model_mode','rigid'),span_class=request.get('span_class','all'))
        if study!='master':
            manifest=model.read_json(model.OUTPUTS/study/'manifest.json');verified=catalog.verified_import(model,manifest)
            for row in report['rows']:row['_verified']=verified
    elif study=='master':
        report=torque_study.master_results(model,request.get('generations',['current']),limit,model_mode=request.get('model_mode','rigid'))
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
    rows=[lookup[key] for key in keys];spec=data(model,rows,request.get('axes'))
    digest=hashlib.sha256(catalog.compact([spec['axes'],[(p['source_study'],p['source_case'],p['coords']) for p in spec['points']]]).encode()).hexdigest()[:16]
    directory=model.OUTPUTS/('thrust-landscape-'+digest)
    export_rows=[{**row,'id':row.get('comparison_key',row['id'])} for row in rows]
    return model.shape_landscape(directory,True,True,selected_rows=export_rows,selected_spec=spec)
