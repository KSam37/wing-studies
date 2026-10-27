"""Persistent run identities, conservative result reuse, and the master Excel view.

The portable application uses Python's built-in SQLite and OpenXML support. Excel
is a generated view: opening it never locks the simulation records themselves.
"""
from __future__ import annotations
import ast
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import sqlite3
import time
from datetime import datetime, timezone
import xml.etree.ElementTree as ET
import zipfile

OBJECTIVE = "single_wing_thrust_roll_ratio_1pm"
METRICS = {
    "single_wing_mean_thrust_N":"Single-wing mean thrust (N)",
    "estimated_two_wing_mean_thrust_N":"Estimated pair mean thrust (N)",
    "single_wing_peak_abs_roll_moment_Nm":"Peak absolute roll moment (N m)",
    "single_wing_rms_roll_moment_Nm":"RMS roll (N m)",
    OBJECTIVE:"Thrust to peak roll moment (1/m)",
    "dimensionless_thrust_roll_score":"L T/M (dimensionless)",
    "mean_lift_N":"Mean lift (N)", "rms_lift_N":"RMS lift (N)",
    "peak_abs_lift_N":"Peak absolute lift (N)"}
PARAM_HEADERS = ["Case #","Origin study","Local case","State","Recorded UTC","Simulation mode",
    "Wing span (m)","Area (m2)","Aspect ratio","Entered chords (m)","Active sections (SI, deg)",
    "Frequency (Hz)","Half-stroke amplitude (deg)","Forward speed (m/s)","Waveform",
    "Waveform points","Density (kg/m3)","Kinematic viscosity (m2/s)","Time step (s)","Cycles",
    "Span panels","Chord panels","Wake model","Retained wake cycles","Cycle tolerance (%)",
    "Leading-edge sweep (deg)","Incidence (deg)","Static tail","Ptera version","Solver identity",
    "Run occurrences","All study / case locations","Outputs","Interactive case","Native aeroelasticity","Shared spring (Nm/rad)","Wing mass per area (kg/m2)","Damping (Nms/rad)","Startup hold (steps)"]
RESULT_HEADERS = ["Rank","Case #","Origin study","Local case","State","Repeatable cycles","Cycle error (%)",
    *METRICS.values(),"Ranking value","Rank eligible (1/0)","Area (m2)","Aspect ratio","Wing span (m)","Simulation mode",
    "Outputs","Interactive case","Last error"]
NS="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
RNS="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
ET.register_namespace("",NS)
PHYSICS_NAMES={"FlapWave","FlapAcceleration","build_aeroelastic_solver","build_solver","sweep_sections","custom_sections","custom_frames",
    "custom_transforms","solver_from_wing","single_wing_forces","wing_root_roll_moment",
    "shape_metrics","cycle_metrics","run_case"}

def compact(value):return json.dumps(value,sort_keys=True,separators=(",",":"),allow_nan=False)
def stamp():return datetime.now(timezone.utc).isoformat(timespec="seconds")
def root(model):return model.OUTPUTS.parent
class ClosingConnection(sqlite3.Connection):
    def __exit__(self,*args):
        try:return super().__exit__(*args)
        finally:self.close()
def connect(model,filename="master_runs.sqlite3"):
    root(model).mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(root(model)/filename,timeout=30,factory=ClosingConnection)
    db.row_factory=sqlite3.Row
    db.executescript("""CREATE TABLE IF NOT EXISTS cases (
        case_no INTEGER PRIMARY KEY AUTOINCREMENT, signature TEXT UNIQUE NOT NULL,
        payload TEXT NOT NULL, result TEXT, origin_study TEXT, origin_case TEXT,
        state TEXT NOT NULL, recorded TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS occurrences (study TEXT, local_case TEXT, case_no INTEGER,
        state TEXT, reused INTEGER DEFAULT 0, PRIMARY KEY(study,local_case));
      CREATE TABLE IF NOT EXISTS imports (study TEXT PRIMARY KEY, revision TEXT);
      CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY,value TEXT);""")
    return db

def old_connection(model):
    path=root(model)/"master_runs_old.sqlite3"
    db=sqlite3.connect(path.as_uri()+"?mode=ro",uri=True,factory=ClosingConnection)
    db.row_factory=sqlite3.Row
    return db

