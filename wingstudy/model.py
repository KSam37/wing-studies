"""Study definitions, stock Ptera UVLM runs, and reproducible comparisons.

No Ptera internals are changed. Units are SI; forces use named wind-axis loads.
"""
from __future__ import annotations

import csv
import hashlib
import itertools
import json
import math
import os
from pathlib import Path
import re
import sys
import time
import traceback

HERE = Path(__file__).resolve().parent
PTERA = HERE.parent / "PteraSoftware"
OUTPUTS = HERE.parent / "outputs" / "studies"
sys.path.insert(0, str(PTERA))

FIELDS = {
    "span_m": ("Total span", "m"), "root_chord_m": ("Root chord", "m"),
    "tip_ratio": ("Tip / root chord", ""), "mid_ratio": ("Mid / root chord", ""),
    "sweep_deg": ("Leading-edge sweep", "deg"), "incidence_deg": ("Wing incidence", "deg"),
    "frequency_hz": ("Flapping frequency", "Hz"), "amplitude_deg": ("Flapping amplitude", "deg"),
    "speed_mps": ("Forward speed", "m/s"), "family": ("Planform", ""),
    "wake_model": ("Wake model", ""), "wake_cycles": ("Retained wake cycles (0 = full)", ""),
    "tail_signature": ("Fixed tail design", ""), "waveform_signature": ("Flapping waveform", ""),
}
FAMILIES = {"rectangular": "Rectangular", "tapered": "Straight taper",
            "shoulder": "Broad shoulder", "custom": "Three-station custom", "sectioned":"Custom sections"}
GEOMETRY_KEYS = ("span_m", "root_chord_m", "tip_ratio", "mid_ratio", "sweep_deg", "incidence_deg")
MOTION_KEYS = ("frequency_hz", "amplitude_deg", "speed_mps")
DEFAULT = {
    "schema_version": 2, "name": "Water wing screening",
    "sweep": {"span_m": "0.6, 0.8", "root_chord_m": "0.14", "tip_ratio": "0.5, 0.8",
              "mid_ratio": "0.85", "sweep_deg": "0", "incidence_deg": "0, 5"},
    "limits": {"min_chord_m": "", "max_chord_m": ""},
    "settings": {"gap_m": 0.04, "rho": 998.2, "nu": 1.004e-6, "dt_s": 0.02,
                 "cycles": 4, "span_panels": 8, "chord_panels": 4,
                 "frequency_hz": 1., "amplitude_deg": 20., "speed_mps": .5,
                 "case_budget": 10000, "cycle_tolerance_pct": 5.0, "save_solver": False},
}
# Rod estimate: d=4 mm, assumed E=34 GPa (supplier axial range 28-40 GPa),
# 0.10 m reference cantilever under pure end moment: k_theta=EI/L.
ROD_EI_NM2=34e9*math.pi*.004**4/64
DEFAULT["settings"].update(wake_model="free", wake_cycles=0,
    aeroelastic_enabled=False, spring_constant_rad=ROD_EI_NM2/.10,
    wing_density=.50, damping_constant_rad=2.0, step_discards=5)
DEFAULT["waveform"]={"mode":"sine","points":"0, 0\n0.25, 1\n0.5, 0\n0.75, -1\n1, 0"}
DEFAULT.update(mode="shape_sweep",shape_sweep={"span_m":.6,"chord_count":4,
    "decreasing":True,"sweep_deg":0.,"incidence_deg":0.,
    "ranges":[{"min_m":.06,"max_m":.14,"count":3} for _ in range(4)]})
SIMULATION_MODE="isolated_single_wing_v1"
OBJECTIVE="single_wing_thrust_roll_ratio_1pm"
for _i in range(1,65):FIELDS[f"chord_{_i}_m"]=(f"Chord {_i}","m")
DEFAULT["tail"] = {"enabled":False,"pitch_deg":0.,"x_m":.65,"z_m":0.,
    "span_panels":4,"chord_panels":2,"sections":[
        {"y_m":0.,"x_m":0.,"chord_m":.10,"pitch_deg":0.,"roll_deg":0.},
        {"y_m":.10,"x_m":.015,"chord_m":.08,"pitch_deg":0.,"roll_deg":0.},
        {"y_m":.20,"x_m":.04,"chord_m":.04,"pitch_deg":0.,"roll_deg":0.}]}
MODEL_NOTE = ("Stock Ptera 5.1.0 prescribed-motion UVLM with optional native independent torsional springs, selectable wake convection and retention; one isolated "
              "flapping wing rooted at the moment reference origin, no body, and a fixed zero-camber mean surface (NACA 0012). "
              "Water viscosity affects the vortex model; membrane deformation, skin friction, "
              "separation, actuator limits, and structural strength are not resolved.")
WATER_SOURCE = "https://www.iapws.org/relguide/LiquidWater.html"


def write_json(path, data):
    path = Path(path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, allow_nan=False), encoding="utf-8")
    # OneDrive/antivirus may briefly open the destination without delete sharing.
    for attempt in range(5):
        try:
            os.replace(tmp,path)
            break
        except PermissionError:
            if attempt==4:raise
            time.sleep(.05*2**attempt)


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def number(value, label, lo=None, hi=None, integer=False):
    try:
        result = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{label}: enter a number.") from None
    if not math.isfinite(result) or (lo is not None and result < lo) or (hi is not None and result > hi):
        raise ValueError(f"{label}: value must be finite and between {lo} and {hi}.")
    if integer:
        if result != int(result):
            raise ValueError(f"{label}: enter a whole number.")
        return int(result)
    return result


def values(text, label, limit=100000):
    """Comma list or inclusive start:stop:step, with decimal-safe endpoint tolerance."""
    if isinstance(text, list):
        result = [number(x, label) for x in text]
    else:
        text = str(text).strip()
        if ":" in text:
            parts = text.split(":")
            if len(parts) != 3:
                raise ValueError(f"{label}: use start:stop:step, e.g. 0.4:0.8:0.1.")
            start, stop, step = [number(p, label) for p in parts]
            if step <= 0 or stop < start:
                raise ValueError(f"{label}: use an increasing range and positive step.")
            count = math.floor((stop - start) / step + 1e-9) + 1
            if count > limit:
                raise ValueError(f"{label}: the range exceeds the study's {limit}-case budget.")
            result = [round(start + step * i, 12) for i in range(count)]
        else:
            result = [number(p.strip(), label) for p in text.split(",") if p.strip()]
    result = list(dict.fromkeys(result))
    if not result or len(result) > limit:
        raise ValueError(f"{label}: enter 1–{limit} values, or raise the study case budget.")
    return result


def stations(case, gap):
    if "sections" in case:
        return [(s["y_m"], s["x_m"], s["chord_m"]) for s in case["sections"]]
    half = (case["span_m"] - gap) / 2
    root = case["root_chord_m"]
    return [(0., 0., root), (half / 2, math.tan(math.radians(case["sweep_deg"])) * half / 2,
                             root * case["mid_ratio"]),
            (half, math.tan(math.radians(case["sweep_deg"])) * half, root * case["tip_ratio"])]


def save_wing_profile(case, settings, path):
    """Export the flat planform at 1 SVG unit = 1 mm, independent of pitch/flap.

    These are nominal outlines, without seam, rod-pocket or cutting allowances.
    Physical SVG dimensions and the viewBox use the same millimeter dimensions.
    """
    import xml.etree.ElementTree as ET
    if "sections" in case:
        return save_custom_profile(case, settings, path)
    ns="http://www.w3.org/2000/svg"
    ET.register_namespace("",ns)
    fmt=lambda v:format(v,".10g")
    points=stations(case,settings["gap_m"])
    span=1000*case["span_m"]
    aft=[1000*x for y,x,c in points]+[1000*(x+c) for y,x,c in points]
    front,back=min(aft),max(aft)
    width=max(210.,span+30.)
    height=20.+back-front+50.
    root=ET.Element(f"{{{ns}}}svg",{"width":fmt(width)+"mm","height":fmt(height)+"mm",
        "viewBox":f"0 0 {fmt(width)} {fmt(height)}","version":"1.1"})
    def add(tag,attrs=None,text=None,parent=root):
        item=ET.SubElement(parent,f"{{{ns}}}{tag}",attrs or {})
        if text is not None:item.text=text
        return item
    add("title",text=f"{case['id']} - full-size flat wing tracing outline")
    add("desc",text="Both wings at 1:1 scale in millimeters. Unpitched flat planform, including the hinge gap. No seam or rod-pocket allowances. Print at actual size, disable fit-to-page, and measure the 100 mm scale bar before tracing. Large templates require a plotter or tiled printing.")
    add("metadata",text=json.dumps({"case":case["id"],"units":"mm","scale":"1:1",
        "geometry":{k:case[k] for k in GEOMETRY_KEYS},"gap_m":settings["gap_m"],
        "allowances_included":False,"incidence_and_flap_projection":False},sort_keys=True))
    label={"font-family":"Arial, sans-serif","font-size":"3","fill":"#222"}
    add("text",{**label,"x":"15","y":"6"},f"{case['id']} | FLAT WING OUTLINE | 1:1 in mm")
    add("text",{**label,"x":"15","y":"12"},
        f"Root {fmt(case['root_chord_m']*1000)} / mid {fmt(case['root_chord_m']*case['mid_ratio']*1000)} / tip {fmt(case['root_chord_m']*case['tip_ratio']*1000)} mm; sweep {fmt(case['sweep_deg'])} deg")
    outlines=add("g",{"id":"wing-outlines","fill":"none","stroke":"black","stroke-width":"0.25","stroke-linejoin":"miter"})
    def xy(y,x,side):return width/2+side*1000*(settings["gap_m"]/2+y),20.+1000*x-front
    for side,name in ((-1,"left-wing"),(1,"right-wing")):
        vertices=[xy(y,x,side) for y,x,c in points]+[xy(y,x+c,side) for y,x,c in reversed(points)]
        add("polygon",{"id":name,"points":" ".join(f"{fmt(x)},{fmt(y)}" for x,y in vertices)},parent=outlines)
    baseline=20.+back-front+10.
    dims=add("g",{"id":"dimensions","fill":"none","stroke":"#777","stroke-width":"0.18"})
    left,right=width/2-span/2,width/2+span/2
    add("line",{"x1":fmt(left),"x2":fmt(right),"y1":fmt(baseline),"y2":fmt(baseline)},parent=dims)
    for x in (left,right):add("line",{"x1":fmt(x),"x2":fmt(x),"y1":fmt(baseline-2),"y2":fmt(baseline+2)},parent=dims)
    add("text",{**label,"x":fmt(width/2),"y":fmt(baseline+6),"text-anchor":"middle"},
        f"Total span {fmt(span)} mm; hinge gap {fmt(settings['gap_m']*1000)} mm")
    ybar=baseline+15
    add("line",{"id":"scale-check","x1":"15","x2":"115","y1":fmt(ybar),"y2":fmt(ybar),"stroke":"black","stroke-width":"0.35"})
    for x in (15,115):add("line",{"x1":str(x),"x2":str(x),"y1":fmt(ybar-1.5),"y2":fmt(ybar+1.5),"stroke":"black","stroke-width":"0.35"})
    add("text",{**label,"x":"15","y":fmt(ybar+5)},"100 mm scale check - print at 100%, no fit-to-page")
    add("text",{**label,"x":"15","y":fmt(ybar+11)},"Nominal outline only; add your own seam / rod-pocket allowances.")
    ET.ElementTree(root).write(Path(path),encoding="utf-8",xml_declaration=True)


def geometry(case, settings):
    if "sections" in case:
        return custom_geometry(case, settings)
    st = stations(case, settings["gap_m"])
    area = 2 * sum((b[0] - a[0]) * (a[2] + b[2]) / 2 for a, b in zip(st, st[1:]))
    half = st[-1][0]
    # Integrate y^2*c(y) analytically on piecewise-linear chord segments.
    moment2 = 0.
    for a, b in zip(st, st[1:]):
        slope = (b[2] - a[2]) / (b[0] - a[0])
        intercept = a[2] - slope * a[0]
        moment2 += intercept * (b[0]**3-a[0]**3)/3 + slope * (b[0]**4-a[0]**4)/4
    return {"area_m2": area, "aspect_ratio": case["span_m"]**2 / area,
            "exposed_span_m": 2*half, "rhat2": math.sqrt(moment2 / (area/2 * half**2)),
            "stations": [{"y_m": y, "x_m": x, "chord_m": c} for y, x, c in st]}


