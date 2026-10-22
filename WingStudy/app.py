"""Local-only companion GUI. Run with the existing Ptera Python environment."""
from __future__ import annotations

import argparse
from datetime import datetime
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import time
from urllib.parse import unquote, urlparse
import webbrowser

import model
import catalog

LOCK = threading.Lock()
PROCESS = None
ACTIVE = None
SERVER = None


def study_path(name):
    if not re.fullmatch(r"[A-Za-z0-9_-]+", name):
        raise ValueError("Invalid study identifier.")
    path = model.OUTPUTS/name
    if not (path/"manifest.json").is_file():
        raise ValueError("Study not found.")
    return path


def studies():
    result = []
    with catalog.connect(model) as db:
        numbers={(r["study"],r["local_case"]):r["case_no"] for r in db.execute("SELECT study,local_case,case_no FROM occurrences")}
    if model.OUTPUTS.exists():
        for p in sorted(model.OUTPUTS.iterdir(), reverse=True):
            if not (p/"manifest.json").is_file():
                continue
            try:
                manifest = model.read_json(p/"manifest.json")
                status = model.read_json(p/"status.json")
                # A worker may outlive a browser tab. Only report interruption when
                # its recorded PID is no longer alive (not merely on GUI restart).
                if status.get("state") == "running" and not pid_alive(manifest.get("worker_pid")):
                    status.update(state="interrupted", message="Worker stopped; completed cases remain available.")
                rows = model.read_json(p/"results.json") if (p/"results.json").exists() else []
                rows = [{**r,"global_case_no":r.get("global_case_no",numbers.get((p.name,r["id"]))),"simulation_mode":r.get("simulation_mode","legacy_paired"),"wake_model":r.get("wake_model","free"),"wake_cycles":r.get("wake_cycles",0),"waveform_signature":r.get("waveform_signature","sine"),"has_profile_svg":(p/r["id"]/"wing_profile.svg").is_file(),"has_paired_profiles":all((p/r["id"]/f"wing_{side}.svg").is_file() for side in ("left","right"))} for r in rows]
                result.append({"id": p.name, "name": manifest["name"], "created": manifest["created"],
                               "status": {**status,**model.runtime_status(manifest,status,rows)}, "rows": rows, "config": manifest["config"],
                               "simulation_mode":manifest.get("settings",{}).get("simulation_mode","legacy_paired"),"tail":manifest.get("tail"),"tail_profiles":manifest.get("tail_profiles"),
                               "lean_outputs":manifest.get("companion_version") in ("1.2.0","1.3.0","1.4.0","1.4.1","1.5.0","1.6.0","1.7.0","2.1.1") or
                                   (p/"comparisons"/"time_histories.csv").exists()})
            except (OSError, ValueError):
                continue
    return result


def pid_alive(pid):
    if not pid:
        return False
    if os.name == "nt":
        import ctypes
        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, int(pid))
        if not handle:
            return False
        code = ctypes.c_ulong()
        ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        ctypes.windll.kernel32.CloseHandle(handle)
        return code.value == 259
    try:
        os.kill(pid, 0); return True
    except OSError:
        return False


