"""Interpolate a neutral planform; native Ptera still receives ordinary sections."""
import numpy as np
from numpy.polynomial import Polynomial
from scipy.interpolate import PchipInterpolator
from scipy.interpolate import PPoly
import copy
import ast


def export_smooth_profiles(model,study,case_id):
    """Fabrication-only conversion: no planning, meshing, solve or catalog edit."""
    from pathlib import Path
    import json
    import re
    import os
    import tempfile
    import xml.etree.ElementTree as ET
    import curve_profiles
    study=Path(study)
    if not re.fullmatch(r'case_\d{4,}',case_id):raise ValueError('Choose a valid saved case.')
    manifest=model.read_json(study/'manifest.json')
    case=next((c for c in manifest['cases'] if c['id']==case_id),None)
    if not case or not case.get('sections'):raise ValueError('This case has no saved chord-section geometry to smooth.')
    destination=study/case_id
    if not destination.is_dir():raise ValueError('The case output folder does not exist yet.')
    anchors=copy.deepcopy(case.get('outline_function',{}).get('anchors',case['sections']))
    anchors[-1]['chord_m']=0.  # Preserve the established smooth zero-tip template.
    y=np.array([s['y_m'] for s in anchors]);t=y/y[-1]
    leading,leading_info=fit_profile(t,[s['x_m'] for s in anchors])
    chord,chord_info=fit_profile(t,[s['chord_m'] for s in anchors])
    function={'version':1,'span_m':float(y[-1]),'leading':pack_curve(leading),'chord':pack_curve(chord),
        'anchors':anchors,'sample_sections':copy.deepcopy(anchors)}
    export_case={**case,'outline_function':function}
    names=['wing_smooth_left.svg','wing_smooth_right.svg'];ns='http://www.w3.org/2000/svg'
    with tempfile.TemporaryDirectory(prefix='.smooth-',dir=destination) as temp:
        result=curve_profiles.save(export_case,temp,prefix='wing_smooth')
        for name in names:
            path=Path(temp)/name;tree=ET.parse(path);root=tree.getroot()
            meta=root.find(f'{{{ns}}}metadata');record=json.loads(meta.text)
            record.update(export_only_smoothing=True,simulated=False,source_study=study.name,source_case=case_id,
                source_sections=case['sections'],tip_chord_set_to_zero=True)
            meta.text=json.dumps(record)
            root.find(f'{{{ns}}}desc').text+=' Export-only smoothing; force results describe the original sectioned geometry, not this curve.'
            tree.write(path,encoding='utf-8',xml_declaration=True)
        for name in names:os.replace(Path(temp)/name,destination/name)
    return {**result,'files':[f'{study.name}/{case_id}/{name}' for name in names],
        'fit':{'leading_edge':leading_info,'chord_profile':chord_info},
        'note':'Smooth SVGs exported at 1:1 scale with a zero-width tip. Simulation results and original SVGs are unchanged. '+result['profile_note']}


def fit_profile(t, values):
    """Lowest global degree 0..3 fitting every anchor without interval overshoot.

    Otherwise use a C1 shape-preserving piecewise cubic, never a high-order
    interpolating polynomial. Positions are normalized to avoid unit conditioning.
    """
    t=np.asarray(t,dtype=float);values=np.asarray(values,dtype=float)
    tolerance=1e-10*max(1.,float(np.max(np.abs(values))))
    for degree in range(min(3,len(t)-1)+1):
        poly=Polynomial.fit(t,values,degree).convert()
        if np.max(np.abs(poly(t)-values))>tolerance:continue
        extrema=[float(v.real) for v in poly.deriv().roots() if abs(v.imag)<1e-10]
        bounded=True
        for a,b,va,vb in zip(t,t[1:],values,values[1:]):
            q=poly([a,b,*[v for v in extrema if a<v<b]])
            if np.min(q)<min(va,vb)-tolerance or np.max(q)>max(va,vb)+tolerance:
                bounded=False;break
        if bounded:return poly,{'method':'polynomial','degree':degree}
    return PchipInterpolator(t,values),{'method':'shape-preserving piecewise cubic','degree':3}


