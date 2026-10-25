"""Actual-size SVG cubic paths from the stored wing functions, not mesh polygons."""
import json
import math
from pathlib import Path
import xml.etree.ElementTree as ET
import numpy as np
from wing_curves import unpack_curve


def save(case,directory,prefix='wing'):
    f=case['outline_function'];leading=unpack_curve(f['leading']);chord=unpack_curve(f['chord'])
    span=f['span_m'];anchors=f['anchors'];ts=np.array([s['y_m']/span for s in anchors])
    cutting=all(abs(s['pitch_deg'])<1e-10 for s in f['sample_sections'])
    # Untwisted bent surfaces unfold by accumulating span distance along each
    # outgoing dihedral. Twist requires a different fabrication construction.
    factors=[1/math.cos(math.radians(s['roll_deg'])) if cutting else 1. for s in anchors[:-1]]
    distances=np.r_[0.,np.cumsum(np.diff(ts)*span*np.array(factors))]
    def flat(t):return float(np.interp(t,ts,distances))
    knots=sorted(set([*leading.x,*chord.x,*ts]))
    curves=[[],[]]
    for a,b in zip(knots,knots[1:]):
        interval=min(len(factors)-1,max(0,int(np.searchsorted(ts,(a+b)/2)-1)))
        slope=span*factors[interval];h=(b-a)/3
        for edge in (0,1):
            def x(t):return float(leading(t)+edge*chord(t))
            def dx(t):return float(leading.derivative()(t)+edge*chord.derivative()(t))
            p=np.array([[flat(a),x(a)],[flat(a)+h*slope,x(a)+h*dx(a)],
                [flat(b)-h*slope,x(b)-h*dx(b)],[flat(b),x(b)]])
            curves[edge].append(p)
    ns='http://www.w3.org/2000/svg';ET.register_namespace('',ns)
    fmt=lambda v:format(float(v),'.12g')
    reason='' if cutting else 'Nonzero section pitch: unpitched function outline only, not a verified unfolded cutting pattern.'
    for side,sign in [('left',-1),('right',1)]:
        parts=[p*np.array([sign*1000,1000]) for p in curves[0]]
        parts += [p[::-1]*np.array([sign*1000,1000]) for p in reversed(curves[1])]
        points=np.concatenate(parts);lo=points.min(axis=0);hi=points.max(axis=0)
        width=max(180.,hi[0]-lo[0]+30);height=hi[1]-lo[1]+85
        offset=np.array([15.,25.])-lo
        root=ET.Element(f'{{{ns}}}svg',{'width':fmt(width)+'mm','height':fmt(height)+'mm',
            'viewBox':f'0 0 {fmt(width)} {fmt(height)}'})
        def add(tag,attributes=None,text=None):
            node=ET.SubElement(root,f'{{{ns}}}{tag}',attributes or {});node.text=text;return node
        title=f"{case['id']} | {side.upper()} {prefix.upper()} | SMOOTH FUNCTION {'CUTTING OUTLINE' if cutting else 'UNPITCHED OUTLINE - NOT A CUTTING PATTERN'}"
        add('title',text=title)
        add('desc',text=reason or 'Exact cubic Bezier representation of the stored wing function, including its zero-width tip. No seam or attachment allowances.')
        add('metadata',text=json.dumps({'case':case['id'],'side':side,'scale':'1:1','units':'mm',
            'flat_cutting_pattern':cutting,'method':'exact cubic function paths',
            'function':f,'simulated_tip_m':case['sections'][-1]['y_m'],'allowances_included':False}))
        path=[]
        for i,part in enumerate(parts):
            p=part+offset
            path.append(('M' if i==0 else 'L')+' '.join(map(fmt,p[0])))
            path.append('C'+' '.join(fmt(v) for v in p[1:].ravel()))
        path.append('Z')
        add('path',{'id':'wing-outline','d':' '.join(path),'fill':'none','stroke':'black','stroke-width':'.25'})
        style={'font-family':'Arial, sans-serif','font-size':'3'}
        add('text',{**style,'x':'15','y':'7'},title)
        add('text',{**style,'x':'15','y':'14'},'1:1 mm; exact function to zero tip. Print at 100%; no seam allowances.')
        y=height-30
        add('line',{'id':'scale-check','x1':'15','x2':'115','y1':fmt(y),'y2':fmt(y),'stroke':'black','stroke-width':'.35'})
        add('text',{**style,'x':'15','y':fmt(y+7)},'100 mm scale check - disable fit-to-page.')
        add('text',{**style,'x':'15','y':fmt(y+14)},reason or 'Untwisted curve unfolded along its span; verify fabrication before cutting.')
        ET.ElementTree(root).write(Path(directory)/f'{prefix}_{side}.svg',encoding='utf-8',xml_declaration=True)
    return {'profile_is_cutting_pattern':cutting,'profile_note':reason or 'Exact smooth-function cutting paths, full zero tip; no allowances.'}