def validate_waveform(raw):
    """Data-only, smooth periodic flap definition; no user code is evaluated."""
    if not isinstance(raw,dict) or raw.get("mode","sine") not in ("sine","custom"):
        raise ValueError("Choose sine or custom flapping waveform.")
    if raw.get("mode","sine")=="sine":return {"mode":"sine"}
    points=raw.get("points","")
    if isinstance(points,str):
        try:points=[[float(v.strip()) for v in line.split(",")] for line in points.strip().splitlines() if line.strip()]
        except ValueError:raise ValueError("Waveform: enter one phase, relative angle pair per line.") from None
    if not isinstance(points,list) or not 4<=len(points)<=40:
        raise ValueError("Waveform: enter 4–40 phase/relative-angle pairs including 0,0 and 1,0.")
    clean=[]
    for point in points:
        if not isinstance(point,(list,tuple)) or len(point)!=2:
            raise ValueError("Waveform: each row needs phase, relative angle.")
        clean.append([number(point[0],"Waveform phase",0,1),number(point[1],"Relative flap angle")])
    if clean[0]!=[0.,0.] or clean[-1]!=[1.,0.]:
        raise ValueError("Waveform must start at 0,0 and end at 1,0 for Ptera's periodic motion.")
    if any(b[0]<=a[0] for a,b in zip(clean,clean[1:])):
        raise ValueError("Waveform phases must increase strictly from 0 to 1.")
    result={"mode":"custom","points":clean}
    wave=FlapWave(result)
    # Ptera itself samples at 100 points/cycle when checking custom callables.
    from pterasoftware._oscillation import validate_custom_spacing_function
    validate_custom_spacing_function(wave)
    return result


class FlapWave:
    """Native Ptera phase callable, with its analytic derivative for virtual work.

    Custom relative-angle points are joined by a periodic cubic spline. Normalize
    by exact spline half-range, preserving zero crossings and any stroke offset.
    Ptera mirrors the same callable on the other wing. Phase is in radians.
    """
    def __init__(self,spec=None):
        self.spec=spec or {"mode":"sine"}
        self.spline=None;self.scale=1.;self.minimum=-1.;self.maximum=1.
        if self.spec.get("mode")=="custom":
            import numpy as np
            from scipy.interpolate import CubicSpline
            p=np.array(self.spec["points"],dtype=float)
            self.spline=CubicSpline(p[:,0],p[:,1],bc_type="periodic")
            extrema=self.spline.derivative().roots(extrapolate=False)
            candidates=np.r_[p[:,0],extrema[(extrema>=0)&(extrema<=1)]]
            vals=self.spline(candidates)
            self.scale=float((max(vals)-min(vals))/2)
            if not math.isfinite(self.scale) or self.scale<1e-12:
                raise ValueError("Waveform must have a nonzero stroke.")
            self.minimum=float(min(vals)/self.scale);self.maximum=float(max(vals)/self.scale)

    def __call__(self,phase):
        if self.spline is None:return float(math.sin(phase))
        return float(self.spline((phase/(2*math.pi))%1)/self.scale)

    def derivative(self,phase):
        import numpy as np
        phase=np.asarray(phase)
        if self.spline is None:return np.cos(phase)
        return self.spline((phase/(2*math.pi))%1,1)/(2*math.pi*self.scale)


def waveform_signature(spec):
    if spec.get("mode","sine")=="sine":return "sine"
    return "custom-"+hashlib.sha256(json.dumps(spec,sort_keys=True,separators=(",",":")).encode()).hexdigest()[:12]


def motion_preview(spec,frequency,amplitude):
    wave=FlapWave(spec)
    points=[[i/200,amplitude*wave(2*math.pi*i/200)] for i in range(201)]
    return {"points":points,"minimum_deg":amplitude*wave.minimum,"maximum_deg":amplitude*wave.maximum,
            "period_s":1/frequency,"signature":waveform_signature(spec)}


def shape_grid(raw,settings,budget):
    """Count admissible combinations with dynamic programming before generating.

    Non-increasing sequences are pruned at each prefix; never enumerate the
    rejected Cartesian product (e.g. 10^20 candidates for a taper-only grid).
    """
    import numpy as np
    if not isinstance(raw,dict):raise ValueError("Shape sweep must be an object.")
    n=number(raw.get("chord_count"),"Number of chords",2,64,True)
    if n-1>settings["span_panels"]:raise ValueError(f"Use at least {n-1} span panels for {n} chord nodes.")
    span=number(raw.get("span_m"),"Fixed total span",settings["gap_m"]+1e-12)
    sweep=number(raw.get("sweep_deg",0),"Fixed leading-edge sweep",-89.9,89.9)
    pitch=number(raw.get("incidence_deg",0),"Fixed incidence",-89.9,89.9)
    baseline=None
    if raw.get("baseline") is not None:
        if not isinstance(raw["baseline"],dict):raise ValueError("The sweep baseline must be a wing design object.")
        base=custom_case(raw["baseline"],settings)
        if len(base["requested_sections"])!=n:
            raise ValueError("The sweep baseline must have one section for every chord range.")
        baseline={"name":base["design_name"],"sections":base["requested_sections"]}
        if base.get("outline_function"):baseline["outline_function"]=base["outline_function"]
        span=2*baseline["sections"][-1]["y_m"]+settings["gap_m"]
    decreasing=raw.get("decreasing",False)
    if not isinstance(decreasing,bool):raise ValueError("Decreasing chord selection must be true/false.")
    ranges=raw.get("ranges",[])
    if not isinstance(ranges,list) or len(ranges)!=n:raise ValueError("Provide one linspace range for every chord node.")
    levels=[]
    for i,r in enumerate(ranges):
        if not isinstance(r,dict):raise ValueError("Each chord range must be an object.")
        lo=number(r.get("min_m"),f"Chord {i+1} minimum",0.)
        hi=number(r.get("max_m"),f"Chord {i+1} maximum",lo)
        count=number(r.get("count"),f"Chord {i+1} samples",1,10000,True)
        if count==1 and hi!=lo:raise ValueError(f"Chord {i+1}: use matching min/max for one sample.")
        levels.append(sorted(set(float(v) for v in np.linspace(lo,hi,count))))
    suffix=[[int(v>0 or n-1>=2) for v in levels[-1]]]
    for i in range(n-2,-1,-1):
        # Prefix sums + bisect avoid a quadratic pairwise counting loop.
        from bisect import bisect_right
        cumulative=list(itertools.accumulate(suffix[0],initial=0))
        counts=[]
        for v in levels[i]:
            if v==0:
                counts.append(suffix[0][0] if i>=2 and levels[i+1][0]==0 else 0)
            else:counts.append(cumulative[bisect_right(levels[i+1],v+1e-12)] if decreasing else cumulative[-1])
        suffix.insert(0,counts)
    total=sum(suffix[0]);raw_count=math.prod(len(v) for v in levels)
    if not total:raise ValueError("No shapes satisfy the chord constraints: at least two positive root sections, only trailing zeros, and optional decreasing chords. Adjust node ranges.")
    if total>budget:raise ValueError(f"This grid has {total:,} admissible shapes ({raw_count:,} unconstrained), above the {budget:,}-case budget. Reduce samples or raise the budget.")
    return {"count":total,"unconstrained_count":raw_count,"pruned_count":raw_count-total,
            "span_m":span,"sweep_deg":sweep,"incidence_deg":pitch,"chord_count":n,
            "decreasing":decreasing,"levels":levels,"suffix":suffix,"baseline":baseline}


def shape_combinations(grid):
    def visit(i,prefix):
        if i==len(grid["levels"]):yield tuple(prefix);return
        for j,v in enumerate(grid["levels"][i]):
            if not grid["suffix"][i][j]:continue
            if prefix and prefix[-1]==0 and v!=0:break
            if grid["decreasing"] and prefix and v>prefix[-1]+1e-12:break
            yield from visit(i+1,prefix+[v])
    yield from visit(0,[])


