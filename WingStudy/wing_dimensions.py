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
    gap=settings.get('gap_m')
    if gap is None:gap=max(0.,row.get('span_m',2*span)-2*span)
    effective=2*span+gap
    reference=2*requested[-1]['y_m']+gap if requested else row.get('reference_grid_span_m',effective)
    reference=max(reference,row.get('reference_grid_span_m',effective))
    omitted=len(requested)-len(active) if requested else row.get('omitted_zero_chord_count',0)
    return {'single_wing_span_m':span,'effective_total_span_m':effective,'reference_total_span_m':reference,
        'omitted_zero_chord_count':omitted,'span_shortened_by_zero_chords':bool(omitted and reference>effective+1e-10)}