def start_fresh(model):
    """Explicit, one-time archive; existing studies and case numbers stay intact."""
    with connect(model) as db:
        if db.execute("SELECT value FROM meta WHERE key='archive_studies'").fetchone():return False
    sync(model)
    directory=root(model);old=directory/"master_runs_old.sqlite3"
    if old.exists() or (directory/"master_runs_old.xlsx").exists():
        raise ValueError("An Old master already exists. Preserve it before starting another generation.")
    if not (directory/"master_runs.xlsx").exists():export(model)
    # Copy the existing workbook verbatim and use SQLite's consistent backup API.
    shutil.copy2(directory/"master_runs.xlsx",directory/"master_runs_old.xlsx")
    with connect(model) as db,sqlite3.connect(old,factory=ClosingConnection) as backup:
        db.backup(backup)
        maximum=db.execute("SELECT COALESCE(MAX(case_no),0) FROM cases").fetchone()[0]
    studies=[p.name for p in model.OUTPUTS.iterdir() if (p/"manifest.json").is_file()]
    staged="master_runs_new.sqlite3"
    with connect(model,staged) as fresh:
        fresh.execute("INSERT INTO meta VALUES('archive_studies',?)",(compact(studies),))
        fresh.execute("INSERT INTO meta VALUES('generation_started',?)",(stamp(),))
        fresh.execute("INSERT INTO sqlite_sequence(name,seq) VALUES('cases',?)",(maximum,))
    os.replace(directory/staged,directory/"master_runs.sqlite3")
    export(model,metric="single_wing_mean_thrust_N")
    return True

def cache_entries(model,signatures):
    """Both generations remain available for exact physical-result reuse."""
    entries={}
    if (root(model)/"master_runs_old.sqlite3").exists():
        with old_connection(model) as db:
            entries.update({r["signature"]:r for r in db.execute("SELECT * FROM cases WHERE state='ok'") if r['signature'] in signatures and available(model,r)})
    with connect(model) as db:
        entries.update({r["signature"]:r for r in db.execute("SELECT * FROM cases WHERE state='ok'") if r['signature'] in signatures and available(model,r)})
    return entries

def generations(model,selected=("current",)):
    if not isinstance(selected,(list,tuple)) or any(v not in ("current","old") for v in selected):
        raise ValueError("Choose Current and/or Old master.")
    rows=[];counts={};seen=set()
    for name in ("current","old"):
        if name=='old' and not (root(model)/"master_runs_old.sqlite3").exists():
            counts[name]=0;continue
        with (connect(model) if name=='current' else old_connection(model)) as db:
            counts[name]=db.execute("SELECT COUNT(*) FROM cases").fetchone()[0]
            data=listing(model,_db=db,check_outputs=False) if name in selected else {"rows":[]}
        for row in data['rows']:
            if row['_signature'] in seen:continue
            seen.add(row['_signature'])
            rows.append({**row,'catalog_generation':name,'comparison_key':f"{name}:{row['global_case_no']}",
                'aeroelastic_enabled':row['_settings'].get('aeroelastic_enabled',False)})
    return {'rows':rows,'generations':counts,'selected':list(selected)}

AEROELASTIC_KEYS={"aeroelastic_enabled","spring_constant_rad","wing_density","damping_constant_rad","step_discards"}

def physics_digest(source,rigid=False):
    tree=ast.parse(source)
    nodes=[n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.ClassDef)) and n.name in PHYSICS_NAMES]
    if rigid:
        # Project away only the explicit opt-in dispatch and aeroelastic-only reporting.
        # All rigid load, movement and geometry code remains in the fingerprint.
        nodes=[n for n in nodes if n.name not in ("FlapAcceleration","build_aeroelastic_solver")]
        for node in nodes:
            if node.name=="build_solver":
                node.body=[n for n in node.body if not (isinstance(n,ast.If) and ast.dump(n.test)==ast.dump(ast.parse('settings.get("aeroelastic_enabled",False)',mode='eval').body))]
            if node.name=="run_case":
                node.body=[n for n in node.body if not (
                    isinstance(n,ast.If) and ast.dump(n.test)==ast.dump(ast.parse('settings.get("aeroelastic_enabled",False)',mode='eval').body) or
                    isinstance(n,ast.Expr) and isinstance(n.value,ast.Call) and any(k.arg=="aeroelastic_enabled" for k in n.value.keywords))]
    return hashlib.sha256(compact([ast.dump(n,include_attributes=False) for n in nodes]).encode()).hexdigest()

def physical_settings(settings):
    values={k:v for k,v in settings.items() if k not in ("case_budget","save_solver","gap_m")}
    if not values.get("aeroelastic_enabled",False):values={k:v for k,v in values.items() if k not in AEROELASTIC_KEYS}
    return values