def plan(config):
    if not isinstance(config, dict):
        raise ValueError("Study settings must be an object.")
    if config.get("workflow")=="root_torque":
        from . import torque_study
        config=torque_study.prepare(sys.modules[__name__],config)
    name = str(config.get("name", "")).strip()
    if not name or len(name) > 80:
        raise ValueError("Give the study a name of 1–80 characters.")
    waveform=validate_waveform(config.get("waveform",DEFAULT["waveform"]))
    limits = config.get("limits", {})
    def optional_bound(key, label):
        value = limits.get(key)
        return None if value in (None, "") else number(value, label, 0.)
    min_chord = optional_bound("min_chord_m", "Minimum chord")
    max_chord = optional_bound("max_chord_m", "Maximum chord")
    if min_chord is not None and max_chord is not None and max_chord < min_chord:
        raise ValueError("Maximum chord must not be less than minimum chord.")
    s = config.get("settings", {})
    def scalar(key, label, lo=None, hi=None, integer=False):
        value = s.get(key, config.get("sweep", {}).get(key))
        if isinstance(value, (list, tuple)) or isinstance(value, str) and any(c in value for c in ",:"):
            raise ValueError(f"{label} is constant across the study. Enter one value in Section 2 or 3, not a list/range.")
        return number(value, label, lo, hi, integer)
    budget = scalar("case_budget", "Case budget", 1, None, True) if "case_budget" in s else 10000
    settings = {
        "gap_m": scalar("gap_m", "Root hinge gap", 1e-12),
        "rho": scalar("rho", "Water density", 1e-12),
        "nu": scalar("nu", "Kinematic viscosity", 1e-12),
        "dt_s": scalar("dt_s", "Delta time", 1e-12),
        "cycles": scalar("cycles", "Cycles", 3, None, True),
        "span_panels": scalar("span_panels", "Span panels per half-wing", 4, None, True),
        "chord_panels": scalar("chord_panels", "Chord panels", 2, None, True),
        "cycle_tolerance_pct": scalar("cycle_tolerance_pct", "Cycle tolerance", .001),
        "frequency_hz": scalar("frequency_hz", "Flapping frequency", 1e-12),
        "amplitude_deg": scalar("amplitude_deg", "Flapping amplitude", 1e-12, 90.),
        "speed_mps": scalar("speed_mps", "Forward speed", 0.),
        "case_budget": budget,
        "save_solver": bool(s.get("save_solver", False)),
        "wake_model": str(s.get("wake_model", "free")),
        "wake_cycles": number(s.get("wake_cycles",0), "Retained wake cycles", 0, None, True),
        "aeroelastic_enabled": s.get("aeroelastic_enabled",False),
    }
    if not isinstance(settings["aeroelastic_enabled"],bool):
        raise ValueError("Native aeroelastic option must be a checkbox boolean.")
    for key,label,lo,integer in (("spring_constant_rad","Shared torsional stiffness",1e-12,False),
            ("wing_density","Wing mass per area",1e-12,False),
            ("damping_constant_rad","Torsional damping",0.,False),("step_discards","Startup deformation hold steps",0,True)):
        settings[key]=number(s.get(key,DEFAULT["settings"][key]),label,lo,None,integer)
    if settings["aeroelastic_enabled"] and settings["step_discards"]>=math.ceil(settings["cycles"]/settings["frequency_hz"]/settings["dt_s"])-1:
        raise ValueError("Startup hold must end before the last simulation step.")
    if settings["wake_model"] not in ("free", "prescribed"):
        raise ValueError("Choose free or prescribed wake.")
    settings["waveform"]=waveform
    wave=FlapWave(waveform)
    if max(abs(wave.minimum),abs(wave.maximum))*settings["amplitude_deg"]>90.+1e-9:
        raise ValueError("The waveform exceeds 90 degrees of flap. Reduce amplitude or change the waveform.")
    settings["simulation_mode"]=SIMULATION_MODE
    if config.get("tail",{}).get("enabled",False):
        raise ValueError("Single-wing studies require the static tail to be disabled.")
    settings["tail"], tail_preview = validate_tail(config.get("tail",{"enabled":False}),settings)
    bounds = {"span_m": (0., None), "root_chord_m": (1e-12, None),
              "tip_ratio": (1e-12, None), "mid_ratio": (1e-12, None),
              "sweep_deg": (-90., 90.), "incidence_deg": (-90., 90.)}
    shape_mode=config.get("mode")=="shape_sweep"
    custom = config.get("mode", "sweep") == "custom" or shape_mode
    inputs = {}
    for key in GEOMETRY_KEYS:
        inputs[key] = values(DEFAULT["sweep"][key] if custom else config.get("sweep", {}).get(key, ""), FIELDS[key][0], budget)
        for val in inputs[key]:
            number(val, FIELDS[key][0], *bounds[key])
    if min(inputs["span_m"]) <= settings["gap_m"]:
        raise ValueError("Total span must exceed the root hinge gap so each wing has positive exposed span.")
    if any(abs(v) >= 90 for v in inputs["sweep_deg"]):
        raise ValueError("Leading-edge sweep must lie strictly between -90 and 90 degrees.")
    if settings["speed_mps"] <= 0:
        raise ValueError("Stock Ptera requires speed > 0 m/s. A stationary zero-speed test stand is unsupported; no small-speed substitution is made.")
    if settings["frequency_hz"] * settings["dt_s"] > 1/30 + 1e-12:
        raise ValueError("Use at least 30 steps per flap: delta time must be <= 1 / (30 × frequency). Refine further for convergence.")
    max_steps = math.ceil(settings["cycles"] / settings["frequency_hz"] / settings["dt_s"])
    if max_steps > 1600:
        raise ValueError(f"Largest case has {max_steps} time steps; limit is 1600 for this sequential desktop runner. Split or refine the study in stages.")
    n_panels = settings["span_panels"] * settings["chord_panels"]
    if settings["tail"]["enabled"]:
        n_panels += 2*settings["tail"]["span_panels"]*settings["tail"]["chord_panels"]
    if n_panels > 800:
        raise ValueError("Limit the combined wing mesh to 800 panels per case.")
    shape_spec=shape_grid(config.get("shape_sweep",{}),settings,budget) if shape_mode else None
    total = shape_spec["count"] if shape_mode else len(config.get("designs", [])) if custom else math.prod(len(inputs[k]) for k in GEOMETRY_KEYS)
    if total > budget and (shape_mode or not custom):
        raise ValueError(f"This Cartesian grid has {total:,} combinations, above your {budget:,}-case budget. Raise Case budget in Section 3 or narrow the lists.")
    # Every geometry field participates independently. Presets only populate the UI.
    cases, skipped = [], 0
    for combination in ([] if custom else itertools.product(*(inputs[k] for k in GEOMETRY_KEYS))):
        case = dict(zip(GEOMETRY_KEYS, combination))
        case.update({k: settings[k] for k in MOTION_KEYS})
        case["family"] = "custom"
        if math.isclose(case["tip_ratio"],1.) and math.isclose(case["mid_ratio"],1.):
            case["family"] = "rectangular"
        elif math.isclose(case["mid_ratio"],(1+case["tip_ratio"])/2):
            case["family"] = "tapered"
        elif math.isclose(case["mid_ratio"],1.):
            case["family"] = "shoulder"
        chords = [case["root_chord_m"] * r for r in (1, case["mid_ratio"], case["tip_ratio"])]
        if (min_chord is not None and min(chords) < min_chord-1e-12 or
                max_chord is not None and max(chords) > max_chord+1e-12):
            skipped += 1
            continue
        case["id"] = f"case_{len(cases)+1:04d}"
        case["geometry"] = geometry(case, settings)
        cases.append(case)
    if shape_mode:
        for chords in shape_combinations(shape_spec):
            half=(shape_spec["span_m"]-settings["gap_m"])/2
            sections=[{"y_m":half*i/(len(chords)-1),"x_m":math.tan(math.radians(shape_spec["sweep_deg"]))*half*i/(len(chords)-1),
                       "chord_m":chord,"pitch_deg":shape_spec["incidence_deg"],"roll_deg":0.} for i,chord in enumerate(chords)]
            if shape_spec["baseline"]:
                sections=[{**s,"chord_m":chord} for s,chord in zip(shape_spec["baseline"]["sections"],chords)]
            if (min_chord is not None and min(v for v in chords if v>0)<min_chord or max_chord is not None and max(chords)>max_chord):
                skipped+=1;continue
            design={"name":f"Shape {len(cases)+1:04d}","sections":sections}
            if shape_spec["baseline"] and shape_spec["baseline"].get("outline_function"):
                design["outline_function"]=shape_spec["baseline"]["outline_function"]
            case=custom_case(design,settings)
            case.update(id=f"case_{len(cases)+1:04d}",search_mode="shape_sweep",chord_count=len(chords),reference_grid_span_m=shape_spec["span_m"])
            case.update({f"chord_{i+1}_m":v for i,v in enumerate(chords)})
            cases.append(case)
    elif custom:
        for design in config.get("designs", []):
            case = custom_case(design, settings)
            chords = [s["chord_m"] for s in case["sections"]]
            if (min_chord is not None and min(chords) < min_chord or
                    max_chord is not None and max(chords) > max_chord):
                raise ValueError(f"{case['design_name']}: a section violates your chord bounds.")
            case["id"] = f"case_{len(cases)+1:04d}"
            cases.append(case)
    if not cases:
        raise ValueError("Add at least one wing design; check your chord bounds if using a sweep.")
    unique={};duplicate_count=0
    for case in cases:
        # Names and omitted outboard nodes do not change the simulated geometry.
        key=json.dumps([[s[k] for k in ("y_m","x_m","chord_m","pitch_deg","roll_deg")]
                        for s in case["sections"]] if "sections" in case else
                       [case[k] for k in GEOMETRY_KEYS],separators=(",",":"))
        alias={"design_name":case.get("design_name",case["id"]),
               "requested_sections":case.get("requested_sections"),
               "chords_m":[case[k] for k in sorted((k for k in case if re.fullmatch(r"chord_\d+_m",k)),key=lambda k:int(k.split('_')[1]))]}
        if key in unique:
            unique[key]["input_aliases"].append(alias);duplicate_count+=1
        else:
            case["input_aliases"]=[alias];unique[key]=case
    cases=list(unique.values())
    if len(cases)>budget:raise ValueError(f"This study has {len(cases):,} unique geometries, above your {budget:,}-case budget.")
    for i,case in enumerate(cases,1):case["id"]=f"case_{i:04d}"
    signature=tail_signature(settings["tail"])
    for c in cases:
        c.update(aeroelastic_enabled=settings.get("aeroelastic_enabled",False))
        if settings.get("aeroelastic_enabled",False):c.update({k:settings[k] for k in ("spring_constant_rad","wing_density","damping_constant_rad","step_discards")})
        c.update(simulation_mode=SIMULATION_MODE,single_wing_span_m=(c["span_m"]-settings["gap_m"])/2)
        c.update(tail_signature=signature,tail_enabled=settings["tail"]["enabled"],
                 tail_pitch_deg=settings["tail"].get("pitch_deg",0.))
        c.update(waveform_signature=waveform_signature(waveform),waveform=waveform)
    return {"name": name, "settings": settings, "cases": cases, "skipped": skipped,
            "objective":"single_wing_mean_thrust_N" if config.get("workflow")=="root_torque" else OBJECTIVE,"shape_grid":{k:v for k,v in shape_spec.items() if k not in ("levels","suffix")} if shape_spec else None,
            "motion_preview":motion_preview(waveform,settings["frequency_hz"],settings["amplitude_deg"]),
            "tail":tail_preview,
            "case_count": len(cases), "duplicate_geometry_count":duplicate_count, "panels_per_case": n_panels, "max_steps": max_steps,
            "runtime_estimate":estimated_case_seconds(settings,n_panels,max_steps),
            "config": config, "model_note": MODEL_NOTE,
            "assumptions": ["Span has no imposed upper limit. Optional chord bounds apply only if supplied.",
                            "Only geometry varies; motion, water, and numerical settings are study constants.",
                            "Positive prescribed forward speed through room-temperature still water.",
                            "Cycle repeatability is separate from mesh/time-step convergence."]}


def tail_signature(tail):
    if not tail.get("enabled",False):return "none"
    return hashlib.sha256(json.dumps(tail,sort_keys=True,separators=(",",":")).encode()).hexdigest()[:12]


def tail_shape(tail, settings):
    local={**settings,"gap_m":0.,"span_panels":tail["span_panels"],
           "chord_panels":tail["chord_panels"],"amplitude_deg":0.}
    shape=custom_case({"name":"Static tail","sections":tail["sections"]},local)
    shape["id"]="tail"
    return shape,local


def validate_tail(raw, settings):
    """One rigid symmetric tail shared by every case; no servo motion is applied."""
    if not isinstance(raw,dict) or not isinstance(raw.get("enabled",False),bool):
        raise ValueError("Tail settings must contain a true/false enabled option.")
    if not raw.get("enabled",False):return {"enabled":False},None
    tail={"enabled":True,"pitch_deg":number(raw.get("pitch_deg",0),"Overall tail pitch",-90,90),
          "x_m":number(raw.get("x_m"),"Tail root aft position",0),
          "z_m":number(raw.get("z_m",0),"Tail root height"),
          "span_panels":number(raw.get("span_panels",4),"Tail span panels per half",1,None,True),
          "chord_panels":number(raw.get("chord_panels",2),"Tail chord panels",2,None,True),
          "sections":raw.get("sections",[])}
    shape,local=tail_shape(tail,settings)
    tail["sections"]=shape["sections"]
    import numpy as np
    from scipy.spatial.transform import Rotation
    whole=Rotation.from_euler("Y",tail["pitch_deg"],degrees=True).as_matrix()
    _,frames=custom_frames(shape)
    angles=Rotation.from_matrix(whole@frames[0]).as_euler("XYZ",degrees=True)
    if np.any(np.abs(angles)>90+1e-8):
        raise ValueError("Overall tail pitch and root section angles exceed Ptera's ±90° orientation range.")
    preview={**shape,"pitch_deg":tail["pitch_deg"],"x_m":tail["x_m"],"z_m":tail["z_m"]}
    preview["geometry"]={**shape["geometry"],"stations":[{**s,
        "le":(whole@np.array(s["le"])+[tail["x_m"],0,tail["z_m"]]).tolist(),
        "te":(whole@np.array(s["te"])+[tail["x_m"],0,tail["z_m"]]).tolist()}
        for s in shape["geometry"]["stations"]]}
    return tail,preview


def make_tail_wing(tail,settings,ps):
    import numpy as np
    from scipy.spatial.transform import Rotation
    shape,local=tail_shape(tail,settings)
    sections,root=custom_sections(shape,local,ps)
    whole=Rotation.from_euler("Y",tail["pitch_deg"],degrees=True).as_matrix()
    angles=Rotation.from_matrix(whole@Rotation.from_euler("XYZ",root,degrees=True).as_matrix()).as_euler("XYZ",degrees=True)
    return ps.Wing(wing_cross_sections=sections,name="Static Tail",
        Ler_Gs_Cgs=(tail["x_m"],0.,tail["z_m"]),angles_Gs_to_Wn_ixyz=np.clip(angles,-90,90),
        symmetric=True,symmetryNormal_G=(0.,1.,0.),symmetryPoint_G_Cg=(0.,0.,0.),
        num_chordwise_panels=tail["chord_panels"],chordwise_spacing="cosine")


def export_tail_profiles(settings,directory):
    tail=settings.get("tail",{})
    if not tail.get("enabled",False):return None
    shape,local=tail_shape(tail,settings)
    return save_wing_profiles(shape,local,directory,prefix="tail")


def custom_case(design, settings):
    """Absolute section frames; roll sets the outgoing leading-edge dihedral.

    x aft, y outboard, z up. Width is measured along the pitched chord, not its
    projection. R = Rx(roll) Ry(pitch); no accumulation of user-entered angles.
    Ptera receives exact parent-relative transforms, through its public API.
    """
    name = str(design.get("name", "")).strip()
    if not name or len(name) > 80:
        raise ValueError("Each custom wing needs a name of 1–80 characters.")
    raw = design.get("sections", [])
    if not isinstance(raw, list) or len(raw) < 2:
        raise ValueError(f"{name}: use at least two chord sections.")
    if len(raw)-1 > settings["span_panels"]:
        raise ValueError(f"{name}: increase span panels to at least {len(raw)-1}, one per section interval.")
    sections = []
    for i, item in enumerate(raw):
        s = {k:number(item.get(k, 0), f"{name}, section {i+1}, {k}")
             for k in ("y_m", "x_m", "chord_m", "pitch_deg", "roll_deg")}
        if s["chord_m"] < 0 or abs(s["pitch_deg"]) >= 90 or abs(s["roll_deg"]) >= 90:
            raise ValueError(f"{name}: chord widths must be nonnegative; pitch and roll must be strictly between -90° and 90°.")
        if i == 0 and (s["y_m"] != 0 or s["x_m"] != 0):
            raise ValueError(f"{name}: root position and aft offset must be zero.")
        if i and s["y_m"] <= sections[-1]["y_m"]:
            raise ValueError(f"{name}: section positions must increase from root to tip.")
        sections.append(s)
    requested_sections=[dict(s) for s in sections]
    first_zero=next((i for i,s in enumerate(sections) if s["chord_m"]==0),len(sections))
    if any(s["chord_m"]!=0 for s in sections[first_zero:]):
        raise ValueError(f"{name}: after a zero chord, all subsequent chords must also be zero; positive chords cannot resume.")
    sections=sections[:first_zero]
    if len(sections)<2:
        raise ValueError(f"{name}: at least two positive chord sections are required before any trailing zeros.")
    if abs(sections[0]["roll_deg"])+settings["amplitude_deg"] > 90:
        raise ValueError(f"{name}: root roll plus flapping amplitude exceeds Ptera's 90° orientation range.")
    half = sections[-1]["y_m"]
    root = sections[0]["chord_m"]
    import numpy as np
    case = {"design_name":name, "sections":sections, "family":"sectioned",
            "span_m":2*half+settings["gap_m"], "root_chord_m":root,
            "tip_ratio":sections[-1]["chord_m"]/root,
            "mid_ratio":float(np.interp(half/2,[s["y_m"] for s in sections],[s["chord_m"] for s in sections]))/root,
            "sweep_deg":math.degrees(math.atan2(sections[-1]["x_m"], half)),
            "incidence_deg":sections[0]["pitch_deg"],
            **{k:settings[k] for k in MOTION_KEYS}}
    case["requested_sections"]=requested_sections
    if design.get("outline_function"):
        from . import wing_curves
        definition=wing_curves.matching_definition(design["outline_function"],requested_sections)
        if definition:case["outline_function"]=definition
    case["active_chord_count"]=len(sections)
    case["omitted_zero_chord_count"]=len(requested_sections)-len(sections)
    case["geometry"] = custom_geometry(case, settings)
    # Validate native relative rotations/offsets before launching a study.
    custom_transforms(case)
    return case