def start(config):
    global PROCESS, ACTIVE
    specification = model.plan(config)
    with LOCK:
        if PROCESS is not None and PROCESS.poll() is None:
            raise ValueError("A study is already running. Stop it or let it finish first.")
        for previous in studies():
            if previous["status"]["state"] == "running":
                raise ValueError("A study is already running in another session. Its progress is shown in Results.")
        model.OUTPUTS.mkdir(parents=True, exist_ok=True)
        slug = re.sub(r"[^a-zA-Z0-9]+", "-", specification["name"]).strip("-").lower()[:45] or "study"
        identifier = datetime.now().strftime("%Y%m%d-%H%M%S-%f") + "_" + slug
        directory = model.OUTPUTS/identifier; directory.mkdir()
        import importlib.metadata
        specification.update(created=datetime.now().astimezone().isoformat(),
            python=sys.version, ptera_version=importlib.metadata.version("PteraSoftware"),
            source_path=str(model.PTERA), companion_version="3.2.4",
            water_source=model.WATER_SOURCE)
        try:
            bundle_source = model.PTERA/"BUNDLE_SOURCE.json"
            if bundle_source.is_file():
                source = model.read_json(bundle_source)
                specification["ptera_commit"] = source["commit"]
                specification["ptera_worktree"] = source["original_worktree"]
            else:
                specification["ptera_commit"] = subprocess.check_output(
                    ["git", "-C", str(model.PTERA), "rev-parse", "HEAD"], text=True,
                    creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0)).strip()
                specification["ptera_worktree"] = subprocess.check_output(
                    ["git", "-C", str(model.PTERA), "status", "--porcelain"], text=True,
                    creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0)).strip()
        except (OSError, subprocess.SubprocessError):
            specification["ptera_commit"] = "unavailable"
        catalog.sync(model)
        catalog.prepare(model,specification,identifier)
        specification.update(catalog.preview(model,specification))
        specification["browser_url"]=f"http://127.0.0.1:{SERVER.server_port}" if SERVER else "http://127.0.0.1:8765"
        specification["tail_profiles"]=model.export_tail_profiles(specification["settings"],directory)
        model.write_json(directory/"manifest.json", specification)
        model.write_json(directory/"status.json", {"state":"running", "completed":0,
            "total":len(specification["cases"]), "message":"Starting worker"})
        env = os.environ.copy()
        env.update(MPLBACKEND="Agg", OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1", NUMBA_NUM_THREADS="1")
        try:
            with (directory/"run.log").open("w", encoding="utf-8") as log:
                PROCESS = subprocess.Popen([sys.executable, "-u", str(Path(__file__).resolve()), "--worker", str(directory)],
                    stdout=log, stderr=subprocess.STDOUT, env=env, cwd=directory,
                    creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
            specification["worker_pid"] = PROCESS.pid
            model.write_json(directory/"manifest.json", specification)
            ACTIVE = identifier
        except OSError as exc:
            model.write_json(directory/"status.json", {"state":"failed", "completed":0,
                "total":len(specification["cases"]), "message":str(exc)})
            raise
        return {"id":identifier}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def send(self, data, status=200, kind="application/json"):
        body = json.dumps(data, allow_nan=False).encode() if kind=="application/json" else data
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers(); self.wfile.write(body)

    def do_GET(self):
        if not self.valid_host():
            return self.send({"error":"Local requests only."}, 403)
        path = unquote(urlparse(self.path).path)
        try:
            if path in ("/", "/index.html"):
                return self.send((model.HERE/"ui.html").read_bytes(), kind="text/html; charset=utf-8")
            if path == "/catalog-ui.js":
                return self.send((model.HERE/"catalog-ui.js").read_bytes(),kind="application/javascript; charset=utf-8")
            if path == "/ui.js":
                return self.send((model.HERE/"ui.js").read_bytes(), kind="application/javascript; charset=utf-8")
            if path == "/api/defaults":
                return self.send({"config":model.DEFAULT, "fields":model.FIELDS, "families":model.FAMILIES,
                                  "geometry_keys":model.GEOMETRY_KEYS,
                                  "output_root":str(model.OUTPUTS), "model_note":model.MODEL_NOTE})
            if path == "/api/studies":
                return self.send(studies())
            if path == "/api/catalog":
                return self.send(catalog.listing(model))
            if path == "/master_runs.xlsx":
                file=catalog.root(model)/"master_runs.xlsx"
                if not file.is_file():catalog.export(model,browser_url=f"http://127.0.0.1:{SERVER.server_port}")
                return self.send(file.read_bytes(),kind="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            if path.startswith("/api/case/"):
                _, _, _, name, case_id = path.split("/")
                return self.send(model.case_data(study_path(name), case_id))
            if path.startswith("/files/"):
                root = model.OUTPUTS.resolve()
                file = (root/path[len("/files/"):]).resolve()
                if not file.is_relative_to(root) or not file.is_file():
                    return self.send({"error":"File not found."},404)
                return self.send(file.read_bytes(), kind=mimetypes.guess_type(file.name)[0] or "application/octet-stream")
            return self.send({"error":"Not found."},404)
        except (ValueError, OSError) as exc:
            return self.send({"error":str(exc)},400)

    def valid_host(self):
        return self.headers.get("Host") in (f"127.0.0.1:{SERVER.server_port}", f"localhost:{SERVER.server_port}")

    def do_POST(self):
        global PROCESS
        if not self.valid_host() or self.headers.get("Origin", f"http://{self.headers.get('Host')}") != f"http://{self.headers.get('Host')}":
            return self.send({"error":"Local same-origin requests only."},403)
        try:
            length = int(self.headers.get("Content-Length",0))
            if length <= 0 or length > 200_000:
                raise ValueError("Invalid request size.")
            data = json.loads(self.rfile.read(length))
            path = urlparse(self.path).path
            if path == "/api/preview":
                spec=model.plan(data)
                spec.update(catalog.preview(model,spec))
                return self.send(spec)
            if path == "/api/catalog":
                with LOCK:
                    catalog.sync(model)
                    metric=data.get("metric",catalog.OBJECTIVE)
                    descending=bool(data.get("descending",True))
                    if data.get("export",False):catalog.export(model,metric,descending,f"http://127.0.0.1:{SERVER.server_port}")
                    return self.send(catalog.listing(model,metric,descending))
            if path == "/api/catalog-landscape":
                with LOCK:
                    return self.send(catalog.landscape(model,data.get("case_numbers",[])))
            if path == "/api/start":
                return self.send(start(data))
            if path == "/api/stop":
                directory = study_path(data["id"])
                if ACTIVE != data["id"] or PROCESS is None or PROCESS.poll() is not None:
                    raise ValueError("This session has no active worker for that study.")
                with LOCK:
                    PROCESS.terminate(); PROCESS.wait(timeout=15)
                    status = model.read_json(directory/"status.json")
                    status.update(state="cancelled", message="Stopped by user; completed cases retained.")
                    model.write_json(directory/"status.json", status)
                return self.send({"ok":True})
            if path == "/api/heatmap":
                with LOCK:
                    result = model.design_plot(study_path(data["study"]), data["axes"], data["metric"],
                        data.get("filters",{}), data.get("mode","max"), data.get("repeat_only",False))
                return self.send(result)
            if path == "/api/shape-comparison":
                with LOCK:
                    directory=study_path(data["study"])
                    if data.get("export",False) and model.read_json(directory/"status.json").get("state")=="running":
                        raise ValueError("Wait for the study to finish before exporting the comparison.")
                    result=model.shape_comparison(directory,export=data.get("export",False),repeat_only=data.get("repeat_only",True))
                return self.send(result)
            if path == "/api/shape-landscape":
                with LOCK:
                    directory=study_path(data["study"])
                    if model.read_json(directory/"status.json").get("state")=="running":
                        raise ValueError("Wait for the study to finish before generating the 3D comparison.")
                    result=model.shape_landscape(directory,repeat_only=data.get("repeat_only",True),export=True)
                return self.send(result)
            if path == "/api/overlay":
                with LOCK:
                    file = model.overlay(data["cases"])
                return self.send({"file":file})
            return self.send({"error":"Not found."},404)
        except (ValueError, TypeError, KeyError, OSError, subprocess.SubprocessError) as exc:
            return self.send({"error":str(exc)},400)


def main():
    global SERVER
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--catalog",action="store_true",help="Open the compiled master run catalog.")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    if args.worker:
        model.worker(Path(args.worker)); return
    # Windows permits duplicate listeners with SO_REUSEADDR, leaving browser
    # requests split between old/new processes instead of taking the free port.
    if os.name == "nt":
        ThreadingHTTPServer.allow_reuse_address = False
    try:
        SERVER = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    except OSError:
        SERVER = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    url = f"http://127.0.0.1:{SERVER.server_port}"
    catalog.sync(model)
    catalog.export(model,browser_url=url)
    print(f"Wing Studies: {url}\nResults: {model.OUTPUTS}\nKeep this terminal open. Ctrl+C stops the GUI server.", flush=True)
    if not args.no_browser:
        webbrowser.open(url+("/#catalog" if args.catalog else ""))
    try:
        SERVER.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        SERVER.server_close()


if __name__ == "__main__":
    main()