def smooth_wing(model,design,settings,subdivisions=2):
    """Keep all active anchors and their bends; add interpolated planform sections."""
    subdivisions=model.number(subdivisions,'Curve subdivisions',1,16,True)
    if not isinstance(design,dict):raise ValueError('Choose a wing design to smooth.')
    raw=design.get('sections',[])
    if not isinstance(raw,list):raise ValueError('Wing sections must be a list.')
    local={**settings,'span_panels':max(settings['span_panels'],len(raw)-1)}
    case=model.custom_case(design,local)
    # Re-smoothing a function wing uses its actual endpoint, not the truncated mesh.
    anchors=copy.deepcopy(design.get('outline_function',{}).get('anchors',case['sections']))
    anchors[-1]['chord_m']=0.
    y=np.array([s['y_m'] for s in anchors]);t=y/y[-1]
    leading,leading_info=fit_profile(t,[s['x_m'] for s in anchors])
    chord,chord_info=fit_profile(t,[s['chord_m'] for s in anchors])
    curved=leading_info['degree']>1 or chord_info['degree']>1
    subdivisions=subdivisions if curved else 1
    if len(anchors)==2:subdivisions=max(2,subdivisions)
    if (len(anchors)-1)*subdivisions+1>257:
        raise ValueError('This curve would exceed 257 sections. Reduce subdivisions or source sections.')
    sections=[]
    for i,(a,b) in enumerate(zip(anchors,anchors[1:])):
        # Original anchor dictionaries are retained exactly, including angle frames.
        sections.append(dict(a))
        for j in range(1,subdivisions):
            fraction=j/subdivisions;position=a['y_m']+(b['y_m']-a['y_m'])*fraction
            sections.append({'y_m':position,'x_m':float(leading(position/y[-1])),
                'chord_m':float(chord(position/y[-1])),
                'pitch_deg':a['pitch_deg']+fraction*(b['pitch_deg']-a['pitch_deg']),
                # Keep original leading-edge heights and outgoing dihedral.
                'roll_deg':a['roll_deg']})
    sections.append(dict(anchors[-1]))
    if any(s['chord_m']<=0 for s in sections[:-1]):raise ValueError('The fitted curve would create a nonpositive interior chord.')
    report={'leading_edge':leading_info,'chord_profile':chord_info,
        'anchor_count':len(anchors),'section_count':len(sections),'subdivisions':subdivisions,
        'omitted_zero_sections':case['omitted_zero_chord_count'],
        'note':'Interior anchors retained; tip chord set to zero at the original tip position. SVG uses the full curve. Ptera omits the zero tip and ends at the last positive sample; refine subdivisions for convergence. Pitch is interpolated; outgoing roll is retained.'}
    wing={'name':(case['design_name'][:73]+' smooth')[:80],'sections':sections,'curve_fit':report}
    wing['outline_function']={'version':1,'span_m':float(y[-1]),'leading':pack_curve(leading),
        'chord':pack_curve(chord),'anchors':anchors,'sample_sections':copy.deepcopy(sections)}
    report['simulation_tip_m']=sections[-2]['y_m']
    report['function_tip_m']=float(y[-1])
    required=max(settings['span_panels'],len(sections)-1)
    model.custom_case(wing,{**settings,'span_panels':required})
    return {'design':wing,'required_span_panels':required,'fit':report}


def pack_curve(curve):
    if isinstance(curve,Polynomial):
        return {'breaks':[0.,1.],'coefficients':np.pad(curve.coef,(0,4-len(curve.coef)))[::-1,None].tolist()}
    return {'breaks':curve.x.tolist(),'coefficients':curve.c.tolist()}


def unpack_curve(data):
    knots=np.asarray(data['breaks'],dtype=float);coeff=np.asarray(data['coefficients'],dtype=float)
    if not (2<=len(knots)<=257 and knots[0]==0 and knots[-1]==1 and np.all(np.diff(knots)>0)
            and coeff.shape==(4,len(knots)-1) and np.isfinite(coeff).all()):
        raise ValueError('Invalid cubic wing-function definition.')
    return PPoly(coeff,knots,extrapolate=False)