def custom_frames(case):
    import numpy as np
    from scipy.spatial.transform import Rotation
    positions, frames = [], []
    for i, s in enumerate(case["sections"]):
        z = 0. if not i else positions[-1][2] + (s["y_m"]-positions[-1][1])*math.tan(math.radians(case["sections"][i-1]["roll_deg"]))
        positions.append(np.array([s["x_m"], s["y_m"], z]))
        frames.append(Rotation.from_euler("XYZ", [s["roll_deg"],s["pitch_deg"],0], degrees=True).as_matrix())
    return positions, frames


def custom_transforms(case):
    import numpy as np
    from scipy.spatial.transform import Rotation
    positions, frames = custom_frames(case)
    result = [(np.zeros(3), np.zeros(3))]
    for i in range(1,len(positions)):
        offset = frames[i-1].T @ (positions[i]-positions[i-1])
        angles = Rotation.from_matrix(frames[i-1].T @ frames[i]).as_euler("XYZ", degrees=True)
        if offset[1] <= 0 or np.any(np.abs(angles) > 90+1e-8):
            raise ValueError(f"{case['design_name']}, section {i+1}: this bend requires a nonpositive parent span or relative angle beyond Ptera's ±90° range. Add an intermediate section or soften the bend.")
        result.append((offset, np.clip(angles,-90,90)))
    return result


def custom_geometry(case, settings):
    # Keep the same nominal, unpitched planform reference metrics as sweep cases.
    base = {k:v for k,v in case.items() if k != "sections"}
    st = stations(case,settings["gap_m"])
    area = sum((b[0]-a[0])*(a[2]+b[2]) for a,b in zip(st,st[1:]))
    moment2 = 0.
    for a,b in zip(st,st[1:]):
        slope=(b[2]-a[2])/(b[0]-a[0]); intercept=a[2]-slope*a[0]
        moment2 += intercept*(b[0]**3-a[0]**3)/3+slope*(b[0]**4-a[0]**4)/4
    positions,frames=custom_frames(case)
    pts=[]
    for s,p,r in zip(case["sections"],positions,frames):
        pts.append({**s,"z_m":float(p[2]),"le":p.tolist(),"te":(p+r[:,0]*s["chord_m"]).tolist()})
    return {"area_m2":area,"aspect_ratio":case["span_m"]**2/area,
            "exposed_span_m":2*st[-1][0],"rhat2":math.sqrt(moment2/(area/2*st[-1][0]**2)),
            "stations":pts,"reference":"Nominal unpitched planform; span is based on leading-edge y positions."}


def custom_sections(case, settings, ps):
    import numpy as np
    lengths=np.diff([s["y_m"] for s in case["sections"]])
    counts=np.ones(len(lengths),dtype=int)
    quota=(settings["span_panels"]-len(lengths))*lengths/sum(lengths)
    counts+=np.floor(quota).astype(int)
    for i in np.argsort(-(quota-np.floor(quota)))[:settings["span_panels"]-sum(counts)]:counts[i]+=1
    sections=[]
    for i,(s,(offset,angles)) in enumerate(zip(case["sections"],custom_transforms(case))):
        tip=i==len(case["sections"])-1
        sections.append(ps.WingCrossSection(airfoil=ps.Airfoil(name="naca0012"),
            chord=s["chord_m"], Lp_Wcsp_Lpp=offset, angles_Wcsp_to_Wcs_ixyz=angles,
            num_spanwise_panels=None if tip else int(counts[i]),
            spanwise_spacing=None if tip else "uniform",control_surface_symmetry_type=None))
    root=case["sections"][0]
    return sections,(root["roll_deg"],root["pitch_deg"],0.)


def save_custom_profile(case, settings, path):
    """Full-size XY projection; nonplanar geometry has no implied flat pattern."""
    import xml.etree.ElementTree as ET
    ns="http://www.w3.org/2000/svg"; ET.register_namespace("",ns)
    pts=case["geometry"]["stations"]
    vertices=[]
    for side in (-1,1):
        vertices.append([(side*(p["le"][1]+settings["gap_m"]/2)*1000,p["le"][0]*1000) for p in pts]+
                        [(side*(p["te"][1]+settings["gap_m"]/2)*1000,p["te"][0]*1000) for p in reversed(pts)])
    lo=min(x for v in vertices for x,y in v); hi=max(x for v in vertices for x,y in v)
    front=min(y for v in vertices for x,y in v); back=max(y for v in vertices for x,y in v)
    width=max(210,hi-lo+30); height=back-front+80
    root=ET.Element(f"{{{ns}}}svg",{"width":f"{width}mm","height":f"{height}mm","viewBox":f"0 0 {width} {height}"})
    def add(tag,attrs,text=None):
        item=ET.SubElement(root,f"{{{ns}}}{tag}",attrs); item.text=text; return item
    add("title",{},f"{case['design_name']} - actual-size top projection")
    add("metadata",{},json.dumps({"case":case["id"],"scale":"1:1","units":"mm","projection":"XY at neutral flap","flat_cutting_pattern":False,"sections":case["sections"]}))
    for side,v in enumerate(vertices):
        add("polygon",{"id":f"wing-{side}","points":" ".join(f"{x-lo+15},{y-front+25}" for x,y in v),"fill":"none","stroke":"black","stroke-width":"0.25"})
    style={"font-family":"Arial","font-size":"3"}
    add("text",{**style,"x":"15","y":"7"},f"{case['id']} | {case['design_name']} | 1:1 TOP PROJECTION (mm)")
    add("text",{**style,"x":"15","y":"14"},"Nonplanar surface: this is NOT a flattened fabric cutting pattern. No allowances.")
    y=height-28
    add("line",{"id":"scale-check","x1":"15","x2":"115","y1":str(y),"y2":str(y),"stroke":"black","stroke-width":".35"})
    add("text",{**style,"x":"15","y":str(y+7)},"100 mm scale check; print at actual size, disable fit-to-page.")
    ET.ElementTree(root).write(Path(path),encoding="utf-8",xml_declaration=True)


def flat_pattern(case, settings):
    """Unfold a chain of planar section strips, preserving their edge lengths.

    Nonplanar ruled strips need strain or a different panel/seam design. They are
    deliberately rejected instead of approximated as a usable cutting pattern.
    Returns one half-wing's LE/TE points in flat (aft, outboard) coordinates.
    """
    import numpy as np
    if "sections" not in case:
        st=stations(case,settings["gap_m"])
        return ([np.array([x,y]) for y,x,c in st],
                [np.array([x+c,y]) for y,x,c in st])
    pts=case["geometry"]["stations"]
    leading=[np.array([0.,0.])]; trailing=[np.array([pts[0]["chord_m"],0.])]
    for i,(a,b) in enumerate(zip(pts,pts[1:])):
        p,q,r,t=map(np.asarray,(a["le"],a["te"],b["le"],b["te"]))
        u=(q-p)/np.linalg.norm(q-p); d=r-p
        out=d-np.dot(d,u)*u; h=np.linalg.norm(out)
        if h < 1e-10:raise ValueError("A section strip has zero unfolded width.")
        v=out/h; normal=np.cross(u,v)
        scale=max(np.linalg.norm(t-p),np.linalg.norm(d),a["chord_m"],1e-9)
        if abs(np.dot(t-p,normal)) > scale*1e-8:
            raise ValueError(f"Section interval {i+1} has a nonplanar twisted surface; an exact flat cutting outline requires a separate seam/strain design.")
        u2=(trailing[-1]-leading[-1])/np.linalg.norm(trailing[-1]-leading[-1])
        v2=np.array([-u2[1],u2[0]])
        start=leading[-1]
        leading.append(start+np.dot(d,u)*u2+h*v2)
        trailing.append(start+np.dot(t-p,u)*u2+np.dot(t-p,v)*v2)
        if np.dot(trailing[-1]-leading[-1],u2) <= 0:
            raise ValueError("Unfolded section reverses chord direction.")
    poly=[*leading,*reversed(trailing)]
    def cross(a,b):return a[0]*b[1]-a[1]*b[0]
    def intersects(a,b,c,d):
        eps=1e-12
        ab_c,ab_d=cross(b-a,c-a),cross(b-a,d-a)
        cd_a,cd_b=cross(d-c,a-c),cross(d-c,b-c)
        if ab_c*ab_d < -eps and cd_a*cd_b < -eps:return True
        for val,p,x,y in ((ab_c,c,a,b),(ab_d,d,a,b),(cd_a,a,c,d),(cd_b,b,c,d)):
            if abs(val)<=eps and np.all(p>=np.minimum(x,y)-eps) and np.all(p<=np.maximum(x,y)+eps):return True
        return False
    for i in range(len(poly)):
        for j in range(i+1,len(poly)):
            if j==i+1 or i==0 and j==len(poly)-1:continue
            if intersects(poly[i],poly[(i+1)%len(poly)],poly[j],poly[(j+1)%len(poly)]):
                raise ValueError("The unfolded outline overlaps itself; a separate panel layout is needed.")
    return leading,trailing


def save_wing_profiles(case, settings, directory, prefix="wing"):
    """Two separate actual-size SVGs; exact unfold where possible, else projection."""
    if case.get("outline_function"):
        from . import curve_profiles
        return curve_profiles.save(case,directory,prefix)
    import xml.etree.ElementTree as ET
    ns="http://www.w3.org/2000/svg";ET.register_namespace("",ns)
    reason=""
    try:
        leading,trailing=flat_pattern(case,settings);cutting=True
    except ValueError as exc:
        reason=str(exc);cutting=False
        leading=[(s["le"][0],s["le"][1]) for s in case["geometry"]["stations"]]
        trailing=[(s["te"][0],s["te"][1]) for s in case["geometry"]["stations"]]
    fmt=lambda n:format(float(n),".10g")
    for side in ("left","right"):
        sign=-1 if side=="left" else 1
        points=[(sign*1000*p[1],1000*p[0]) for p in [*leading,*reversed(trailing)]]
        minx=min(x for x,y in points);maxx=max(x for x,y in points)
        miny=min(y for x,y in points);maxy=max(y for x,y in points)
        width=max(180,maxx-minx+30);height=maxy-miny+85
        root=ET.Element(f"{{{ns}}}svg",{"width":fmt(width)+"mm","height":fmt(height)+"mm","viewBox":f"0 0 {fmt(width)} {fmt(height)}"})
        def add(tag,attrs=None,text=None):
            el=ET.SubElement(root,f"{{{ns}}}{tag}",attrs or {});el.text=text;return el
        title=f"{case['id']} | {side.upper()} {prefix.upper()} | {'UNFOLDED CUTTING OUTLINE' if cutting else 'TOP PROJECTION - NOT A CUTTING PATTERN'}"
        add("title",text=title)
        add("desc",text=reason or "Planar section strips unfolded without stretch. No seam, attachment or cutting allowances. Dashed chord lines are bend/section references, not cuts.")
        add("metadata",text=json.dumps({"case":case["id"],"side":side,"units":"mm","scale":"1:1","flat_cutting_pattern":cutting,"method":"planar-strip unfolding" if cutting else "neutral XY projection","fallback_reason":reason,"allowances_included":False}))
        label={"font-family":"Arial, sans-serif","font-size":"3"}
        add("text",{**label,"x":"15","y":"7"},title)
        add("text",{**label,"x":"15","y":"14"},"1:1 millimeters; no seam / attachment allowances. Dashed lines are section references.")
        add("polygon",{"id":"wing-outline","points":" ".join(f"{fmt(x-minx+15)},{fmt(y-miny+25)}" for x,y in points),"fill":"none","stroke":"black","stroke-width":".25"})
        for a,b in zip(leading,trailing):
            add("line",{"x1":fmt(sign*1000*a[1]-minx+15),"y1":fmt(1000*a[0]-miny+25),"x2":fmt(sign*1000*b[1]-minx+15),"y2":fmt(1000*b[0]-miny+25),"stroke":"#888","stroke-width":".15","stroke-dasharray":"2 2"})
        y=height-30
        add("line",{"id":"scale-check","x1":"15","x2":"115","y1":fmt(y),"y2":fmt(y),"stroke":"black","stroke-width":".35"})
        add("text",{**label,"x":"15","y":fmt(y+7)},"100 mm scale check - print at 100%, disable fit-to-page.")
        add("text",{**label,"x":"15","y":fmt(y+14)},"Flat pattern: verify fabrication and bend placement." if cutting else "Twist / overlap prevents exact unfolding. Projection only; do not use as a cutting pattern.")
        ET.ElementTree(root).write(Path(directory)/f"{prefix}_{side}.svg",encoding="utf-8",xml_declaration=True)
    return {"profile_is_cutting_pattern":cutting,"profile_note":reason or "Unfolded planar strips; no seam or attachment allowances."}


