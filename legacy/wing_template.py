"""Full-size fabric cutting frames: inward rim, chord ribs, chord-centered seams.

Fabrication only. Does not smooth saved section geometry, replace the tip, alter
simulation records, or invoke Ptera. STL coordinates are millimeters.
"""
import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile
import zipfile

WIDTH=2.0
HEIGHT=3.0
BED=250.0
MARGIN=1.0
CURVE_TOLERANCE=.02
JOINT_AMPLITUDE=.35
JOINT_PITCH=6.
JOINT_END=3.
VERSION='chord-split-template-v2-zigzag'


def _curve_pattern(case):
    import numpy as np
    from wingstudy.wing_curves import unpack_curve
    f=case['outline_function'];span=f['span_m'];anchors=f['anchors']
    if any(abs(s.get('pitch_deg',0))>1e-10 for s in f['sample_sections']):
        raise ValueError('This smooth wing has nonzero section pitch and no verified flat cutting pattern. A seam/strain design is needed before making a template.')
    leading=unpack_curve(f['leading']);chord=unpack_curve(f['chord'])
    ts=np.array([s['y_m']/span for s in anchors]);factors=1/np.cos(np.radians([s.get('roll_deg',0) for s in anchors[:-1]]))
    distances=np.r_[0.,np.cumsum(np.diff(ts)*span*factors)]
    def flat(t):return float(np.interp(t,ts,distances))*1000
    def bisect(p):
        a=(p[:-1]+p[1:])/2;b=(a[:-1]+a[1:])/2;c=(b[0]+b[1])/2
        return np.array([p[0],a[0],b[0],c]),np.array([c,b[1],a[2],p[3]])
    def error(p):
        v=p[-1]-p[0];length=np.linalg.norm(v)
        if length<1e-12:return float(np.max(np.linalg.norm(p-p[0],axis=1)))
        fraction=np.clip((p-p[0])@v/(length*length),0,1)
        return float(np.max(np.linalg.norm(p-(p[0]+fraction[:,None]*v),axis=1)))
    def sample(a,b,depth=0):
        if max(error(a),error(b))<=CURVE_TOLERANCE:return [a[-1]],[b[-1]]
        if depth>=20:raise ValueError('Smooth outline is too complex to resolve safely for printing.')
        al,ar=bisect(a);bl,br=bisect(b);l1,t1=sample(al,bl,depth+1);l2,t2=sample(ar,br,depth+1)
        return l1+l2,t1+t2
    bays=[];chords=[]
    for i,(start,stop) in enumerate(zip(ts,ts[1:])):
        knots=sorted(set([start,stop,*[t for t in [*leading.x,*chord.x] if start<t<stop]]))
        le=[np.array([flat(start),float(leading(start))*1000])]
        te=[np.array([flat(start),float(leading(start)+chord(start))*1000])]
        if i==0:chords.append((le[0].tolist(),te[0].tolist()))
        for a,b in zip(knots,knots[1:]):
            h=(b-a)/3;slope=span*factors[i]*1000;curves=[]
            for edge in (0,1):
                def value(t):return float(leading(t)+edge*chord(t))*1000
                def deriv(t):return float(leading.derivative()(t)+edge*chord.derivative()(t))*1000
                curves.append(np.array([[flat(a),value(a)],[flat(a)+h*slope,value(a)+h*deriv(a)],
                    [flat(b)-h*slope,value(b)-h*deriv(b)],[flat(b),value(b)]]))
            l,t=sample(*curves);le.extend(l);te.extend(t)
        bays.append([p.tolist() for p in [*le,*te[::-1]]]);chords.append((le[-1].tolist(),te[-1].tolist()))
    return bays,chords,'Saved smooth function; adaptive cubic flattening ≤ 0.02 mm control-hull deviation.'


def pattern(model,case,settings):
    """Return contiguous flat bays and actual section endpoints, all in mm."""
    if case.get('outline_function'):return _curve_pattern(case)
    leading,trailing=model.flat_pattern(case,settings)
    le=[[float(p[1])*1000,float(p[0])*1000] for p in leading]
    te=[[float(p[1])*1000,float(p[0])*1000] for p in trailing]
    return [[le[i],le[i+1],te[i+1],te[i]] for i in range(len(le)-1)],list(zip(le,te)),'Exact saved section edges; planar strips unfolded without stretch.'


