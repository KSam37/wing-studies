"""Feasible direct-search polls and auditable two-objective hypervolume.

Coordinate directions remain present; smooth multi-chord directions augment
them. This finite-budget local method does not claim global convergence.
"""
import math


def directions(count, paired=True, coordinated=True):
    vectors=[];seen=set()
    def add(weights,kind):
        for sign in (1.,-1.):
            vector=tuple(round(sign*w,12) for w in weights)
            if vector not in seen:seen.add(vector);vectors.append((vector,kind))
    for i in range(count):add([float(j==i) for j in range(count)],'coordinate')
    if paired:
        for i in range(count-1):add([float(j in (i,i+1)) for j in range(count)],'paired')
    if coordinated:
        add([1.]*count,'whole_wing')
        add([2*j/(count-1)-1 for j in range(count)],'taper')
        for center in (1/3,2/3):
            add([max(0.,1-abs(j/(count-1)-center)/.4) for j in range(count)],'smooth_region')
    # Interleave each coordinated direction with coordinate/pair directions so
    # a small simulation budget can reach both kinds of move.
    local=[d for d in vectors if d[1] in ('coordinate','paired')]
    coupled=[d for d in vectors if d[1] not in ('coordinate','paired')]
    out=[]
    for i in range(max(len(local),len(coupled))):
        if i<len(local):out.append(local[i])
        if i<len(coupled):out.append(coupled[i])
    return out


def candidate(chords,weights,steps,options,valid):
    bounds=options['bounds'];delta=[w*s for w,s in zip(weights,steps)]
    floor=options['minimum_chord_m']
    # A removal is a coordinated suffix move. Test it before the continuous
    # monotone projection, which would otherwise stop at the next positive node.
    cut=next((i for i,(c,d,b) in enumerate(zip(chords,delta,bounds))
        if i>=2 and d<0 and b['min_m']==0 and c+d<floor),None)
    if cut is not None:
        truncated=[round(max(b['min_m'],min(b['max_m'] if b['max_m'] is not None else math.inf,c+d)),12)
            for c,d,b in zip(chords,delta,bounds)]
        truncated[cut:]=[0.]*(len(chords)-cut)
        if truncated!=chords and valid(truncated,options):return truncated
    for i,(c,b) in enumerate(zip(chords,bounds)):
        if delta[i]<0 and c<=b['min_m']+1e-12:delta[i]=0.
        if delta[i]>0 and b['max_m'] is not None and c>=b['max_m']-1e-12:delta[i]=0.
    fraction=1.
    for c,d,b in zip(chords,delta,bounds):
        if d<0:fraction=min(fraction,(c-b['min_m'])/-d)
        elif d>0 and b['max_m'] is not None:fraction=min(fraction,(b['max_m']-c)/d)
    if options['decreasing']:
        for i in range(len(chords)-1):
            closing=delta[i+1]-delta[i]
            if closing>1e-15:fraction=min(fraction,(chords[i]-chords[i+1])/closing)
    proposed=[round(c+max(0.,fraction)*d,12) for c,d in zip(chords,delta)]
    for i,value in enumerate(proposed):
        if 0<value<floor:
            proposed[i]=0. if delta[i]<0 and bounds[i]['min_m']==0 else floor
    # Removing an outboard section removes every section beyond it, even when
    # monotone taper is unchecked. Never reconnect positive material after zero.
    zero=next((i for i,c in enumerate(proposed) if c==0),len(proposed))
    if zero<len(proposed):proposed[zero:]=[0.]*(len(proposed)-zero)
    return proposed if proposed!=chords and valid(proposed,options) else None


def hypervolume(values,reference_torque,thrust_scale=1.,torque_scale=1.):
    """Area dominated by (thrust, -torque), relative to (0, -reference_torque).

    The reference is only a measurement baseline. It does not constrain search.
    Duplicate and dominated observations cannot inflate this measure.
    """
    area=0.;best=0.
    for thrust,torque in sorted(values,key=lambda v:(v[1],-v[0])):
        if not all(math.isfinite(x) for x in (thrust,torque)) or torque<0:continue
        if torque<reference_torque and thrust>best:
            area+=(thrust-best)*(reference_torque-torque);best=thrust
    return area/(thrust_scale*torque_scale)


def refresh_hypervolume(events):
    """Recalculate the complete trace with one common, full-history reference.

    Automatic scaling may expand as observations arrive. Recomputing earlier
    events prevents comparing areas calculated with different reference points.
    All span jobs share the same reference and normalization within a study.
    """
    if not events:return None
    lookup={e['case']['id']:e['case'] for e in events}
    values=[(r['single_wing_mean_thrust_N'],r['single_wing_peak_abs_roll_moment_Nm']) for r in lookup.values()]
    thrust_scale=max(t for t,m in values)*1.1
    torque_scale=max(max(m for t,m in values)*1.1,1e-9)
    reference={'reference_thrust_N':0.,'reference_torque_Nm':torque_scale,
        'thrust_scale_N':thrust_scale,'torque_scale_Nm':torque_scale,
        'policy':'Automatic 10% margin around all observed frontier discoveries; complete history recomputed when scaling expands. Measurement only, never a search ceiling.'}
    for e in events:
        points=[lookup[key] for key in e['frontier_case_ids']]
        e['normalized_hypervolume']=hypervolume([(r['single_wing_mean_thrust_N'],r['single_wing_peak_abs_roll_moment_Nm']) for r in points],torque_scale,thrust_scale,torque_scale)
    return reference