_ENGINE={}
_RIGID_ENGINE={}
def engine(model,settings=None):
    """Actual solver code and dependency versions, independent of installation path."""
    if str(model.HERE) not in _ENGINE:
        import importlib.metadata as md
        files={p.relative_to(model.PTERA).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
               for p in (model.PTERA/"pterasoftware").rglob("*")
               if p.is_file() and "__pycache__" not in p.parts and p.suffix not in (".pyc",".nbc",".nbi")}
        _ENGINE[str(model.HERE)]={"physics":physics_digest((model.HERE/"model.py").read_text(encoding="utf-8")),
            "native":files,"packages":{n:md.version(n) for n in ("PteraSoftware","numpy","scipy","numba")}}
    identity=_ENGINE[str(model.HERE)]
    if settings is None or not settings.get("aeroelastic_enabled",False):
        if str(model.HERE) not in _RIGID_ENGINE:
            _RIGID_ENGINE[str(model.HERE)]={**identity,"physics":physics_digest((model.HERE/"model.py").read_text(encoding="utf-8"),rigid=True)}
        identity=_RIGID_ENGINE[str(model.HERE)]
    return identity

_HISTORICAL={}
def verified_import(model,manifest):
    """Audit old v3 code against the archived release before permitting reuse."""
    if manifest.get("catalog_engine")==engine(model,manifest.get("settings",{})):return True
    version=manifest.get("companion_version","")
    key=(version,bool(manifest.get("settings",{}).get("aeroelastic_enabled",False)))
    if key not in _HISTORICAL:
        path=root(model)/"share"/f"WingStudies-Windows-x64-{version}.zip"
        try:
            proof=root(model)/"provenance"/(version+".json")
            if proof.is_file():
                record=json.loads(proof.read_text(encoding="utf-8"))
                old=record["physics"];native=record["native"];report=record
            else:
                with zipfile.ZipFile(path) as z:
                    prefix=f"WingStudies-Windows-x64-{version}/"
                    report=json.loads(z.read(prefix+"support/bundle.json"))
                    old=physics_digest(z.read(prefix+"WingStudy/model.py").decode("utf-8"))
                    native={k.removeprefix("PteraSoftware/"):v for k,v in report["sha256"].items()
                            if k.startswith("PteraSoftware/pterasoftware/")}
            current=engine(model,manifest.get("settings",{}))
            _HISTORICAL[key]={"matches":old==current["physics"] and native==current["native"] and
                all(report["packages"].get(k)==v for k,v in current["packages"].items()),"commit":report.get("ptera_commit")}
        except (OSError,ValueError,KeyError,zipfile.BadZipFile):_HISTORICAL[key]={"matches":False}
    old=_HISTORICAL[key]
    return (old["matches"] and old.get("commit")==manifest.get("ptera_commit") and
        "pterasoftware/" not in manifest.get("ptera_worktree","").replace("\\","/").lower() and
        manifest.get("ptera_version")==engine(model)["packages"]["PteraSoftware"])

def signature(model,case,settings,identity=None):
    # Root gap and grid labels do not affect an isolated sectioned wing's mesh.
    geometry={"sections":case["sections"]} if "sections" in case else {
        k:case[k] for k in model.GEOMETRY_KEYS}|{"gap_m":settings["gap_m"]}
    current=engine(model,settings)
    settings=physical_settings(settings)
    identity_hash=hashlib.sha256(compact(current if identity is None else identity).encode()).hexdigest()
    value={"contract":2,"geometry":geometry,"settings":settings,"engine":identity_hash}
    return hashlib.sha256(compact(value).encode()).hexdigest()

def _register(db,signature_value,payload,study,local_case,state="planned",result=None):
    entry=db.execute("SELECT * FROM cases WHERE signature=?",(signature_value,)).fetchone()
    if entry is None:
        db.execute("INSERT OR IGNORE INTO cases(signature,payload,origin_study,origin_case,state,recorded) VALUES(?,?,?,?,?,?)",
            (signature_value,compact(payload),study,local_case,state,stamp()))
        entry=db.execute("SELECT * FROM cases WHERE signature=?",(signature_value,)).fetchone()
    if result is not None and not (result.get("reused_from") and entry["state"]=="ok") and (result.get("status")=="ok" or entry["state"]!="ok"):
        db.execute("UPDATE cases SET result=?,payload=?,origin_study=?,origin_case=?,state=?,recorded=? WHERE case_no=?",
            (compact(result),compact(payload),study,local_case,result.get("status","failed"),stamp(),entry["case_no"]))
    db.execute("INSERT INTO occurrences(study,local_case,case_no,state,reused) VALUES(?,?,?,?,?) "
        "ON CONFLICT(study,local_case) DO UPDATE SET case_no=excluded.case_no,state=excluded.state,reused=excluded.reused",
        (study,local_case,entry["case_no"],state,int(bool(result and result.get("reused_from")))))
    return int(entry["case_no"])