def bed_layout(poly,limit=BED-2*MARGIN):
    """Keep original orientation if possible; otherwise find a square-bed rotation."""
    from shapely.affinity import rotate,translate
    from scipy.optimize import minimize_scalar
    def extent(angle):
        p=rotate(poly,angle,origin=(0,0));b=p.bounds
        return max(b[2]-b[0],b[3]-b[1])
    angle=0.
    if extent(angle)>limit+1e-8:
        coarse=min(range(91),key=extent)
        solution=minimize_scalar(extent,bounds=(max(0,coarse-1),min(90,coarse+1)),method='bounded')
        angle=min((float(coarse),float(solution.x)),key=extent)
        if extent(angle)>limit+1e-7:return None
    rotated=rotate(poly,angle,origin=(0,0));lo=rotated.bounds[:2]
    return translate(rotated,xoff=-lo[0],yoff=-lo[1]),angle,[-lo[0],-lo[1]]


def zigzag_joint(left,right,frame,a,b):
    """Transfer alternating triangular lobes across a chord-centered seam.

    The assembled frame is unchanged; teeth stay inside its existing 2 mm rib.
    Ends remain straight to preserve the cutting rim. Exact mating faces, no gap.
    """
    import numpy as np
    from shapely.geometry import Polygon
    a=np.asarray(a,dtype=float);b=np.asarray(b,dtype=float);length=float(np.linalg.norm(b-a))
    u=(b-a)/length;n=np.array([-u[1],u[0]])
    usable=length-2*JOINT_END
    if usable<4:return left,right,{'active':False,'reason':'Chord too short for printable teeth.','points':[a.tolist(),b.tolist()]}
    cycles=max(1,int(usable/JOINT_PITCH));pitch=usable/cycles
    stations=[(0.,0.),(JOINT_END,0.)]
    for i in range(cycles):
        start=JOINT_END+i*pitch
        stations.extend([(start+pitch/4,JOINT_AMPLITUDE),(start+pitch/2,0.),
            (start+3*pitch/4,-JOINT_AMPLITUDE),(start+pitch,0.)])
    stations.append((length,0.))
    points=[(a+t*u+offset*n).tolist() for t,offset in stations]
    for (t0,d0),(t1,d1) in zip(stations,stations[1:]):
        if abs(d0)+abs(d1)<1e-12:continue
        region=Polygon([a+t0*u,a+t1*u,a+t1*u+d1*n,a+t0*u+d0*n]).intersection(frame)
        if region.area<1e-10:continue
        la=left.intersection(region).area;ra=right.intersection(region).area
        if min(la,ra)>max(1e-8,region.area*1e-8):raise ValueError('A joint tooth crossed another seam.')
        if la>ra:left=left.difference(region);right=right.union(region)
        else:right=right.difference(region);left=left.union(region)
    if any(p.geom_type!='Polygon' or not p.is_valid for p in (left,right)):
        raise ValueError('Zigzag joint did not produce connected valid print parts.')
    return left,right,{'active':True,'points':points,'amplitude_mm':JOINT_AMPLITUDE,
        'pitch_mm':pitch,'cycles':cycles,'straight_end_mm':JOINT_END,
        'minimum_nominal_half_rib_mm':WIDTH/2-JOINT_AMPLITUDE,'clearance_mm':0.}


def build(model,case,settings):
    from shapely.geometry import Polygon,LineString
    from shapely.ops import unary_union
    bays,chords,method=pattern(model,case,settings)
    # Collapse sub-nanometer arithmetic residue at mathematically zero tips.
    bays=[[(round(x,9),round(y,9)) for x,y in bay] for bay in bays]
    chords=[tuple((round(x,9),round(y,9)) for x,y in line) for line in chords]
    zones=[Polygon(b) for b in bays]
    if not zones or any(not p.is_valid or p.area<=1e-9 for p in zones):raise ValueError('Wing sections do not form valid positive-area cutting panels.')
    outer=unary_union(zones)
    if outer.geom_type!='Polygon' or not outer.is_valid or len(outer.interiors):raise ValueError('The wing has a disconnected or overlapping flat cutting outline.')
    if abs(sum(p.area for p in zones)-outer.area)>max(1e-5,outer.area*1e-9):raise ValueError('Unfolded section panels overlap; no printable fabric template can be inferred.')
    rim=outer.difference(outer.buffer(-WIDTH,join_style='mitre'))
    ribs=[LineString([a,b]).buffer(WIDTH/2,cap_style='flat',join_style='mitre') for a,b in chords if math.dist(a,b)>1e-8]
    frame=unary_union([rim,*ribs]).intersection(outer)
    if frame.geom_type!='Polygon' or not frame.is_valid:raise ValueError('The template frame is disconnected.')
    full_layout=bed_layout(frame)
    parts=[{'start':0,'end':len(zones),'polygon':frame,'layout':full_layout}] if full_layout is not None else []
    start=len(zones) if parts else 0
    while start<len(zones):
        best=None
        for end in range(start+1,len(zones)+1):
            region=unary_union(zones[start:end]);part=frame.intersection(region)
            if part.geom_type!='Polygon' or part.area<1e-8:break
            # Reserve room for teeth projecting beyond either straight cut.
            layout=bed_layout(part,limit=BED-2*MARGIN-2*JOINT_AMPLITUDE)
            if layout is None:break
            best=(end,part,layout)
        if best is None:raise ValueError(f'Chord bay {start+1} cannot fit the 250 × 250 mm bed even after rotation. Add chord sections or reduce the geometry; this exporter only splits at existing chords.')
        end,part,layout=best;parts.append({'start':start,'end':end,'polygon':part,'layout':layout});start=end
    joints=[]
    for i in range(len(parts)-1):
        chord=parts[i]['end'];a,b=chords[chord]
        left,right,joint=zigzag_joint(parts[i]['polygon'],parts[i+1]['polygon'],frame,a,b)
        parts[i]['polygon']=left;parts[i+1]['polygon']=right
        joints.append({**joint,'chord':chord+1,'part_numbers':[i+1,i+2]})
    for part in parts:
        part['layout']=bed_layout(part['polygon'])
        if part['layout'] is None:raise ValueError('A zigzag print part exceeds the print bed.')
    union=unary_union([p['polygon'] for p in parts]);error=union.symmetric_difference(frame).area
    overlap=sum(p['polygon'].area for p in parts)-union.area
    if error>max(1e-5,frame.area*1e-9) or overlap>1e-5:raise ValueError('Split verification failed: pieces do not exactly reconstruct the frame.')
    # Teeth vary the nominal 1 mm half-rib, leaving at least 0.65 mm per side.
    # Both sides remain full height and reconstruct the original 2 mm rib.
    return {'outer':outer,'frame':frame,'parts':parts,'chords':chords,'method':method,
        'joints':joints,'reconstruction_error_mm2':error,'overlap_mm2':overlap}


