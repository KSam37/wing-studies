"""Effective dimensions derived from the active positive-chord sections."""
import math


def dimensions(row):
    settings=row.get('_settings',{})
    requested=row.get('requested_sections') or row.get('sections') or []
    active=[]
    for section in requested:
        if section.get('chord_m',0)<=0:break
        active.append(section)
    span=active[-1]['y_m'] if active else row.get('single_wing_span_m')
    if not isinstance(span,(int,float)) or not math.isfinite(span) or span<=0:
        total=row.get('span_m');gap=settings.get('gap_m',0)
        span=(total-gap)/2 if isinstance(total,(int,float)) and total>gap else None
    if span is None:return {}
    if active:
        leading_length=sum(math.sqrt((b.get('x_m',0)-a.get('x_m',0))**2+(b['y_m']-a['y_m'])**2+
            ((b['y_m']-a['y_m'])*math.tan(math.radians(a.get('roll_deg',0))))**2) for a,b in zip(active,active[1:]))
    else:
        stations=row.get('geometry',{}).get('stations',[])
        points=[s.get('le',[s.get('x_m',0),s.get('y_m',0),s.get('z_m',0)]) for s in stations]
        leading_length=sum(math.dist(a,b) for a,b in zip(points,points[1:])) if len(points)>1 else span
    gap=settings.get('gap_m')
    if gap is None:gap=max(0.,row.get('span_m',2*span)-2*span)
    effective=2*span+gap
    reference=2*requested[-1]['y_m']+gap if requested else row.get('reference_grid_span_m',effective)
    reference=max(reference,row.get('reference_grid_span_m',effective))
    omitted=len(requested)-len(active) if requested else row.get('omitted_zero_chord_count',0)
    return {'single_wing_span_m':span,'leading_edge_length_m':leading_length,'effective_total_span_m':effective,'reference_total_span_m':reference,
        'omitted_zero_chord_count':omitted,'span_shortened_by_zero_chords':bool(omitted and reference>effective+1e-10)}


def span_class(row):
    """Display grouping by actual total span, merging only sub-micron roundoff."""
    value=dimensions(row).get('effective_total_span_m',row.get('span_m'))
    if not isinstance(value,(int,float)) or not math.isfinite(value) or value<=0:return 'unknown'
    return f'{value:.6f}'.rstrip('0').rstrip('.')