def sync(model):
    """Import/reconcile existing studies without modifying their historical files."""
    if not model.OUTPUTS.exists():return
    with connect(model) as db:
        boundary=db.execute("SELECT value FROM meta WHERE key='archive_studies'").fetchone()
        archived=set(json.loads(boundary[0])) if boundary else set()
        for study in sorted(model.OUTPUTS.iterdir()):
            if study.name in archived:continue
            manifest_path=study/"manifest.json";result_path=study/"results.json"
            if not manifest_path.is_file():continue
            status_path=study/"status.json"
            revision=f"{manifest_path.stat().st_mtime_ns}:{result_path.stat().st_mtime_ns if result_path.exists() else 0}:{result_path.stat().st_size if result_path.exists() else 0}:{status_path.stat().st_mtime_ns if status_path.exists() else 0}"
            prior=db.execute("SELECT revision FROM imports WHERE study=?",(study.name,)).fetchone()
            if prior and prior[0]==revision:continue
            try:
                manifest=model.read_json(manifest_path);rows=model.read_json(result_path) if result_path.exists() else []
                known={c["id"]:c for c in manifest["cases"]}
                reusable=(manifest["settings"].get("simulation_mode")==model.SIMULATION_MODE and verified_import(model,manifest))
                for row in rows:
                    case=known[row["id"]]
                    identity=engine(model,manifest["settings"]) if reusable else {"historical_unverified":study.name,"case":row["id"]}
                    sig=signature(model,case,manifest["settings"],identity)
                    payload={"case":case,"settings":manifest["settings"],"study_name":manifest["name"],
                        "ptera_version":manifest.get("ptera_version"),"reuse_verified":reusable}
                    _register(db,sig,payload,study.name,row["id"],row.get("status","failed"),row)
                finished={r["id"] for r in rows}
                state=model.read_json(status_path).get("state","planned") if status_path.exists() else "planned"
                for local_case,case in known.items():
                    if local_case in finished:continue
                    identity=engine(model,manifest["settings"]) if reusable else {"historical_unverified":study.name,"case":local_case}
                    sig=signature(model,case,manifest["settings"],identity)
                    payload={"case":case,"settings":manifest["settings"],"study_name":manifest["name"],
                        "ptera_version":manifest.get("ptera_version"),"reuse_verified":reusable}
                    _register(db,sig,payload,study.name,local_case,"planned" if state=="running" else state)
                db.execute("INSERT OR REPLACE INTO imports VALUES(?,?)",(study.name,revision))
            except (OSError,ValueError,KeyError,TypeError):continue

def prepare(model,spec,study):
    spec["catalog_engine"]=engine(model,spec["settings"])
    with connect(model) as db:
        for case in spec["cases"]:
            payload={"case":case,"settings":spec["settings"],"study_name":spec["name"],
                "ptera_version":spec.get("ptera_version"),"reuse_verified":True}
            case["global_case_no"]=_register(db,signature(model,case,spec["settings"]),payload,study,case["id"])

def record(model,manifest,study,row):
    case=next(c for c in manifest["cases"] if c["id"]==row["id"])
    payload={"case":case,"settings":manifest["settings"],"study_name":manifest["name"],
        "ptera_version":manifest.get("ptera_version"),"reuse_verified":True}
    with connect(model) as db:
        row["global_case_no"]=_register(db,signature(model,case,manifest["settings"]),payload,study,row["id"],row["status"],row)

CASE_FILES=["water_wing_forces.png","water_wing_moments.png","water_wing_force_coefficients.png",
    "water_wing_moment_coefficients.png","animation.webp","wing_left.svg","wing_right.svg"]
def available(model,entry):
    directory=model.OUTPUTS/entry["origin_study"]/entry["origin_case"]
    return entry["state"]=="ok" and all((directory/n).is_file() and (directory/n).stat().st_size>40 for n in CASE_FILES) and (directory.parent/"comparisons/time_histories.csv").is_file()