def export(model,study,case_id):
    try:import trimesh
    except ImportError as exc:raise ValueError('STL export needs the CAD dependencies. Run Setup Windows.cmd once to install them.') from exc
    if not re.fullmatch(r'case_\d{4,}',case_id):raise ValueError('Choose a valid saved wing case.')
    study=Path(study);manifest=model.read_json(study/'manifest.json')
    case=next((c for c in manifest['cases'] if c['id']==case_id),None)
    if not case or not (study/case_id).is_dir():raise ValueError('This wing has no saved case output directory.')
    fingerprint=hashlib.sha256(json.dumps([VERSION,case,manifest['settings'].get('gap_m'),WIDTH,HEIGHT,BED,MARGIN],sort_keys=True).encode()).hexdigest()
    dest=study/case_id/'template_stl';meta=dest/'template.json';zip_path=dest/'wing_template_stl.zip'
    def response(report):
        return {'file':str(zip_path.relative_to(model.OUTPUTS)).replace('\\','/'),
            'preview':str((dest/'assembly.png').relative_to(model.OUTPUTS)).replace('\\','/'),
            'part_count':len(report['parts']),'parts':report['parts'],
            'note':f"{len(report['parts'])} STL part(s), millimeters, 2 mm lines × 3 mm high. Matching zigzag chord joints align the pieces; glue in numbered order. Flip the assembled single-wing template for its mirror."}
    if meta.is_file() and zip_path.is_file() and zipfile.is_zipfile(zip_path):
        record=model.read_json(meta)
        if record.get('fingerprint')==fingerprint:return response(record)
    built=build(model,case,manifest['settings']);report={'version':VERSION,'fingerprint':fingerprint,
        'source_study':study.name,'source_case':case_id,'units':'mm','line_width_mm':WIDTH,'height_mm':HEIGHT,
        'bed_mm':[BED,BED],'usable_bed_mm':[BED-2*MARGIN]*2,'method':built['method'],
        'rim_placement':'inward; outer edge is the exact cutting line','seam':'Matching zigzag around chord centerline; nominal 1 mm each side, minimum 0.65 mm; full 3 mm height; no designed gap.',
        'joints':built['joints'],
        'reconstruction_error_mm2':built['reconstruction_error_mm2'],'overlap_mm2':built['overlap_mm2'],'parts':[]}
    with tempfile.TemporaryDirectory(prefix='wing-stl-') as temporary:
        temp=Path(temporary)
        for i,part in enumerate(built['parts'],1):
            planar,angle,shift=part['layout'];mesh=trimesh.creation.extrude_polygon(planar,height=HEIGHT,engine='earcut')
            name=f'part_{i:02d}_chords_{part["start"]+1:02d}-{part["end"]+1:02d}.stl'
            mesh.export(temp/name);saved=trimesh.load_mesh(temp/name,process=True)
            import numpy as np
            if not saved.is_watertight or not saved.is_winding_consistent or not saved.is_volume or saved.body_count!=1:
                raise ValueError(f'Part {i} did not pass closed connected solid verification.')
            if max(saved.extents[:2])>BED-2*MARGIN+1e-4 or abs(saved.extents[2]-HEIGHT)>1e-5:raise ValueError('Saved part dimensions do not fit the bed.')
            if abs(saved.volume-planar.area*HEIGHT)>max(.01,planar.area*HEIGHT*1e-5):raise ValueError('Saved STL volume does not match its planar frame.')
            if not np.all(np.bincount(saved.edges_unique_inverse)==2):raise ValueError('Saved STL has nonmanifold edges.')
            report['parts'].append({'file':name,'start_chord':part['start']+1,'end_chord':part['end']+1,
                'dimensions_mm':saved.extents.tolist(),'rotation_deg':angle,'bed_translation_mm':shift,
                'watertight':True,'connected_bodies':1,'volume_mm3':float(saved.volume),
                'sha256':hashlib.sha256((temp/name).read_bytes()).hexdigest()})
        preview(model,built,report,temp/'assembly.png')
        instructions(report,temp/'PRINT_AND_ASSEMBLE.txt')
        model.write_json(temp/'template.json',report)
        with zipfile.ZipFile(temp/'wing_template_stl.zip','w',zipfile.ZIP_DEFLATED) as archive:
            for file in sorted(temp.iterdir()):
                if file.suffix!='.zip':archive.write(file,file.name)
        dest.mkdir(exist_ok=True)
        for file in temp.iterdir():os.replace(file,dest/file.name)
    return response(report)