def matching_definition(definition,sections):
    """Discard stale curve metadata after manual changes; never export an old fit."""
    if not isinstance(definition,dict) or definition.get('sample_sections')!=sections:return None
    leading=unpack_curve(definition['leading']);chord=unpack_curve(definition['chord'])
    span=float(definition['span_m'])
    if not np.isfinite(span) or span<=0:raise ValueError('Invalid wing-function span.')
    for s in sections:
        t=s['y_m']/span
        if not (0<=t<=1 and abs(float(leading(t))-s['x_m'])<1e-9
                and abs(float(chord(t))-s['chord_m'])<1e-9):
            raise ValueError('Wing samples do not match their defining function.')
    return copy.deepcopy(definition)


def polynomial_expression(text):
    """Parse a cubic in normalized span s as arithmetic, without executing code."""
    def walk(node):
        if isinstance(node,ast.Constant) and type(node.value) in (int,float):return Polynomial([float(node.value)])
        if isinstance(node,ast.Name) and node.id=='s':return Polynomial([0.,1.])
        if isinstance(node,ast.UnaryOp) and isinstance(node.op,(ast.UAdd,ast.USub)):
            value=walk(node.operand);return -value if isinstance(node.op,ast.USub) else value
        if isinstance(node,ast.BinOp):
            a,b=walk(node.left),walk(node.right)
            if isinstance(node.op,ast.Add):value=a+b
            elif isinstance(node.op,ast.Sub):value=a-b
            elif isinstance(node.op,ast.Mult):value=a*b
            elif isinstance(node.op,ast.Div) and b.degree()==0 and b.coef[0]!=0:value=a/b.coef[0]
            elif isinstance(node.op,ast.Pow) and b.degree()==0 and b.coef[0] in (0,1,2,3):value=a**int(b.coef[0])
            else:raise ValueError('Use cubic polynomial arithmetic in s only.')
            if value.degree()>3:raise ValueError('Use a polynomial of degree at most three.')
            return value
        raise ValueError('Use numbers, s, parentheses, +, -, *, / and ** only.')
    try:
        if not isinstance(text,str) or len(text)>300:raise ValueError('Function is too long.')
        result=walk(ast.parse(text,mode='eval').body)
        if not np.isfinite(result.coef).all():raise ValueError('Function coefficients must be finite.')
        return result
    except (SyntaxError,OverflowError,RecursionError) as exc:raise ValueError('Enter a cubic polynomial in s.') from exc


def function_wing(model,name,span,leading_text,chord_text,intervals,settings):
    span=model.number(span,'Function tip span',1e-6)
    intervals=model.number(intervals,'Function intervals',2,128,True)
    leading=polynomial_expression(leading_text);chord=polynomial_expression(chord_text)
    if abs(float(leading(0)))>1e-12:raise ValueError('Leading-edge function must start at x(0)=0.')
    if abs(float(chord(1)))>1e-10:raise ValueError('Chord function must end at c(1)=0.')
    checkpoints=[0.,1.,*[float(v.real) for v in chord.deriv().roots() if abs(v.imag)<1e-10 and 0<v.real<1]]
    if float(chord(0))<=0 or any(float(chord(t))<=0 for t in checkpoints if t<1):
        raise ValueError('Chord must be strictly positive before the zero tip.')
    sections=[{'y_m':span*i/intervals,'x_m':float(leading(i/intervals)),
        'chord_m':float(chord(i/intervals)) if i<intervals else 0.,'pitch_deg':0.,'roll_deg':0.}
        for i in range(intervals+1)]
    report={'leading_edge':{'method':'polynomial','degree':int(leading.degree())},
        'chord_profile':{'method':'polynomial','degree':int(chord.degree())},'anchor_count':2,
        'section_count':len(sections),'subdivisions':intervals,'simulation_tip_m':sections[-2]['y_m'],
        'function_tip_m':span,'note':'User-defined functions use s=y/span, 0≤s≤1. SVG uses the exact function to its zero tip; Ptera ends at the last positive sample.'}
    wing={'name':str(name or 'Function wing')[:80],'sections':sections,'curve_fit':report,
        'outline_function':{'version':1,'span_m':span,'leading':pack_curve(leading),'chord':pack_curve(chord),
            'anchors':[copy.deepcopy(sections[0]),copy.deepcopy(sections[-1])],
            'sample_sections':copy.deepcopy(sections),'expressions':{'leading':leading_text,'chord':chord_text}}}
    required=max(settings['span_panels'],intervals)
    model.custom_case(wing,{**settings,'span_panels':required})
    return {'design':wing,'required_span_panels':required,'fit':report}