def reuse(model,case,settings,directory):
    import numpy as np
    sig=signature(model,case,settings)
    entry=cache_entries(model,{sig}).get(sig)
    if not entry or not available(model,entry):return None
    source=model.OUTPUTS/entry["origin_study"]
    if source.resolve()==directory.parent.resolve() and entry["origin_case"]==case["id"]:return None
    saved=model.case_data(source,entry["origin_case"])
    columns=model.HISTORY_COLUMNS+model.SINGLE_WING_HISTORY_COLUMNS+model.TORQUE_HISTORY_COLUMNS
    if saved["history_columns"]!=columns or not saved["history"] or not np.isfinite(np.asarray(saved["history"])).all():return None
    destination=directory.parent/"comparisons/time_histories.csv"
    if destination.exists():
        with destination.open(newline="",encoding="utf-8") as f:
            if next(csv.reader(f))!=["case",*columns]:return None
    # Native outputs are identical; regenerate the templates with the new local ID.
    for name in CASE_FILES[:5]:shutil.copy2(source/entry["origin_case"]/name,directory/name)
    model.save_wing_profiles(case,settings,directory)
    destination.parent.mkdir(exist_ok=True)
    fresh=not destination.exists()
    with destination.open("a",newline="",encoding="utf-8") as f:
        writer=csv.writer(f)
        if fresh:writer.writerow(["case",*columns])
        writer.writerows([case["id"],*values] for values in saved["history"])
    excluded=set(saved["case"])|{"id","status","elapsed_s","global_case_no","reused_from"}
    metrics={k:v for k,v in saved["metrics"].items() if k not in excluded}
    metrics["reused_from"]={"study":entry["origin_study"],"case":entry["origin_case"],"global_case_no":entry["case_no"]}
    print(f"Reused master case #{entry['case_no']} from {entry['origin_study']}/{entry['origin_case']}",flush=True)
    return metrics

def preview(model,spec):
    signatures=[signature(model,c,spec['settings']) for c in spec['cases']]
    existing=cache_entries(model,set(signatures))
    reused=sum(sig in existing for sig in signatures)
    return {"cached_case_count":reused,"new_simulation_count":len(spec["cases"])-reused}

def listing(model,metric=OBJECTIVE,descending=True,_db=None,check_outputs=True):
    if metric not in METRICS:raise ValueError("Choose a supported ranking metric.")
    db=_db or connect(model)
    try:
        entries=list(db.execute("SELECT * FROM cases"));occurrences=list(db.execute("SELECT * FROM occurrences ORDER BY study,local_case"))
        meta=dict(db.execute("SELECT key,value FROM meta"))
    finally:
        if _db is None:db.close()
    rows=[]
    for e in entries:
        payload=json.loads(e["payload"]);result=json.loads(e["result"] or "{}")
        case=payload["case"];s=payload["settings"];g=case.get("geometry",{})
        isolated=s.get("simulation_mode")==model.SIMULATION_MODE
        span=(case["span_m"]-s["gap_m"])/2
        area=g.get("area_m2",0)/(2 if isolated else 1)
        geometry={"area_m2":area or None,"aspect_ratio":span**2/area if isolated and area else g.get("aspect_ratio"),
                  "single_wing_span_m":span}
        rows.append({**case,**geometry,**result,"global_case_no":e["case_no"],"catalog_state":e["state"],
            "_study":e["origin_study"],"_studyName":payload["study_name"],"_settings":payload["settings"],
            "_ptera_version":payload.get("ptera_version"),"_signature":e["signature"],"_recorded":e["recorded"],
            "_verified":payload.get("reuse_verified",False),"outputs_available":available(model,e) if check_outputs else None,
            "occurrences":[dict(o) for o in occurrences if o["case_no"]==e["case_no"]]})
    def valid(r):return isinstance(r.get(metric),(int,float)) and math.isfinite(r[metric]) and r.get("status")=="ok"
    rows.sort(key=lambda r:(not valid(r),(-r[metric] if descending else r[metric]) if valid(r) else 0,r["global_case_no"]))
    last=None;rank=0
    for i,r in enumerate(rows,1):
        if valid(r):
            if last!=r[metric]:rank=i;last=r[metric]
            r["catalog_rank"]=rank
        else:r["catalog_rank"]=None
    return {"rows":rows,"metric":metric,"descending":descending,"metrics":METRICS,
        "case_count":len(rows),"occurrence_count":len(occurrences),"excel_pending":meta.get("excel_pending",""),
        "excel_updated":meta.get("excel_updated",""),"workbook_path":str(root(model)/"master_runs.xlsx")}

