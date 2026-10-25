"""Interpolate a neutral planform; native Ptera still receives ordinary sections."""
import numpy as np
from numpy.polynomial import Polynomial
from scipy.interpolate import PchipInterpolator


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
    case=model.custom_case(design,local);anchors=case['sections']
    y=np.array([s['y_m'] for s in anchors]);t=y/y[-1]
    leading,leading_info=fit_profile(t,[s['x_m'] for s in anchors])
    chord,chord_info=fit_profile(t,[s['chord_m'] for s in anchors])
    curved=leading_info['degree']>1 or chord_info['degree']>1
    subdivisions=subdivisions if curved else 1
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
    if any(s['chord_m']<=0 for s in sections):raise ValueError('The fitted curve would create a nonpositive chord.')
    report={'leading_edge':leading_info,'chord_profile':chord_info,
        'anchor_count':len(anchors),'section_count':len(sections),'subdivisions':subdivisions,
        'omitted_zero_sections':case['omitted_zero_chord_count'],
        'note':'Original active anchors retained exactly. Ptera models the curve using these sections; increase subdivisions for geometric convergence. Pitch is interpolated; original outgoing roll is retained between anchors.'}
    wing={'name':(case['design_name'][:73]+' smooth')[:80],'sections':sections,'curve_fit':report}
    required=max(settings['span_panels'],len(sections)-1)
    model.custom_case(wing,{**settings,'span_panels':required})
    return {'design':wing,'required_span_panels':required,'fit':report}
