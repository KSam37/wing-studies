"""Local browser dashboard for elastic_campaign: plan, controls, live progress, explorer.

Only the standard library; serves WingStudy/elastic_dashboard.html. All data endpoints
read the campaign SQLite store through their own read-only connections.
"""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

HERE = Path(__file__).resolve().parent


def _reader(camp):
    db = sqlite3.connect(f"file:{camp.store.path}?mode=ro", uri=True, timeout=30, check_same_thread=False)
    return db


def points(camp, freq=None):
    db = _reader(camp)
    q = ("select d.key,d.level,d.freq,d.status,d.thrust,d.torque,d.thrust_lo,d.thrust_hi,d.torque_lo,d.torque_hi,"
         "d.tip_twist,d.chords,d.half_span,(select group_concat(distinct u.source||':'||u.search_id) from uses u where u.key=d.key) "
         "from designs d where d.numerics='base' and d.thrust is not null")
    args = ()
    if freq is not None:
        q += " and abs(d.freq-?)<1e-9"; args = (freq,)
    out = []
    for r in db.execute(q, args):
        srcs = (r[13] or "").split(",")
        out.append({"key": r[0], "level": r[1], "freq": r[2], "status": r[3], "thrust": r[4], "torque": r[5],
                    "thrust_lo": r[6], "thrust_hi": r[7], "torque_lo": r[8], "torque_hi": r[9], "tip_twist": r[10],
                    "chords": json.loads(r[11]), "half_span": r[12],
                    "search": any(s.startswith("search:") for s in srcs), "map": any(s.startswith("map:") for s in srcs),
                    "objectives": sorted({s.split("/")[-1] for s in srcs if s.startswith("search:")})})
    db.close()
    return out


def design(camp, key):
    db = _reader(camp)
    cols = [c[1] for c in db.execute("pragma table_info(designs)")]
    row = db.execute("select * from designs where key=?", (key,)).fetchone()
    if row is None:
        return {"error": "not found"}
    d = dict(zip(cols, row)); d["chords"] = json.loads(d["chords"])
    cyc = db.execute("select data from cycles where key=?", (key,)).fetchone()
    d["final_cycle"] = json.loads(cyc[0]) if cyc else None
    d["uses"] = [dict(zip(("source", "search_id", "lineage", "role", "phase"), u))
                 for u in db.execute("select source,search_id,lineage,role,phase from uses where key=?", (key,))]
    d["rechecks"] = [dict(zip(("key", "numerics", "status", "thrust", "torque"), r)) for r in db.execute(
        "select d.key,d.numerics,d.status,d.thrust,d.torque from rechecks r join designs d on d.key=r.key where r.base_key=?", (key,))]
    anim = camp.dir / "animations" / key
    d["animation"] = {"state": camp_replays.get(key, "done" if (anim / "animation_front.webp").exists() else "none"),
                      "files": sorted(p.name for p in anim.glob("*.webp")) if anim.exists() else []}
    d["replay_command"] = f"python WingStudy/elastic_campaign.py replay {camp.dir} {key}"
    db.close()
    return d


def best(camp):
    """Best verified/settled thrust at <= 1 N m per stiffness x frequency, plus search winners and re-checks."""
    db = _reader(camp)
    plan = camp.plan
    grid = []
    for lv in plan["levels"]:
        for f in plan["frequencies_hz"]:
            r = db.execute("select key,thrust,torque,chords,half_span,tip_twist,status from designs where level=? and abs(freq-?)<1e-9 "
                           "and numerics='base' and status in ('verified','ok') and torque<=? order by thrust desc limit 1",
                           (lv["id"], f, plan["torque_target_nm"])).fetchone()
            n = db.execute("select count(*) from designs where level=? and abs(freq-?)<1e-9 and numerics='base'", (lv["id"], f)).fetchone()[0]
            cell = {"level": lv["id"], "label": lv["label"], "freq": f, "evaluated": n}
            if r:
                cell.update(key=r[0], thrust=r[1], torque=r[2], chords=json.loads(r[3]), half_span=r[4], tip_twist=r[5], status=r[6])
                rc = db.execute("select d.numerics,d.status,d.thrust,d.torque from rechecks x join designs d on d.key=x.key where x.base_key=?", (r[0],)).fetchall()
                cell["rechecks"] = [dict(zip(("numerics", "status", "thrust", "torque"), x)) for x in rc]
            grid.append(cell)
    winners = [dict(zip(("search_id", "level", "freq", "objective", "status", "key", "thrust", "torque"), r)) for r in db.execute(
        "select s.search_id,s.level,s.freq,s.objective,s.status,s.best_key,d.thrust,d.torque from searches s "
        "left join designs d on d.key=s.best_key")]
    db.close()
    return {"grid": grid, "winners": winners, "levels": plan["levels"], "freqs": plan["frequencies_hz"],
            "torque_target": plan["torque_target_nm"]}


camp_replays: dict[str, str] = {}


