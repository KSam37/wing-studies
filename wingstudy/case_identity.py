"""Stable reference codes for undeformed simulated geometry.

Geometry codes are deliberately separate from catalog.signature: geometry alone
never authorizes reusing a result with different motion, mesh, water or solver.
"""
import hashlib
import json


def geometry_id(case):
    stations=case.get('geometry',{}).get('stations',[])
    if stations and all('le' in s and 'te' in s for s in stations):
        points=[[round(float(v),12) or 0. for v in [*s['le'],*s['te']]] for s in stations]
        # Extra collinear sections do not change the reference outline, although
        # they still change the exact simulation signature / panel distribution.
        reduced=[]
        for point in points:
            reduced.append(point)
            while len(reduced)>=3:
                a,b,c=reduced[-3:];ac=[z-x for x,z in zip(a,c)];ab=[y-x for x,y in zip(a,b)]
                length=sum(v*v for v in ac)
                fraction=sum(x*y for x,y in zip(ab,ac))/length if length else -1
                if 0<fraction<1 and max(abs(x-fraction*y) for x,y in zip(ab,ac))<1e-11:reduced.pop(-2)
                else:break
        value={'contract':1,'undeformed_edges_m':reduced}
    else:
        value={'contract':1,'sections':case.get('sections'),'geometry':case.get('geometry',{}),
            'span_m':case.get('span_m'),'root_chord_m':case.get('root_chord_m')}
    data=json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
    return 'GEOM-'+hashlib.sha256(data).hexdigest()


FAMILY_LABELS={'triangle':'Triangle','square':'Square / rectangular','concave':'Concave / inset',
    'convex':'Convex / full','narrow':'Long and narrow','historical':'Historical / unclassified'}
FAMILY_COLORS={'triangle':'#0072b2','square':'#d55e00','concave':'#009e73','convex':'#cc79a7',
    'narrow':'#e69f00','historical':'#777777'}


def families(row):
    return row.get('seed_families') or [row.get('seed_family') or row.get('adaptive_trial',{}).get('seed_family') or 'historical']