def landscape_data(model,rows,case_numbers):
    """Resolve only explicitly selected global IDs; never merge local case IDs."""
    if not isinstance(case_numbers,list) or not case_numbers or any(type(n) is not int for n in case_numbers):
        raise ValueError("Select at least one completed case for the 3D plot.")
    if len(case_numbers)!=len(set(case_numbers)):
        raise ValueError("Case numbers must be unique.")
    by_number={r["global_case_no"]:r for r in rows}
    if any(n not in by_number for n in case_numbers):raise ValueError("A selected case is no longer in the catalog. Refresh it.")
    selected=[]
    for n in case_numbers:
        r=dict(by_number[n])
        if not model.shape_eligible(r,False):raise ValueError(f"Case #{n} has no valid thrust/moment result.")
        r["id"]=f"master_{n:06d}";selected.append(r)
    spec=model.shape_landscape_data(selected,selected[0]["_settings"],False)
    if len(spec["points"])!=len(selected):raise ValueError("A selected case has missing wing-area/thrust data.")
    lookup={r["id"]:r for r in selected}
    for p in spec["points"]:
        r=lookup[p["case_id"]]
        original=by_number[r["global_case_no"]]
        p.update(global_case_no=r["global_case_no"],source_study=r["_study"],source_case=original["id"],
                 thumbnail=model.wing_thumbnail(r,r["_settings"]["gap_m"]))
    conditions={json.dumps(physical_settings(r["_settings"]),sort_keys=True) for r in selected}
    if len(conditions)>1 or any(not r["_verified"] for r in selected):
        spec.update(triangles=[],curve=[],vertex_case_ids=[],interpolation_kind="points")
        spec["note"]="Measured points only: driving/solver conditions differ or provenance is unverified. Filter to consistent verified conditions to enable interpolation. "+spec["note"]
    return selected,spec

def landscape(model,case_numbers):
    selected,spec=landscape_data(model,listing(model)["rows"],case_numbers)
    # Content-addressed comparison folder preserves earlier exports, without making
    # a study manifest or altering any original study or master workbook.
    digest=hashlib.sha256(json.dumps([(r["global_case_no"],r["_signature"],r[OBJECTIVE]) for r in selected]).encode()).hexdigest()[:16]
    return model.shape_landscape(model.OUTPUTS/("compiled-view-"+digest),False,True,selected_rows=selected,selected_spec=spec)

def column(i):
    out=""
    while i:i,n=divmod(i-1,26);out=chr(65+n)+out
    return out