def build_solver(case, settings):
    if settings.get("aeroelastic_enabled",False):return build_aeroelastic_solver(case,settings)
    import pterasoftware as ps
    half_panels = settings["span_panels"]
    if "sections" in case:
        sections, root_angles = custom_sections(case, settings, ps)
    else:
        sections, root_angles = sweep_sections(case, settings, ps)
    wing = ps.Wing(wing_cross_sections=sections, name="Study Wing",
                   Ler_Gs_Cgs=(0., 0., 0.),
                   angles_Gs_to_Wn_ixyz=root_angles,
                   symmetric=False,
                   num_chordwise_panels=settings["chord_panels"], chordwise_spacing="cosine")
    return solver_from_wing(case, settings, ps, wing)


class FlapAcceleration:
    """Analytic second phase derivative required by native aeroelastic movement."""
    def __init__(self,spec):self.wave=FlapWave(spec)
    def __call__(self,phase):
        if self.wave.spline is None:return -math.sin(phase)
        return float(self.wave.spline((phase/(2*math.pi))%1,2)/((2*math.pi)**2*self.wave.scale))


def build_aeroelastic_solver(case,settings):
    """Construct only stock Ptera aeroelastic classes: one unmirrored wing."""
    import pterasoftware as ps
    if settings.get("tail",{}).get("enabled",False):raise ValueError("Only one isolated wing is supported.")
    if "sections" in case:sections,angles=custom_sections(case,settings,ps)
    else:sections,angles=sweep_sections(case,settings,ps)
    wing=ps.Wing(wing_cross_sections=sections,name="Study Wing",Ler_Gs_Cgs=(0.,0.,0.),
        angles_Gs_to_Wn_ixyz=angles,symmetric=False,explode_into_strips=True,
        num_chordwise_panels=settings["chord_panels"],chordwise_spacing="cosine")
    airplane=ps.Airplane(wings=[wing],name="Water Wing",weight=0.)
    spec=settings.get("waveform",{"mode":"sine"});custom=spec["mode"]=="custom"
    kwargs={"spacingAnglesSecondDerivative_Gs_to_Wn_ixyz":(FlapAcceleration(spec),None,None)} if custom else {}
    wm=ps.AeroelasticWingMovement(base_wing=airplane.wings[0],
        wing_cross_section_movements=[ps.AeroelasticWingCrossSectionMovement(base_wing_cross_section=c)
            for c in airplane.wings[0].wing_cross_sections],
        ampAngles_Gs_to_Wn_ixyz=(case["amplitude_deg"],0.,0.),
        periodAngles_Gs_to_Wn_ixyz=(1/case["frequency_hz"],0.,0.),
        spacingAngles_Gs_to_Wn_ixyz=(FlapWave(spec) if custom else "sine","sine","sine"),**kwargs)
    rows=math.ceil(settings["wake_cycles"]/case["frequency_hz"]/settings["dt_s"]) if settings.get("wake_cycles",0) else None
    movement=ps.AeroelasticMovement(
        airplane_movements=[ps.AeroelasticAirplaneMovement(base_airplane=airplane,wing_movements=[wm])],
        operating_point_movement=ps.OperatingPointMovement(base_operating_point=ps.OperatingPoint(
            rho=settings["rho"],nu=settings["nu"],vCg__E=case["speed_mps"],alpha=0.,beta=0.)),
        delta_time=settings["dt_s"],num_steps=math.ceil(settings["cycles"]/case["frequency_hz"]/settings["dt_s"]),max_wake_rows=rows)
    problem=ps.AeroelasticUnsteadyProblem(movement=movement,wing_density=settings["wing_density"],
        spring_constant_rad=settings["spring_constant_rad"],damping_constant_rad=settings["damping_constant_rad"],step_discards=settings["step_discards"])
    return ps.AeroelasticUnsteadyRingVortexLatticeMethodSolver(aeroelastic_unsteady_problem=problem)


def sweep_sections(case, settings, ps):
    half_panels = settings["span_panels"]
    section_panels = (half_panels//2, half_panels-half_panels//2)
    sections, prev_y, prev_x = [], 0., 0.
    for i, (y, x, chord) in enumerate(stations(case, settings["gap_m"])):
        sections.append(ps.WingCrossSection(
            airfoil=ps.Airfoil(name="naca0012"), chord=chord,
            control_surface_symmetry_type=None,
            Lp_Wcsp_Lpp=(x-prev_x, y-prev_y, 0.),
            num_spanwise_panels=section_panels[i] if i<2 else None,
            spanwise_spacing="uniform" if i<2 else None))
        prev_y, prev_x = y, x
    return sections, (0., case["incidence_deg"], 0.)


def solver_from_wing(case, settings, ps, wing):
    if settings.get("tail",{}).get("enabled",False):
        raise ValueError("Only an isolated single wing is supported for new runs.")
    airplane = ps.Airplane(wings=[wing], name="Water Wing", weight=0.)
    if len(airplane.wings)!=1:
        raise RuntimeError("Expected exactly one unmirrored wing.")
    wing_movements = []
    waveform=settings.get("waveform",{"mode":"sine"})
    for w in airplane.wings:
        static="Static Tail" in w.name
        wing_movements.append(ps.WingMovement(
            base_wing=w,
            wing_cross_section_movements=[ps.WingCrossSectionMovement(base_wing_cross_section=c)
                                          for c in w.wing_cross_sections],
            ampAngles_Gs_to_Wn_ixyz=(0. if static else case["amplitude_deg"], 0., 0.),
            spacingAngles_Gs_to_Wn_ixyz=(FlapWave(waveform) if not static and waveform["mode"]=="custom" else "sine","sine","sine"),
            periodAngles_Gs_to_Wn_ixyz=(0. if static else 1/case["frequency_hz"], 0., 0.)))
    movement = ps.Movement(
        airplane_movements=[ps.AirplaneMovement(base_airplane=airplane, wing_movements=wing_movements)],
        operating_point_movement=ps.OperatingPointMovement(base_operating_point=ps.OperatingPoint(
            rho=settings["rho"], nu=settings["nu"], vCg__E=case["speed_mps"], alpha=0., beta=0.)),
        delta_time=settings["dt_s"], num_cycles=settings["cycles"],
        max_wake_cycles=settings.get("wake_cycles",0) or None)
    problem = ps.UnsteadyProblem(movement=movement, only_final_results=False)
    return ps.UnsteadyRingVortexLatticeMethodSolver(unsteady_problem=problem)


def cycle_metrics(times, thrust, lift, frequency, tolerance):
    import numpy as np
    times, thrust, lift = map(lambda a: np.asarray(a, dtype=float), (times, thrust, lift))
    if not np.all(np.isfinite(np.stack([times, thrust, lift]))):
        raise ValueError("Non-finite loads: exclude this case and inspect its solver log.")
    period, end = 1/frequency, float(times[-1])
    if end - 2*period < times[0]-1e-9:
        raise ValueError("Not enough history for two complete cycles.")
    # Include exact window boundaries by interpolation; integrate with actual time.
    def window(series, start, stop):
        t = np.r_[start, times[(times > start) & (times < stop)], stop]
        return t, np.interp(t, times, series)
    result = {"window_start_s": end-period, "window_end_s": end}
    errors = []
    for key, series in (("thrust", thrust), ("lift", lift)):
        t, v = window(series, end-period, end)
        mean = float(np.trapezoid(v, t)/period)
        result[f"mean_{key}_N"] = mean
        result[f"rms_{key}_N"] = float(np.sqrt(np.trapezoid(v*v, t)/period))
        result[f"peak_abs_{key}_N"] = float(np.max(np.abs(v)))
        result[f"peak_{key}_N"] = float(np.max(v))
        phase = np.linspace(0, period, 201)
        last = np.interp(end-period+phase, times, series)
        prior = np.interp(end-2*period+phase, times, series)
        # 1 mN floor prevents near-zero signed means from inflating a relative error.
        scale = max(float(np.sqrt(np.mean(last*last))), float(np.sqrt(np.mean(prior*prior))), .001)
        err = 100*float(np.sqrt(np.mean((last-prior)**2)))/scale
        result[f"cycle_error_{key}_pct"] = err
        errors.append(err)
    result["cycle_error_pct"] = max(errors)
    result["cycle_repeatable"] = bool(max(errors) <= tolerance)
    return result


def ieee_style():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"font.family": "serif", "font.serif": ["Times New Roman", "DejaVu Serif"],
        "font.size": 8, "axes.labelsize": 8, "xtick.labelsize": 7, "ytick.labelsize": 7,
        "legend.fontsize": 7, "lines.linewidth": 1., "axes.linewidth": .6,
        "pdf.fonttype": 42, "ps.fonttype": 42, "savefig.dpi": 600,
        "axes.spines.top": False, "axes.spines.right": False, "figure.facecolor": "white"})
    return plt


def save_figure(fig, stem):
    fig.savefig(str(stem)+".png", dpi=600, facecolor="white")


HISTORY_COLUMNS = ["time_s", "thrust_N", "lift_N", "induced_drag_N", "crosswind_N",
                   "pitching_moment_Nm", "rolling_moment_wind_Nm", "CT_forward_speed_ref", "CL_forward_speed_ref"]
TAIL_HISTORY_COLUMNS = ["main_wing_thrust_N","main_wing_lift_N","tail_thrust_N","tail_lift_N"]
TORQUE_HISTORY_COLUMNS = ["single_wing_root_roll_moment_Nm", "estimated_two_wing_thrust_N"]
SINGLE_WING_HISTORY_COLUMNS=["single_wing_thrust_N","single_wing_lift_N"]


def single_wing_forces(airplane):
    if len(airplane.wings)!=1:
        raise ValueError("Expected exactly one isolated wing.")
    w=airplane.wings[0]
    return (sum(-p.inducedDrag_W for p in w.panels.flat),sum(p.lift_W for p in w.panels.flat))


def shape_metrics(times,forces,right_moment,frequency,tolerance,half_span):
    """Single physical right wing: signed mean thrust / peak |hinge roll moment|.

    Keep negative/zero thrust and numerical-zero denominators out of optimization.
    L*T/M is a dimensionless companion, not a promise of dynamic similarity.
    """
    import numpy as np
    force=np.asarray(forces);right=np.asarray(right_moment)
    metric=cycle_metrics(times,force[:,0],force[:,1],frequency,tolerance)
    start=metric["window_start_s"];end=metric["window_end_s"]
    t=np.r_[start,np.asarray(times)[(np.asarray(times)>start)&(np.asarray(times)<end)],end]
    rv=np.interp(t,times,right)
    peak=float(np.max(np.abs(rv)));rms=float(np.sqrt(np.trapezoid(rv*rv,t)*frequency))
    mean=metric["mean_thrust_N"];valid=bool(peak>1e-9 and mean>0)
    return {"shape_objective_version":"isolated_single_wing_mean_thrust_peak_roll_v2",
            "simulation_mode":SIMULATION_MODE, "estimated_two_wing_mean_thrust_N":2*mean,
            "single_wing_mean_thrust_N":mean,"single_wing_mean_lift_N":metric["mean_lift_N"],
            "single_wing_peak_abs_roll_moment_Nm":peak,"single_wing_rms_roll_moment_Nm":rms,
            OBJECTIVE:mean/peak if valid else None,"dimensionless_thrust_roll_score":half_span*mean/peak if valid else None,
            "shape_ratio_valid":valid,"reference_half_span_m":half_span,
            "single_wing_force_cycle_repeatable":metric["cycle_repeatable"],
            "single_wing_force_cycle_error_pct":metric["cycle_error_pct"]}


def shape_eligible(row,repeat_only=True):
    value=row.get(OBJECTIVE)
    return row.get("status")=="ok" and row.get("shape_ratio_valid",False) and isinstance(value,(int,float)) and math.isfinite(value) and (not repeat_only or row.get("cycle_repeatable",False))