def start_replay(camp, key):
    if camp_replays.get(key) == "running":
        return
    camp_replays[key] = "running"

    def go():
        cmd = [sys.executable, str(HERE / "elastic_campaign.py"), "replay", str(camp.dir), key]
        r = subprocess.run(cmd, capture_output=True, text=True)
        camp_replays[key] = "done" if r.returncode == 0 else "failed: " + (r.stderr or "")[-300:]
    threading.Thread(target=go, daemon=True).start()


def make_handler(camp):
    import elastic_campaign as EC

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def send(self, body, ctype="application/json", code=200):
            data = body if isinstance(body, bytes) else (json.dumps(body, default=str).encode() if ctype == "application/json" else body.encode())
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            u = urlparse(self.path); q = {k: v[0] for k, v in parse_qs(u.query).items()}
            try:
                if u.path in ("/", "/index.html"):
                    return self.send((HERE / "elastic_dashboard.html").read_text(), "text/html; charset=utf-8")
                if u.path == "/api/plan":
                    return self.send({"plan": camp.plan, "estimate": EC.estimate(camp.plan), "dir": str(camp.dir)})
                if u.path == "/api/status":
                    return self.send(camp.status())
                if u.path == "/api/points":
                    return self.send(points(camp, float(q["freq"]) if "freq" in q else None))
                if u.path == "/api/design":
                    return self.send(design(camp, q["key"]))
                if u.path == "/api/best":
                    return self.send(best(camp))
                if u.path.startswith("/files/"):
                    p = (camp.dir / u.path[len("/files/"):]).resolve()
                    if camp.dir.resolve() in p.parents and p.is_file():
                        ctype = {".webp": "image/webp", ".png": "image/png", ".json": "application/json"}.get(p.suffix, "application/octet-stream")
                        return self.send(p.read_bytes(), ctype)
                return self.send({"error": "not found"}, code=404)
            except Exception as exc:  # noqa: BLE001
                return self.send({"error": str(exc)}, code=500)

        def do_POST(self):
            u = urlparse(self.path)
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n) or b"{}")
            if u.path == "/api/export-span-atlas":
                if not camp.plan.get("elastic_options", {}).get("spanwise_bending"):
                    return self.send({"error": "This export is for span-flex campaigns."}, code=400)
                result = subprocess.run([sys.executable, str(HERE / "span_atlas.py"), "--campaign", str(camp.dir)], capture_output=True, text=True)
                return self.send({"message": result.stdout.strip(), "error": result.stderr.strip() if result.returncode else None}, code=500 if result.returncode else 200)
            if u.path == "/api/control":
                a = body.get("action")
                if a == "start" and camp.state in ("ready", "waiting"):
                    camp.control.set()
                elif a == "auto":
                    camp.auto_continue = bool(body.get("value"))
                    camp.note("Auto-continue " + ("on: chunks run back to back" if camp.auto_continue else "off: stops after each chunk"))
                elif a == "stop" and camp.state in ("ready", "waiting"):
                    camp.state = "stopping"; camp.control.set()
                elif a == "pause" and camp.state == "running":
                    camp.state = "paused"; camp.note("Paused (running solves finish first)")
                elif a == "resume" and camp.state == "paused":
                    camp.state = "running"; camp.note("Resumed")
                elif a == "stop" and camp.state in ("running", "paused"):
                    camp.state = "stopping"; camp.note("Stopping after running solves finish")
                return self.send({"state": camp.state})
            if u.path == "/api/replay":
                start_replay(camp, body["key"])
                return self.send({"state": camp_replays.get(body["key"])})
            return self.send({"error": "not found"}, code=404)

    return H


def serve(camp, port=8777, open_browser=True, autostart=False):
    import faulthandler, signal
    # `kill -USR1 <pid>` prints every thread's stack to the terminal (diagnosing hangs).
    if hasattr(signal, "SIGUSR1"):
        faulthandler.register(signal.SIGUSR1, all_threads=True)
    t = threading.Thread(target=camp.run, daemon=True)
    t.start()
    if autostart:
        camp.control.set()
    srv = ThreadingHTTPServer(("127.0.0.1", port), make_handler(camp))
    url = f"http://127.0.0.1:{port}/"
    print(f"Elastic campaign dashboard: {url}\nCampaign folder: {camp.dir}\nClose this window (or Ctrl+C) to stop; results are saved continuously and the campaign resumes where it left off.", flush=True)
    if open_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()

    def terminal_progress():
        import elastic_campaign as EC
        import time as _t
        last = None
        while True:
            _t.sleep(30)
            try:
                st = camp.status()
            except Exception:  # noqa: BLE001
                continue
            if st["state"] in ("running", "paused", "stopping") or st["state"] != last:
                print(_t.strftime("%H:%M ") + EC.progress_line(st), flush=True)
            last = st["state"]
    threading.Thread(target=terminal_progress, daemon=True).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        camp.state = "stopping"
        srv.server_close()