def instructions(report,path):
    lines=[f"Wing fabric cutting template — {report['source_study']} / {report['source_case']}",
        '', 'STL units: millimeters. Import at 100% scale. Lay the 3 mm height along printer Z.',
        'All outline and chord lines: 2 mm wide, 3 mm high. The outer edge is the cut line; no seam allowance.',
        'Bed: 250 x 250 mm. Parts fit a 248 x 248 mm square, leaving 1 mm per bed edge when centered.',
        'Extra slicer brims/skirt need additional space. Do not scale a part to fit.',
        'Print one of each numbered part. Match the zigzag chord seams in assembly.png and glue in order.',
        'Zigzag teeth alternate +/-0.35 mm around the chord centerline, about 6 mm pitch.',
        'Each half-rib is nominally 1 mm wide and at least 0.65 mm at a tooth. Both halves are 3 mm high.',
        'The first/last 3 mm of each chord seam stay straight to preserve the outer cutting edge.',
        'Mating faces have zero designed clearance; dry-fit before gluing and remove print burrs if needed.',
        'Align on a flat surface and keep the cutting edge flush; teeth register the parts, glue holds them.',
        'The preview shows assembly coordinates; STL parts are individually translated/rotated for the bed.',
        'One wing only. Flip the assembled flat template to cut the mirrored wing.',
        'Check a known chord or span after printing before cutting fabric.', '', report['method'],'']
    for i,p in enumerate(report['parts'],1):lines.append(f"{i}. {p['file']} — chords {p['start_chord']} to {p['end_chord']}; size {', '.join(f'{x:.3f}' for x in p['dimensions_mm'])} mm")
    Path(path).write_text('\n'.join(lines)+'\n',encoding='utf-8')


def preview(model,built,report,path):
    import numpy as np
    plt=model.ieee_style();fig,ax=plt.subplots(figsize=(7.16,4.5),layout='constrained')
    colors=plt.get_cmap('tab10')
    for i,part in enumerate(built['parts']):
        p=part['polygon'];xy=np.array(p.exterior.coords);ax.fill(*xy.T,color=colors(i%10),edgecolor='#263f49',lw=.5)
        for hole in p.interiors:ax.fill(*np.array(hole.coords).T,color='white')
        center=p.representative_point();ax.annotate(str(i+1),(center.x,center.y),xytext=(0,12),textcoords='offset points',ha='center',fontsize=9,
            bbox={'boxstyle':'round,pad=.2','fc':'white','ec':'#bbb'})
    for i,(a,b) in enumerate(built['chords'],1):
        ax.plot([a[0],b[0]],[a[1],b[1]],ls=':',lw=.5,color='#52616b');ax.annotate(str(i),a,xytext=(0,-9),textcoords='offset points',ha='center',fontsize=6)
    for joint in built['joints']:
        xy=np.array(joint['points']);ax.plot(*xy.T,color='#632a7b',lw=.8)
    ax.invert_yaxis();ax.set_aspect('equal');ax.set(xlabel='Flat root-to-tip direction (mm)',ylabel='Chord direction (mm)',
        title=f"{report['source_case']} · {len(report['parts'])} print part(s) · 2 mm lines × 3 mm high")
    ax.grid(alpha=.15);fig.savefig(path,dpi=200);plt.close(fig)