def shape_comparison(study,export=False,repeat_only=True):
    study=Path(study);rows=read_json(study/"results.json") if (study/"results.json").exists() else []
    ranked=sorted((r for r in rows if shape_eligible(r,repeat_only)),key=lambda r:r[OBJECTIVE],reverse=True)
    result={"objective":OBJECTIVE,"winner":ranked[0] if ranked else None,"ranked_count":len(ranked),
            "note":"Single right-wing final-cycle mean thrust / sampled peak absolute hinge roll moment. Positive thrust and nonzero moment required. L*T/M is the size-normalized companion; physical scaling must preserve similarity."}
    if not export:return result
    measured=sorted((r for r in rows if shape_eligible(r,False)),key=lambda r:r[OBJECTIVE],reverse=True)
    if not measured:raise ValueError("No valid single-wing ratios. Rerun legacy results or inspect failed/non-propulsive cases.")
    dest=study/"comparisons";dest.mkdir(exist_ok=True);stem=dest/"shape_comparison"
    # The standard export is a ranked list with a true planform thumbnail per row.
    # Paginate large grids instead of allocating one unbounded raster.
    from matplotlib.offsetbox import AnnotationBbox,DrawingArea
    from matplotlib.patches import Polygon
    import numpy as np
    manifest=read_json(study/"manifest.json") if (study/"manifest.json").exists() else {}
    gap=manifest.get("settings",{}).get("gap_m",DEFAULT["settings"]["gap_m"])
    plt=ieee_style();files=[]
    for start in range(0,len(measured),25):
        page=measured[start:start+25];number=start//25+1
        fig,ax=plt.subplots(figsize=(7.16,1.+.42*len(page)),layout="constrained")
        ax.set_xlim(0,1);ax.set_ylim(len(page)+.3,-1.);ax.axis("off")
        ax.set_title("Wing designs ranked by thrust / roll moment"+(f" · page {number}" if len(measured)>25 else ""),fontsize=10,pad=12)
        for x,text in ((.025,"Rank"),(.21,"Wing shape"),(.38,"Case"),(.68,"Thrust/moment\n(1/m)"),(.83,"Mean thrust\n(N)"),(.98,"Peak |roll|\n(N m)")):
            ax.text(x,-.55,text,ha="center" if x==.21 else "left" if x<.5 else "right",va="center",fontsize=7,fontweight="bold")
        for i,r in enumerate(page):
            y=i+.5
            if i%2==0:ax.axhspan(i,i+1,color="#f2f7f7",zorder=0)
            ax.text(.025,y,str(start+i+1),va="center",fontsize=8)
            thumbnail=wing_thumbnail(r,gap);points=np.concatenate(thumbnail);extent=np.ptp(points,axis=0)
            scale=min(100/max(extent[0],1e-9),22/max(extent[1],1e-9))
            drawing=DrawingArea(104,26,0,0)
            for poly in thumbnail:drawing.add_artist(Polygon(np.asarray(poly)*[scale,-scale]+[52,13],closed=True,facecolor="#b8ddd5",edgecolor="#007f78",lw=.8))
            ax.add_artist(AnnotationBbox(drawing,(.21,y),frameon=False,box_alignment=(.5,.5)))
            ax.text(.38,y-.13,r["id"],va="center",fontsize=7.5)
            ax.text(.38,y+.22,"repeatable" if r.get("cycle_repeatable") else "unsettled",va="center",fontsize=6.5,color="#637b86")
            for x,key in ((.68,OBJECTIVE),(.83,"single_wing_mean_thrust_N"),(.98,"single_wing_peak_abs_roll_moment_Nm")):
                ax.text(x,y,f"{r[key]:.5g}",ha="right",va="center",fontsize=8)
        page_stem=stem if number==1 else stem.with_name(stem.name+f"_{number:03d}")
        save_figure(fig,page_stem);plt.close(fig)
        files.append((Path(study.name)/"comparisons"/(page_stem.name+".png")).as_posix())
    result["files"]=files
    keys=list(dict.fromkeys(k for r in measured for k in r))
    rank={r["id"]:i for i,r in enumerate(ranked,1)}
    with stem.with_suffix('.csv').open('w',newline='',encoding='utf-8') as f:
        writer=csv.DictWriter(f,fieldnames=["eligible_rank",*keys]);writer.writeheader()
        writer.writerows({"eligible_rank":rank.get(r["id"]),**csv_row(r)} for r in measured)
    result["file"]=(Path(study.name)/"comparisons"/(stem.name+".png")).as_posix()
    return result


_TIMING_CACHE={"at":0.,"samples":[]}
def estimated_case_seconds(settings,panels,steps):
    """Rough local timing estimate including native plot/animation overhead."""
    import statistics
    if time.time()-_TIMING_CACHE["at"]>30:
        samples=[]
        if OUTPUTS.exists():
            for path in sorted(OUTPUTS.iterdir(),reverse=True)[:30]:
                try:
                    m=read_json(path/"manifest.json")
                    if m.get("exclude_timing_from_eta",False):continue
                    for row in read_json(path/"results.json")[-8:]:
                        if row.get("status")=="ok" and row.get("elapsed_s",0)>0 and not row.get("reused_from"):
                            samples.append((m["settings"],m["panels_per_case"],row["steps"],row["elapsed_s"]))
                except (OSError,ValueError,KeyError,TypeError):continue
        _TIMING_CACHE.update(at=time.time(),samples=samples)
    matches=[]
    for s,p,n,elapsed in _TIMING_CACHE["samples"]:
        if s.get("simulation_mode","legacy_paired")!=settings.get("simulation_mode","legacy_paired"):continue
        if s.get("aeroelastic_enabled",False)!=settings.get("aeroelastic_enabled",False):continue
        if settings.get("aeroelastic_enabled",False) and any(s.get(k)!=settings.get(k) for k in ("spring_constant_rad","wing_density","damping_constant_rad")):continue
        if s.get("wake_model","free")!=settings.get("wake_model","free") or s.get("wake_cycles",0)!=settings.get("wake_cycles",0):continue
        if not .5<=panels/p<=2 or not .5<=steps/n<=2:continue
        scale=(panels/p)**2*(steps/n)**2
        matches.append((abs(math.log(panels/p))+abs(math.log(steps/n)),20+max(1,elapsed-20)*scale))
    chosen=sorted(matches)[:8]
    return {"case_seconds":statistics.median(v for _,v in chosen) if chosen else None,"timing_samples":len(chosen),"timing_note":"Rough local estimate; includes native plots and animation. Updated from completed cases."}


def runtime_status(manifest,status,rows):
    import statistics
    if status.get("state")!="running":return {"eta_remaining_s":0.}
    if manifest.get("exclude_timing_from_eta",False):return {"eta_remaining_s":None,"eta_basis":"Validation timing excludes the overnight interruption"}
    samples=[r["elapsed_s"] for r in rows[-5:] if r.get("elapsed_s",0)>0]
    seconds=statistics.median(samples) if samples else estimated_case_seconds(manifest["settings"],manifest["panels_per_case"],manifest["max_steps"])["case_seconds"]
    if seconds is None:return {"eta_remaining_s":None,"eta_basis":"Calibrating first case"}
    elapsed=max(0,time.time()-status.get("current_case_started",time.time()))
    remaining=max(0,seconds-elapsed)+seconds*max(0,status["total"]-len(rows)-1)
    return {"eta_remaining_s":remaining,"eta_basis":f"Recent {len(samples)} completed cases" if samples else "Similar local runs"}


def wing_root_roll_moment(airplane):
    """Fluid roll moment at the single wing root, about the body x flap axis."""
    import numpy as np
    if len(airplane.wings)!=1:
        raise ValueError("Expected exactly one isolated wing.")
    transform=airplane.T_pas_G_Cg_to_GP1_CgP1
    axis=transform[:3,:3]@np.array([1.,0.,0.])
    w=airplane.wings[0]
    root=w.children_T_pas_Wcs_Lp_to_G_Cg[0][:3,3]
    hinge=transform[:3,:3]@root+transform[:3,3]
    forces=np.sum([p.forces_GP1 for p in w.panels.flat],axis=0)
    moments=np.sum([p.moments_GP1_CgP1 for p in w.panels.flat],axis=0)
    return float(np.dot(moments-np.cross(hinge,forces),axis))


def case_data(study, case_id):
    """Read current shared histories or the original per-case layout."""
    import numpy as np
    study = Path(study)
    if not re.fullmatch(r"case_\d{4,}", case_id):
        raise ValueError("Invalid case identifier.")
    manifest = read_json(study/"manifest.json")
    case = next(c for c in manifest["cases"] if c["id"] == case_id)
    metrics = next(r for r in read_json(study/"results.json") if r["id"] == case_id)
    legacy = study/case_id/"forces.csv"
    columns=[k for k in HISTORY_COLUMNS if k!="rolling_moment_wind_Nm"]
    if legacy.exists():
        data = np.atleast_2d(np.loadtxt(legacy, delimiter=",", skiprows=1)).tolist()
    else:
        with (study/"comparisons"/"time_histories.csv").open(newline="", encoding="utf-8") as f:
            reader=csv.DictReader(f);columns=[k for k in reader.fieldnames if k!="case"]
            data = [[float(r[k]) for k in columns] for r in reader if r["case"] == case_id]
    return {"case":case, "settings":manifest["settings"], "metrics":metrics, "history":data,"history_columns":columns}


def component_forces(airplane):
    """Native panel loads grouped into moving main wings and the static tail."""
    main=[0.,0.];tail=[0.,0.]
    for w in airplane.wings:
        result=tail if "Static Tail" in w.name else main
        for panel in w.panels.flat:
            result[0] += -panel.inducedDrag_W
            result[1] += panel.lift_W
    return [*main,*tail]


def run_case(case, settings, directory):
    import numpy as np
    import pterasoftware as ps
    import matplotlib
    matplotlib.use("Agg")
    directory.mkdir(exist_ok=True)
    profile=save_wing_profiles(case,settings,directory)
    print(f"Building {case['id']}: {case['family']}, span {case['span_m']} m", flush=True)
    solver = build_solver(case, settings)
    solver.run(prescribed_wake=settings.get("wake_model","free")=="prescribed",
               calculate_streamlines=False, show_progress=True)
    history = []
    has_tail=settings.get("tail",{}).get("enabled",False)
    for step in range(solver.first_results_step, solver.num_steps):
        a = solver.steady_problems[step].airplanes[0]
        history.append([step*solver.delta_time, -a.inducedDrag_W, a.lift_W,
                        a.inducedDrag_W, a.crosswindForce_W, a.pitchingMoment_W_Cg, a.rollingMoment_W_Cg,
                        -a.inducedDragCoefficient_W, a.liftCoefficient_W])
        if has_tail:history[-1].extend(component_forces(a))
        history[-1].extend(single_wing_forces(a))
        right=wing_root_roll_moment(a)
        time=step*solver.delta_time
        history[-1].extend([right, -2*a.inducedDrag_W])
    data = np.array(history, dtype=float)
    if not np.isfinite(data).all():
        raise RuntimeError("Ptera returned non-finite loads.")
    dest = directory.parent/"comparisons"
    dest.mkdir(exist_ok=True)
    history_path = dest/"time_histories.csv"
    new_history = not history_path.exists()
    with history_path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if new_history:
            writer.writerow(["case", *HISTORY_COLUMNS, *(TAIL_HISTORY_COLUMNS if has_tail else []),*SINGLE_WING_HISTORY_COLUMNS,*TORQUE_HISTORY_COLUMNS])
        writer.writerows([case["id"], *row] for row in data)
    metrics = cycle_metrics(data[:,0], data[:,1], data[:,2], case["frequency_hz"], settings["cycle_tolerance_pct"])
    offset=9+(4 if has_tail else 0)
    metrics.update(shape_metrics(data[:,0],data[:,offset:offset+2],data[:,-2],case["frequency_hz"],settings["cycle_tolerance_pct"],(case["span_m"]-settings["gap_m"])/2))
    # Shape settling uses wing force and physical root moment, not a drivetrain.
    phase=np.linspace(0,1/case["frequency_hz"],201);end=data[-1,0];period=1/case["frequency_hz"]
    latest=np.interp(end-period+phase,data[:,0],data[:,-2]);prior=np.interp(end-2*period+phase,data[:,0],data[:,-2])
    root_error=100*float(np.sqrt(np.mean((latest-prior)**2)))/max(float(np.sqrt(np.mean(latest*latest))),float(np.sqrt(np.mean(prior*prior))),1e-9)
    metrics.update(root_moment_cycle_error_pct=root_error,
                   cycle_error_pct=max(metrics["single_wing_force_cycle_error_pct"],root_error),
                   cycle_repeatable=bool(metrics["single_wing_force_cycle_repeatable"] and root_error<=settings["cycle_tolerance_pct"]))
    g = case["geometry"]
    metrics.update({"area_m2": g["area_m2"]/2, "aspect_ratio": ((case["span_m"]-settings["gap_m"])/2)**2/(g["area_m2"]/2),
                    "rhat2": g["rhat2"], "dt_s": solver.delta_time, "steps": solver.num_steps,
                    "cycles": settings["cycles"], "span_panels": settings["span_panels"],
                    "chord_panels": settings["chord_panels"], "rho": settings["rho"], "nu": settings["nu"]})
    metrics.update(wake_model=settings.get("wake_model","free"),wake_cycles=settings.get("wake_cycles",0),**profile)
    metrics.update(aeroelastic_enabled=settings.get("aeroelastic_enabled",False))
    if settings.get("aeroelastic_enabled",False):
        metrics.update({k:settings[k] for k in ("spring_constant_rad","wing_density","damping_constant_rad","step_discards")})
        # Native state history: inspect the solved structural response, not geometry previews.
        states=solver.unsteady_problem.listDeformationAnglesYRad_Wcsp_to_Wcs_ixyz[0]
        metrics["peak_abs_native_twist_deg"]=float(np.rad2deg(np.max(np.abs(states))))
    metrics.update(output_scope="isolated_single_wing", estimated_two_wing_thrust_note="Twice isolated-wing thrust; wing interaction is not modeled.")
    if has_tail:
        for offset,label in ((8,"main_wing"),(10,"tail")):
            part=cycle_metrics(data[:,0],data[:,offset],data[:,offset+1],case["frequency_hz"],settings["cycle_tolerance_pct"])
            metrics.update({f"{label}_{k}":v for k,v in part.items() if k.startswith(("mean_","peak_","rms_"))})
    # Preserve Ptera's default plot styling, including after comparison rendering.
    print(f"Saving default Ptera plots and animation for {case['id']}", flush=True)
    with matplotlib.rc_context(matplotlib.rcParamsDefault):
        ps.plot_results_versus_time(solver, show=False, save=True,
                                   directory=directory, file_format="png")
    # Stock Ptera automation mode starts without a keypress; its preview closes
    # automatically before off-screen export. WebP is Ptera's native animation format.
    ps.animate(solver, scalar_type="lift", show_wake_vortices=True,
               save=True, path=directory/"animation.webp", testing=True)
    return metrics