def export(model,metric=OBJECTIVE,descending=True,browser_url="http://127.0.0.1:8765",force=True):
    """Fill the Artifact Tool-authored template using only the portable standard library."""
    with connect(model) as db:
        db.execute("BEGIN IMMEDIATE")
        previous=db.execute("SELECT value FROM meta WHERE key='excel_export_time'").fetchone()
        if not force and previous and time.time()-float(previous[0])<15:return
        data=listing(model,metric,descending,_db=db);rows=data["rows"]
        tables=[[],[]]
        for r in sorted(rows,key=lambda r:r["global_case_no"]):
            s=r["_settings"];sections=r.get("requested_sections",r.get("sections",[]))
            waveform=s.get("waveform",{"mode":"sine"})
            tables[0].append([r["global_case_no"],r["_study"],r["id"],r["catalog_state"],r["_recorded"],r.get("simulation_mode","legacy paired"),
                r.get("single_wing_span_m",r.get("reference_half_span_m")),r.get("area_m2"),r.get("aspect_ratio"),
                " / ".join(str(x["chord_m"]) for x in sections),compact(r.get("sections",{k:r.get(k) for k in model.GEOMETRY_KEYS})),
                r.get("frequency_hz",s.get("frequency_hz")),r.get("amplitude_deg",s.get("amplitude_deg")),r.get("speed_mps",s.get("speed_mps")),waveform.get("mode"),compact(waveform.get("points",[])),
                *[s.get(k) for k in ("rho","nu","dt_s","cycles","span_panels","chord_panels","wake_model","wake_cycles","cycle_tolerance_pct")],
                r.get("sweep_deg"),r.get("incidence_deg"),bool(s.get("tail",{}).get("enabled")),r["_ptera_version"],r["_signature"],
                len(r["occurrences"]),"\n".join(o["study"]+" / "+o["local_case"]+(" (reused)" if o["reused"] else "") for o in r["occurrences"]),
                ("link",f"studies/{r['_study']}/{r['id']}/","Open outputs"),("link",f"{browser_url}/#catalog&case={r['global_case_no']}","Open case"),
                bool(s.get("aeroelastic_enabled",False)),*[s.get(k) if s.get("aeroelastic_enabled",False) else None for k in ("spring_constant_rad","wing_density","damping_constant_rad","step_discards")]])
        for r in rows:
            tables[1].append([r["catalog_rank"],r["global_case_no"],r["_study"],r["id"],r["catalog_state"],r.get("cycle_repeatable"),r.get("cycle_error_pct"),
                *[r.get(k) for k in METRICS],r.get(metric) if r["catalog_rank"] is not None else None,int(r["catalog_rank"] is not None),r.get("area_m2"),r.get("aspect_ratio"),r.get("single_wing_span_m",r.get("reference_half_span_m")),r.get("simulation_mode","legacy paired"),
                ("link",f"studies/{r['_study']}/{r['id']}/","Open outputs"),("link",f"{browser_url}/#catalog&case={r['global_case_no']}","Open case"),r.get("error")])
        template=Path(__file__).with_name("master_template.xlsx")
        tmp=root(model)/"master_runs.xlsx.tmp"
        with zipfile.ZipFile(template) as source,zipfile.ZipFile(tmp,"w",zipfile.ZIP_DEFLATED) as dest:
            link_relationships={}
            for info in source.infolist():
                content=source.read(info.filename)
                if info.filename in ("xl/worksheets/sheet1.xml","xl/worksheets/sheet2.xml"):
                    index=0 if info.filename.endswith("sheet1.xml") else 1
                    sheet=ET.fromstring(content);ns={"s":NS};body=sheet.find("s:sheetData",ns);links=[]
                    styles={c.attrib["r"]:c.get("s","0") for row in body for c in row}
                    for row in list(body):body.remove(row)
                    for tag in ("autoFilter","mergeCells","dataValidations","tableParts","hyperlinks","conditionalFormatting"):
                        for el in sheet.findall("s:"+tag,ns):sheet.remove(el)
                    headers=PARAM_HEADERS if index==0 else RESULT_HEADERS;last=max(6,len(tables[index])+5)
                    def add_row(n,values,height=28):
                        row=ET.SubElement(body,f"{{{NS}}}row",r=str(n),ht=str(height),customHeight="1")
                        for j,value in enumerate(values,1):
                            if value is None:continue
                            ref=column(j)+str(n);style=styles.get("A5" if n==5 else "A1" if n==1 else "A2" if n<5 else "A6","0")
                            cell=ET.SubElement(row,f"{{{NS}}}c",r=ref,s=style)
                            if isinstance(value,tuple):
                                cell.set("s",styles.get("E6",style));cell.set("t","inlineStr")
                                ET.SubElement(ET.SubElement(cell,f"{{{NS}}}is"),f"{{{NS}}}t").text=value[2]
                                links.append((ref,value[1]))
                            elif isinstance(value,(int,float)) and not isinstance(value,bool):
                                cell.set("s",styles.get("D6" if j<=2 else "C6" if 0<abs(value)<.0001 else "B6",style))
                                ET.SubElement(cell,f"{{{NS}}}v").text=repr(value)
                            else:
                                cell.set("t","inlineStr");inline=ET.SubElement(cell,f"{{{NS}}}is")
                                ET.SubElement(inline,f"{{{NS}}}t").text=("Yes" if value else "No") if isinstance(value,bool) else str(value)[:32767]
                        return row
                    add_row(1,["Wing parameters" if index==0 else "Ranked wing results"],30)
                    add_row(2,[f"{len(rows)} parameter sets · {data['occurrence_count']} study/case occurrences · refreshed {stamp()}",None,None,("link",browser_url+"/#catalog","Open interactive catalog")])
                    if index==0:
                        add_row(3,["Generated from run records. Create/edit studies in the app; Excel edits do not alter cached simulations."])
                        add_row(4,["Case # is permanent. Identical settings reuse it. Legacy/unverified results remain documented but cannot be reused."])
                    else:
                        add_row(3,["Rank by",METRICS[metric],None,"Highest first" if descending else "Lowest first"],38)
                        add_row(4,["Choose B3/D3, then sort Rank ascending to reorder in Excel. Browser ranking reorders immediately. Check driving settings and simulation mode before comparing."],38)
                    add_row(5,headers,48)
                    for n,values in enumerate(tables[index],6):
                        row=add_row(n,values,34)
                        if index==1:
                            for ref,formula,cached in (("Q"+str(n),'IF($E'+str(n)+'="ok",CHOOSE(MATCH($B$3,$H$5:$P$5,0),'+','.join(f'IF(ISNUMBER({column(c)}{n}),{column(c)}{n},"")' for c in range(8,17))+'),"")',values[16]),
                                ("R"+str(n),f'IF(ISNUMBER(Q{n}),1,0)',values[17]),
                                ("A"+str(n),f'IF(ISNUMBER(Q{n}),1+COUNTIFS($Q$6:$Q${last},IF($D$3="Highest first",">","<")&Q{n},$R$6:$R${last},1),"")',values[0])):
                                cell=next((c for c in row if c.get("r")==ref),None)
                                if cell is None:cell=ET.SubElement(row,f"{{{NS}}}c",r=ref,s=styles.get("B6","0"))
                                for child in list(cell):cell.remove(child)
                                if cached is None:cell.set("t","str")
                                else:cell.attrib.pop("t",None)
                                ET.SubElement(cell,f"{{{NS}}}f").text=formula
                                ET.SubElement(cell,f"{{{NS}}}v").text="" if cached is None else str(cached)
                            row[:]=sorted(row,key=lambda c:(len(c.get("r").rstrip("0123456789")),c.get("r")))
                    dimension=sheet.find("s:dimension",ns)
                    if dimension is None:
                        dimension=ET.Element(f"{{{NS}}}dimension")
                        sheet.insert(1 if len(sheet) and sheet[0].tag==f"{{{NS}}}sheetPr" else 0,dimension)
                    dimension.set("ref",f"A1:{column(len(headers))}{last}")
                    pane=sheet.find("s:sheetViews/s:sheetView/s:pane",ns)
                    if pane is not None:
                        pane.attrib.update(xSplit=str(1 if index==0 else 2),ySplit="5",topLeftCell="B6" if index==0 else "C6",activePane="bottomRight",state="frozen")
                    ET.SubElement(sheet,f"{{{NS}}}autoFilter",ref=f"A5:{column(len(headers))}{last}")
                    merges=ET.SubElement(sheet,f"{{{NS}}}mergeCells",count="4")
                    for ref in (["A1:H1","A2:C2","A3:H3","A4:H4"] if index==0 else ["A1:H1","A2:C2","B3:C3","A4:H4"]):
                        ET.SubElement(merges,f"{{{NS}}}mergeCell",ref=ref)
                    if index==1:
                        dvs=ET.SubElement(sheet,f"{{{NS}}}dataValidations",count="2")
                        for ref,formula in (("B3","$H$5:$P$5"),("D3",'"Highest first,Lowest first"')):
                            dv=ET.SubElement(dvs,f"{{{NS}}}dataValidation",type="list",sqref=ref,allowBlank="0",showErrorMessage="1")
                            ET.SubElement(dv,f"{{{NS}}}formula1").text=formula
                    hyperlinks=ET.SubElement(sheet,f"{{{NS}}}hyperlinks")
                    relns="http://schemas.openxmlformats.org/package/2006/relationships"
                    rels=ET.Element("Relationships",xmlns=relns)
                    for i,(ref,target) in enumerate(links,1):
                        rid=f"rIdCatalog{i}"
                        ET.SubElement(hyperlinks,f"{{{NS}}}hyperlink",{"ref":ref,f"{{{RNS}}}id":rid})
                        ET.SubElement(rels,"Relationship",Id=rid,Type=RNS+"/hyperlink",Target=target,TargetMode="External")
                    link_relationships[f"xl/worksheets/_rels/sheet{index+1}.xml.rels"]=ET.tostring(rels,encoding="utf-8",xml_declaration=True)
                    # CT_Worksheet requires filters/merges/validations/links before
                    # print settings. Appending them after the template's margins
                    # parses as XML but makes Excel discard both worksheet parts.
                    order="sheetPr dimension sheetViews sheetFormatPr cols sheetData sheetCalcPr sheetProtection protectedRanges scenarios autoFilter sortState dataConsolidate customSheetViews mergeCells phoneticPr conditionalFormatting dataValidations hyperlinks printOptions pageMargins pageSetup headerFooter rowBreaks colBreaks customProperties cellWatches ignoredErrors smartTags drawing legacyDrawing legacyDrawingHF drawingHF picture oleObjects controls webPublishItems tableParts extLst".split()
                    sheet[:]=sorted(sheet,key=lambda el:order.index(el.tag.rsplit('}',1)[-1]))
                    content=ET.tostring(sheet,encoding="utf-8",xml_declaration=True)
                if info.filename=="xl/calcChain.xml":continue
                if info.filename not in ("xl/worksheets/_rels/sheet1.xml.rels","xl/worksheets/_rels/sheet2.xml.rels"):dest.writestr(info,content)
            for path,content in link_relationships.items():dest.writestr(path,content)
        try:
            os.replace(tmp,root(model)/"master_runs.xlsx")
            db.execute("INSERT OR REPLACE INTO meta VALUES('excel_pending','')")
            db.execute("INSERT OR REPLACE INTO meta VALUES('excel_updated',?)",(stamp(),))
            db.execute("INSERT OR REPLACE INTO meta VALUES('excel_export_time',?)",(str(time.time()),))
        except PermissionError:
            tmp.unlink(missing_ok=True)
            db.execute("INSERT OR REPLACE INTO meta VALUES('excel_pending','Close master_runs.xlsx in Excel, then refresh the workbook in the app. Run records are safely saved.')")
    return root(model)/"master_runs.xlsx"