def write_summary(study, rows):
    if not rows:
        return
    keys = list(dict.fromkeys(k for row in rows for k in row))
    tmp = study/"summary.csv.tmp"
    with tmp.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader(); writer.writerows(csv_row(r) for r in rows)
    os.replace(tmp, study/"summary.csv")
    write_json(study/"results.json", rows)
    manifest=read_json(study/"manifest.json") if (study/"manifest.json").exists() else {}
    ranked = sorted((r for r in rows if shape_eligible(r)),key=lambda r:r[OBJECTIVE],reverse=True)[:10]
    if manifest.get("config",{}).get("workflow")=="root_torque":
        from . import torque_study
        limit=manifest["config"]["optimization"]["max_root_moment_nm"]
        report=torque_study.rank(rows,limit)
        ranked=[{k:v for k,v in r.items() if k in keys} for r in report['rows'] if r['thrust_rank'] is not None][:10]
    dest = study/"comparisons"; dest.mkdir(exist_ok=True)
    with (dest/"top_performers.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["shape_rank", *keys])
        writer.writeheader()
        writer.writerows({"shape_rank":i, **csv_row(r)} for i,r in enumerate(ranked, 1))
    # Render the comparison once after the solve, not after every completed case.


def csv_row(row):
    return {k:json.dumps(v,separators=(",",":")) if isinstance(v,(dict,list)) else v for k,v in row.items()}


def worker(study):
    from . import catalog
    study = Path(study)
    manifest = read_json(study/"manifest.json")
    rows = []
    catalog_metric="single_wing_mean_thrust_N" if manifest.get("config",{}).get("workflow")=="root_torque" else catalog.OBJECTIVE
    def state(**kw):
        write_json(study/"status.json", {"total": len(manifest["cases"]), "completed": len(rows), **kw})
    state(state="running", message="Preparing first case")
    for case in manifest["cases"]:
        directory = study/case["id"]
        directory.mkdir(exist_ok=True)
        state(state="running", current=case["id"],current_case_started=time.time(), message=f"Solving {case['id']}")
        started = time.time()
        row = {k:v for k,v in case.items() if k != "geometry" or "sections" in case}
        if manifest["settings"].get("tail",{}).get("enabled",False):
            row["tail_definition"]=manifest["settings"]["tail"]
        try:
            try:
                cached=catalog.reuse(sys.modules[__name__],case,manifest["settings"],directory)
            except (OSError,ValueError,KeyError):
                cached=None
                print("Cached output unavailable; solving this case again.",flush=True)
            row.update(cached if cached is not None else run_case(case, manifest["settings"], directory))
            row["status"] = "ok"
        except Exception as exc:
            traceback.print_exc()
            row.update(status="failed", error=str(exc))
            write_json(directory/"error.json", {"error": str(exc), "traceback": traceback.format_exc()})
        row["elapsed_s"] = round(time.time()-started, 3)
        catalog.record(sys.modules[__name__],manifest,study.name,row)
        rows.append(row)
        write_summary(study, rows)
        catalog.export(sys.modules[__name__],metric=catalog_metric,browser_url=manifest.get("browser_url","http://127.0.0.1:8765"),force=False)
    failed = sum(r["status"] != "ok" for r in rows)
    if manifest.get("config",{}).get("workflow")=="root_torque":
        from . import torque_study
        torque_study.results(sys.modules[__name__],study,export=True)
    elif any(shape_eligible(r,False) for r in rows):
        shape_comparison(study,export=True)
        shape_landscape(study,repeat_only=any(shape_eligible(r) for r in rows),export=True)
    state(state="complete" if not failed else "complete_with_errors", message=f"Finished; {failed} failed cases")
    catalog.export(sys.modules[__name__],metric=catalog_metric,browser_url=manifest.get("browser_url","http://127.0.0.1:8765"))


METRIC_LABELS = {"mean_thrust_N": "Mean thrust (N)", "peak_thrust_N": "Peak forward thrust (N)",
                 "mean_lift_N": "Mean lift (N)", "peak_abs_thrust_N": "Peak |thrust| (N)",
                 "cycle_error_pct": "Cycle difference (%)"}
METRIC_LABELS.update({OBJECTIVE:"Single-wing thrust / roll moment (1/m)","dimensionless_thrust_roll_score":"Size-normalized thrust / roll score",
    "single_wing_mean_thrust_N":"Single-wing mean thrust (N)","single_wing_peak_abs_roll_moment_Nm":"Single-wing peak |roll moment| (N m)"})


def geometry_axes(rows):
    nodes=sorted({k for r in rows for k in r if re.fullmatch(r"chord_\d+_m",k)},key=lambda k:int(k.split('_')[1]))
    return nodes or list(GEOMETRY_KEYS)


def wing_thumbnail(row,gap):
    """Normalized top-view planform polygons; no per-case image files."""
    import numpy as np
    if row.get("sections"):
        positions,frames=custom_frames(row)
        leading=np.asarray(positions)
        trailing=np.asarray([p+r@np.array([s["chord_m"],0.,0.]) for p,r,s in zip(positions,frames,row["sections"])])
    else:
        pts=stations(row,gap);leading=np.array([[x,y,0.] for y,x,c in pts]);trailing=np.array([[x+c,y,0.] for y,x,c in pts])
    polygons=[]
    isolated=row.get("simulation_mode")==SIMULATION_MODE
    for side in ((1,) if isolated else (1,-1)):
        vertices=np.vstack([leading,trailing[::-1]])
        polygons.append(np.c_[side*(vertices[:,1]+(0 if isolated else gap/2)),vertices[:,0]])
    all_points=np.vstack(polygons);lo=all_points.min(axis=0);hi=all_points.max(axis=0)
    scale=max(float(np.max(hi-lo)),1e-12);center=(hi+lo)/2
    return [((p-center)/scale).tolist() for p in polygons]


def shape_landscape_data(rows,settings,repeat_only=True):
    """Measured glyphs plus interpolation, with no invented fixed-span surface.

    Duplicate area/AR locations retain all measured wings. Only the highest
    sampled ratio at each location defines the interpolated upper envelope.
    """
    import numpy as np
    points=[]
    for row in rows:
        if not shape_eligible(row,repeat_only):continue
        area=row.get("area_m2");thrust=row.get("single_wing_mean_thrust_N")
        if not isinstance(area,(int,float)) or not math.isfinite(area) or area<=0:continue
        if not isinstance(thrust,(int,float)) or not math.isfinite(thrust):continue
        points.append({"case_id":row["id"],"coords":[area,thrust,row[OBJECTIVE]],"aspect_ratio":row.get("aspect_ratio"),"value":row[OBJECTIVE],
            "repeatable":row.get("cycle_repeatable",False),"thumbnail":wing_thumbnail(row,settings["gap_m"]),
            "chords_m":[s["chord_m"] for s in row.get("sections",[])],
            "single_wing_mean_thrust_N":row["single_wing_mean_thrust_N"],
            "single_wing_peak_abs_roll_moment_Nm":row["single_wing_peak_abs_roll_moment_Nm"]})
    if not points:raise ValueError("No valid single-wing ratios with wing area and thrust. Rerun legacy cases or review the repeatability filter.")
    from .landscape_interpolation import interpolate
    vertices,triangles,curve,kind,selected=interpolate(points)
    note=("Bounded cubic surface inside the measured perimeter only; no extrapolation. Each patch stays within its measured corner values, with shared continuous edges. Rankings use measured values only." if triangles else
          "Smooth shape-preserving cubic curve through the sampled locations." if curve else "Measured points only.")
    if len(selected)==2:note+=" Two sample locations only constrain a straight thrust trend; more samples are needed to determine curvature."
    duplicates=len(points)-len(selected)
    if len(vertices)<2:note+=" At least two distinct descriptor locations are needed for interpolation."
    if duplicates:note+=f" {duplicates} additional shapes share area/thrust locations. All measured shapes are shown; interpolation follows the highest sampled ratio at each location."
    return {"axes":["area_m2","single_wing_mean_thrust_N",OBJECTIVE],"axis_labels":["Wing area (m²)","Single-wing mean thrust (N)","Thrust / roll moment (1/m)"],
            "points":points,"vertices":vertices.tolist(),"vertex_case_ids":[points[i]["case_id"] for i in selected],
            "triangles":triangles,"curve":curve,"interpolation_kind":kind,"duplicate_locations":duplicates,"distinct_locations":len(selected),
            "repeat_only":repeat_only,"note":note+" Interpolated values are estimates, not additional simulations. Area and thrust describe the simulated single wing; thumbnails are neutral top views normalized in size."}


def shape_landscape(study,repeat_only=True,export=True,*,selected_rows=None,selected_spec=None):
    """3D area / thrust / thrust-moment plot with wing-shaped markers."""
    import numpy as np
    from matplotlib.path import Path as MplPath
    from mpl_toolkits.mplot3d.art3d import Poly3DCollection
    study=Path(study)
    if selected_rows is None:
        manifest=read_json(study/"manifest.json");rows=read_json(study/"results.json")
        spec=shape_landscape_data(rows,manifest["settings"],repeat_only)
    else:
        rows=selected_rows;spec=selected_spec
    if not export:return spec
    plt=ieee_style();fig=plt.figure(figsize=(7.16,4.5),layout="constrained");ax=fig.add_subplot(111,projection="3d")
    coords=np.array([p["coords"] for p in spec["points"]])
    rendered=np.vstack([coords,*([np.array(spec["vertices"])] if spec["triangles"] else []),*([np.array(spec["curve"])] if spec["curve"] else [])]);z=rendered[:,2]
    from matplotlib.colors import Normalize
    norm=Normalize(vmin=float(min(z)),vmax=float(max(z)) if max(z)>min(z) else float(min(z))+1e-9)
    cmap=plt.get_cmap("cividis")
    verts=np.array(spec["vertices"])
    if spec["triangles"]:
        faces=verts[np.array(spec["triangles"])];mesh=Poly3DCollection(faces,facecolors=[cmap(norm(face[:,2].mean())) for face in faces],alpha=.65,edgecolors="none",linewidths=0,antialiased=False)
        ax.add_collection3d(mesh)
    if spec["curve"]:
        curve=np.array(spec["curve"]);ax.plot(*curve.T,color="#6d8b96",lw=1.1,alpha=.8,label="Interpolated upper envelope")
    for p in spec["points"]:
        vv=[];codes=[]
        for poly in p["thumbnail"]:
            vv.extend([*poly,poly[0]]);codes.extend([MplPath.MOVETO,*([MplPath.LINETO]*(len(poly)-1)),MplPath.CLOSEPOLY])
        ax.scatter(*p["coords"],marker=MplPath(vv,codes),s=170,c=[cmap(norm(p["value"]))],edgecolors="#183f4c",linewidths=.45,depthshade=False)
    for setter,label in zip((ax.set_xlabel,ax.set_ylabel,ax.set_zlabel),spec["axis_labels"]):setter(label,labelpad=9)
    ax.auto_scale_xyz(rendered[:,0],rendered[:,1],rendered[:,2]);ax.view_init(elev=25,azim=-55)
    from matplotlib.cm import ScalarMappable
    fig.colorbar(ScalarMappable(norm=norm,cmap=cmap),ax=ax,label=spec.get("color_label","Thrust / moment (1/m)"),shrink=.65,pad=.1)
    ax.set_title("Wing-shape landscape · measured wings + smooth "+("surface" if spec["triangles"] else "curve" if spec["curve"] else "points only"),fontsize=9)
    dest=study/"comparisons";dest.mkdir(parents=True,exist_ok=True)
    tag="repeatable" if repeat_only else "all";stem=dest/spec.get("export_stem",f"wing_shape_landscape_{tag}")
    save_figure(fig,stem);plt.close(fig)
    by_id={r["id"]:r for r in rows}
    with stem.with_suffix('.csv').open('w',newline='',encoding='utf-8') as f:
        records=[{"case_id":p["case_id"],"area_m2":p.get("area_m2",p["coords"][0]),"aspect_ratio":p["aspect_ratio"],spec.get("value_key",OBJECTIVE):p["value"],
            **{k:p[k] for k in (OBJECTIVE,"leading_edge_length_m","single_wing_span_m","effective_total_span_m","reference_total_span_m","omitted_zero_chord_count","span_shortened_by_zero_chords") if k in p},
            **{f"plot_{axis}":p['coords'][i] for i,axis in enumerate(('x','y','z'))},
            **{f"plot_{axis}_parameter":spec['axes'][i] for i,axis in enumerate(('x','y','z'))},
            "single_wing_mean_thrust_N":p["single_wing_mean_thrust_N"],"single_wing_peak_abs_roll_moment_Nm":p["single_wing_peak_abs_roll_moment_Nm"],
            "cycle_repeatable":p["repeatable"],"used_for_interpolation":p["case_id"] in spec["vertex_case_ids"],
            "interpolation_kind":spec["interpolation_kind"],"sections":json.dumps(by_id[p["case_id"]].get("sections",[])),
            "span_m":by_id[p["case_id"]]["span_m"],"note":spec["note"],
            **({"global_case_no":p["global_case_no"],"source_study":p["source_study"],"source_case":p["source_case"],
                "driving_and_solver_settings":json.dumps(by_id[p["case_id"]]["_settings"],sort_keys=True)} if "global_case_no" in p else {})} for p in spec["points"]]
        writer=csv.DictWriter(f,fieldnames=list(records[0]));writer.writeheader();writer.writerows(records)
    spec["file"]=(Path(study.name)/"comparisons"/(stem.name+".png")).as_posix()
    return spec


def comparison_data(rows, axes, metric, filters, mode="max", repeat_only=False):
    """Reduce only unchecked geometries; never combine different operating conditions."""
    if not isinstance(axes, list) or len(axes) not in (2,3) or len(set(axes)) != len(axes):
        raise ValueError("Select two or three different geometry axes.")
    if metric in (OBJECTIVE,"dimensionless_thrust_roll_score"):
        rows=[r for r in rows if shape_eligible(r,False)]
    geometry_keys=geometry_axes(rows)
    if any(key not in geometry_keys for key in axes):
        raise ValueError("Plot axes must be Section 1 geometry inputs.")
    if metric not in METRIC_LABELS or mode not in ("max", "slice"):
        raise ValueError("Unsupported plot metric or comparison mode.")
    if not isinstance(filters, dict) or any(key in axes for key in filters):
        raise ValueError("Slice filters must not include the selected plot axes.")
    def matches(row, key, value):
        actual = row.get(key,"sine" if key=="waveform_signature" else None)
        if isinstance(actual, (int, float)):
            try:
                return math.isclose(actual, float(value), rel_tol=1e-10, abs_tol=1e-12)
            except (TypeError, ValueError):
                return False
        return str(actual) == str(value)
    rows = [r for r in rows if r.get("status")=="ok" and
            all(matches(r,k,v) for k,v in filters.items()) and
            (not repeat_only or r.get("cycle_repeatable"))]
    if not rows:
        raise ValueError("No successful cases match these filters and repeatability settings.")
    constants = (*MOTION_KEYS, "rho", "nu", "dt_s", "cycles", "span_panels", "chord_panels", "wake_model", "wake_cycles","tail_signature","waveform_signature","simulation_mode","reference_grid_span_m","chord_count","aeroelastic_enabled","spring_constant_rad","wing_density","damping_constant_rad","step_discards")
    rows=[{**r,"wake_model":r.get("wake_model","free"),"wake_cycles":r.get("wake_cycles",0),"tail_signature":r.get("tail_signature","none"),"waveform_signature":r.get("waveform_signature","sine")} for r in rows]
    for key in constants:
        if len({r.get(key) for r in rows}) > 1:
            raise ValueError(f"These results vary {FIELDS.get(key,(key,''))[0]}. Fix it with the legacy-study filters before comparing geometries.")
    groups = {}
    for r in rows:
        value = r.get(metric)
        if value is None or not math.isfinite(float(value)):
            raise ValueError(f"{metric} is missing or non-finite for {r['id']}.")
        groups.setdefault(tuple(r[k] for k in axes),[]).append(r)
    points = []
    for coords, group in sorted(groups.items()):
        if mode == "slice" and len(group)>1:
            raise ValueError("More than one case occupies a cell. Fix the other geometry inputs, or select Best over unchecked geometries.")
        winner = max(group, key=lambda r:r[metric])
        points.append({"coords":list(coords), "value":winner[metric], "case_id":winner["id"],
                       "count":len(group), "repeatable":winner["cycle_repeatable"],
                       "metrics":{k:winner.get(k) for k in ("mean_thrust_N", "peak_thrust_N",
                           "mean_lift_N", "peak_lift_N", "cycle_error_pct",OBJECTIVE,"dimensionless_thrust_roll_score",
                           "single_wing_mean_thrust_N","single_wing_peak_abs_roll_moment_Nm")},
                       "inputs":{k:winner.get(k) for k in [*GEOMETRY_KEYS,*geometry_keys]}})
    reduced = [k for k in geometry_keys if k not in axes and k not in filters and
               len({r[k] for r in rows})>1]
    return {"axes":axes, "metric":metric, "label":METRIC_LABELS[metric],
            "mode":mode, "filters":filters, "repeat_only":repeat_only,
            "fixed_settings":{k:rows[0].get(k) for k in constants}, "reduced_over":reduced,
            "points":points, "source_case_count":len(rows),
            "note":("Maximum selected metric over unchecked geometry inputs; each point identifies its winning case. "
                     if mode=="max" else "Exact slice; no reduction or averaging. ") +
                    "No interpolation. Crosses indicate the winning case did not meet the cycle tolerance."}


def design_plot(study, axes, metric, filters, mode="max", repeat_only=False):
    import numpy as np
    study = Path(study).resolve()
    rows = read_json(study/"results.json")
    # Older studies predate signed peak metrics. Derive that metric from their saved
    # dimensional histories instead of substituting a peak absolute force.
    if metric == "peak_thrust_N":
        for r in rows:
            if r.get("status")=="ok" and metric not in r:
                data = np.asarray(case_data(study, r["id"])["history"])
                t = np.r_[r["window_start_s"], data[(data[:,0]>r["window_start_s"]) &
                    (data[:,0]<r["window_end_s"]),0], r["window_end_s"]]
                r[metric] = float(np.max(np.interp(t,data[:,0],data[:,1])))
    spec = comparison_data(rows, axes, metric, filters, mode, repeat_only)
    points = spec["points"]
    plt = ieee_style()
    def label_for(key):
        name, unit = FIELDS[key]; return name+(f" ({unit})" if unit else "")
    name = METRIC_LABELS[metric]
    label = ("Max. " if mode=="max" else "") + name[0].lower()+name[1:]
    if len(axes)==2:
        xs,ys = [sorted({p["coords"][i] for p in points}) for i in range(2)]
        z = np.full((len(ys),len(xs)),np.nan)
        for p in points:
            z[ys.index(p["coords"][1]),xs.index(p["coords"][0])] = p["value"]
        fig,ax = plt.subplots(figsize=(3.5,2.9),layout="constrained")
        image = ax.imshow(np.ma.masked_invalid(z), origin="lower", aspect="auto", cmap="cividis", interpolation="nearest")
        # Sparse ticks keep large grids legible while retaining every sampled cell.
        for vals,setter in ((xs,ax.set_xticks),(ys,ax.set_yticks)):
            idx = np.unique(np.linspace(0,len(vals)-1,min(6,len(vals))).round().astype(int))
            setter(idx,[f"{vals[i]:g}" for i in idx])
        ax.set_xlabel(label_for(axes[0])); ax.set_ylabel(label_for(axes[1]))
        for p in points:
            if not p["repeatable"]:
                ax.plot(xs.index(p["coords"][0]),ys.index(p["coords"][1]),"x",color="white",ms=5,mew=.8)
    else:
        # Use a two-column figure for readable 3D labels and a separate color scale.
        fig = plt.figure(figsize=(7.16,4.1),layout="constrained")
        ax = fig.add_subplot(111,projection="3d")
        coords = np.array([p["coords"] for p in points]); v = [p["value"] for p in points]
        image = ax.scatter(*coords.T,c=v,cmap="cividis",s=36,edgecolors=".2",linewidths=.35,depthshade=False)
        ax.set_xlabel(label_for(axes[0]),labelpad=7); ax.set_ylabel(label_for(axes[1]),labelpad=7)
        ax.set_zlabel(label_for(axes[2]),labelpad=7)
        for p in points:
            if not p["repeatable"]:
                ax.scatter(*p["coords"],marker="x",color="white",s=20,linewidths=.8,depthshade=False)
        ax.view_init(elev=24,azim=-55)
    fig.colorbar(image,ax=ax,label=label,shrink=.8,pad=.12 if len(axes)==3 else .04)
    dest = study/"comparisons"; dest.mkdir(exist_ok=True)
    tag = hashlib.sha256(json.dumps(spec,sort_keys=True).encode()).hexdigest()[:10]
    stem = dest/f"design_{metric}_{tag}"
    save_figure(fig,stem); plt.close(fig)
    with stem.with_suffix(".csv").open("w",newline="",encoding="utf-8") as f:
        records = [{**dict(zip(axes,p["coords"])), "selected_metric":metric,
                    "selected_value":p["value"], "winning_case":p["case_id"],
                    "source_cases":p["count"], "cycle_repeatable":p["repeatable"],
                    **p["metrics"], **{f"winner_{k}":v for k,v in p["inputs"].items()}}
                   for p in points]
        writer = csv.DictWriter(f, fieldnames=list(records[0]))
        writer.writeheader(); writer.writerows(records)
    spec["file"] = str(stem.with_suffix(".png").relative_to(OUTPUTS)).replace("\\","/")
    return spec


def heatmap(study, x, y, metric, filters):
    """Compatibility entry point for exact two-axis plots."""
    return design_plot(study,[x,y],metric,filters,mode="slice")["file"]


def overlay(references):
    """Publish phase-aligned comparisons without altering the raw case histories."""
    import numpy as np
    if not isinstance(references, list) or not 1 <= len(references) <= 4:
        raise ValueError("Choose 1–4 cases.")
    curves = []
    modes=set()
    for ref in references:
        if not re.fullmatch(r"[A-Za-z0-9_-]+", ref["study"]) or not re.fullmatch(r"case_\d{4,}", ref["id"]):
            raise ValueError("Invalid case reference.")
        saved = case_data(OUTPUTS/ref["study"], ref["id"])
        metrics, case = saved["metrics"], saved["case"]
        modes.add(metrics.get("simulation_mode","legacy_paired"))
        if len(modes)>1:raise ValueError("Cannot overlay isolated single-wing and legacy paired-wing loads.")
        data = np.asarray(saved["history"])
        phase = np.linspace(0, 1, 201)
        times = metrics["window_start_s"] + phase/case["frequency_hz"]
        curves.append((ref, metrics, phase, np.interp(times,data[:,0],data[:,1]),
                       np.interp(times,data[:,0],data[:,2])))
    dest = OUTPUTS/references[0]["study"]/"comparisons"; dest.mkdir(exist_ok=True)
    tag = hashlib.sha256(json.dumps(references, sort_keys=True).encode()).hexdigest()[:10]
    stem = dest/f"overlay_{tag}"
    plt = ieee_style()
    fig, axes = plt.subplots(2,1,figsize=(3.5,3.5), sharex=True, layout="constrained")
    colors = ["#0072B2", "#D55E00", "#009E73", "#8C5A9E"]
    for i,(ref, metrics, phase, thrust, lift) in enumerate(curves):
        # Compact figure key; full study/case reference retained in the CSV.
        label = f"{i+1}: {ref['id']}"
        axes[0].plot(phase, thrust, label=label, color=colors[i], linestyle=["-","--","-.",":"][i])
        axes[1].plot(phase, lift, color=colors[i], linestyle=["-","--","-.",":"][i])
    axes[0].legend(frameon=False)
    for ax,label in zip(axes,["Thrust (N)","Lift (N)"]):
        ax.set_ylabel(label); ax.axhline(0,color=".5",lw=.5); ax.grid(alpha=.18,lw=.4)
    axes[-1].set_xlabel("Cycle phase")
    save_figure(fig,stem); plt.close(fig)
    with stem.with_suffix(".csv").open("w",newline="",encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["curve", "study", "case", "cycle_phase", "thrust_N", "lift_N"])
        for i,(ref,metrics,phase,thrust,lift) in enumerate(curves):
            writer.writerows([i+1,ref["study"],ref["id"],p,t,l] for p,t,l in zip(phase,thrust,lift))
    return str(stem.with_suffix(".png").relative_to(OUTPUTS)).replace("\\","/")
