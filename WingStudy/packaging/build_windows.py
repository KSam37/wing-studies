"""Build the offline x64 Windows ZIP from the working, verified Ptera environment.

Run with the same interpreter used by Wing Studies. Only the official CPython
embeddable runtime is downloaded. Existing simulations and personal files are never
included. The original environment is read, never modified.
"""
from pathlib import Path
import hashlib
import importlib.metadata as metadata
import io
import json
import os
import platform
import struct
import subprocess
import sys
import urllib.request
import zipfile

HERE=Path(__file__).resolve().parent
COMPANION=HERE.parent
PTERA=COMPANION.parent/"PteraSoftware"
DEST=COMPANION.parent/"outputs"/"share"
NAME="WingStudies-Windows-x64-3.2.0"
RUNTIME_URL="https://www.python.org/ftp/python/3.14.2/python-3.14.2-embed-amd64.zip"


def main():
    assert sys.version_info[:3]==(3,14,2) and os.name=="nt" and struct.calcsize("P")==8
    DEST.mkdir(parents=True,exist_ok=True)
    cache=DEST.parent/"cache"/"packaging"
    cache.mkdir(parents=True,exist_ok=True)
    runtime=cache/"python-3.14.2-embed-amd64.zip"
    if not runtime.exists():
        print("Downloading the official portable CPython 3.14.2 runtime...",flush=True)
        with urllib.request.urlopen(RUNTIME_URL,timeout=90) as response:
            runtime.write_bytes(response.read())
    archive=DEST/(NAME+".zip")
    temp=archive.with_suffix(".zip.tmp")
    packages={d.metadata["Name"]:d.version for d in metadata.distributions()
              if d.metadata["Name"].lower() not in ("pip","setuptools","wheel")}
    assert packages["PteraSoftware"]=="5.1.0"
    commit=subprocess.check_output(["git","-C",str(PTERA),"rev-parse","HEAD"],text=True).strip()
    dirty=subprocess.check_output(["git","-C",str(PTERA),"status","--porcelain"],text=True).strip()
    digest={}
    total=0
    print("Packaging the runtime, solver, GUI and pinned scientific libraries...",flush=True)
    with zipfile.ZipFile(temp,"w",compression=zipfile.ZIP_DEFLATED,compresslevel=6,allowZip64=True) as out:
        def add_bytes(rel,data):
            nonlocal total
            if isinstance(data,str): data=data.encode("utf-8")
            out.writestr(NAME+"/"+rel,data)
            digest[rel]=hashlib.sha256(data).hexdigest()
            total+=len(data)
        def add_file(rel,path): add_bytes(rel,path.read_bytes())
        def files(root):
            for p in sorted(root.rglob("*")):
                if not p.is_file(): continue
                rel=p.relative_to(root)
                if "__pycache__" in rel.parts or p.suffix.lower() in (".pyc",".pyo",".nbc",".nbi",".pth",".egg-link"): continue
                if any(x.startswith("__editable__") for x in rel.parts) or p.name=="direct_url.json": continue
                yield rel.as_posix(),p
        with zipfile.ZipFile(runtime) as z:
            assert z.testzip() is None
            for n in z.namelist():
                if n.endswith("/") or n.endswith("._pth"): continue
                add_bytes("runtime/"+n,z.read(n))
        add_bytes("runtime/python314._pth","python314.zip\n.\nLib/site-packages\n../PteraSoftware\n../WingStudy\n../support\nimport site\n")
        site=Path(sys.prefix)/"Lib"/"site-packages"
        for rel,p in files(site):
            first=Path(rel).parts[0].lower()
            if first in ("pip","setuptools","wheel","_distutils_hack") or first.startswith(("pip-","setuptools-","wheel-","pterasoftware","__editable__")): continue
            add_file("runtime/Lib/site-packages/"+rel,p)
        for rel,p in files(PTERA/"pterasoftware"):
            add_file("PteraSoftware/pterasoftware/"+rel,p)
        for n in ("LICENSE.md","README.md","CITATION.cff"):
            add_file("PteraSoftware/"+n,PTERA/n)
        # Metadata is local to the bundled source; no editable-install .pth or
        # original environment paths are copied.
        add_file("PteraSoftware/PteraSoftware-5.1.0.dist-info/METADATA",PTERA/"PteraSoftware.egg-info"/"PKG-INFO")
        add_bytes("PteraSoftware/BUNDLE_SOURCE.json",json.dumps({"commit":commit,"original_worktree":dirty,
            "note":"Only solver package, its data/licenses, and metadata bundled; examples are omitted."},indent=2))
        for n in ("app.py","model.py","catalog.py","catalog-ui.js","master_template.xlsx","ui.html","ui.js","test_study.py","test_catalog.py","test_catalog_filters.js","README.md"):
            add_file("WingStudy/"+n,COMPANION/n)
        add_file("support/check_portable.py",HERE/"check_portable.py")
        common='''@echo off
setlocal DisableDelayedExpansion
if not exist "%~dp0runtime\\python.exe" (
  echo Please right-click the ZIP and select Extract All before running this program.
  pause
  exit /b 1
)
set "PYTHONHOME="
set "PYTHONPATH="
set "PYTHONNOUSERSITE=1"
set "MPLBACKEND=Agg"
set "MPLCONFIGDIR=%~dp0outputs\\cache\\matplotlib"
set "NUMBA_CACHE_DIR=%LOCALAPPDATA%\\WingStudies\\numba"
if not defined LOCALAPPDATA set "NUMBA_CACHE_DIR=%TEMP%\\WingStudiesNumba"
set "OMP_NUM_THREADS=1"
set "OPENBLAS_NUM_THREADS=1"
set "NUMBA_NUM_THREADS=1"
pushd "%~dp0"
'''
        for n,command in (("Run Wing Studies.cmd",'"%~dp0runtime\\python.exe" -I -u "%~dp0WingStudy\\app.py" %*'),
                          ("Run Master Catalog.cmd",'"%~dp0runtime\\python.exe" -I -u "%~dp0WingStudy\\app.py" --catalog %*'),
                          ("Check Setup.cmd",'"%~dp0runtime\\python.exe" -I -u "%~dp0support\\check_portable.py" %*')):
            text=common+command+'\nset "WING_EXIT=%ERRORLEVEL%"\npopd\n'
            if n.startswith("Check"): text+='if "%~1"=="" pause\n'
            text+='if not "%WING_EXIT%"=="0" (\n  echo Wing Studies stopped with an error. Keep the messages above for troubleshooting.\n  pause\n)\nexit /b %WING_EXIT%\n'
            add_bytes(n,text.replace("\n","\r\n"))
        add_bytes("START HERE.txt",'''WING STUDIES - WINDOWS x64 PORTABLE EDITION

1. Right-click the ZIP, choose Extract All, and extract the WHOLE folder.
   Choose a short writable local folder, for example your user folder\\WingStudies.
   Avoid deeply nested folders: some native libraries still have Windows path limits.
2. Double-click Run Wing Studies.cmd. Your default browser opens the local GUI.
3. Keep the terminal window open. The terminal shows the actual local address.
   If port 8765 is busy, the program chooses another port.

No installation, administrator rights, Python setup, pip, Git or internet needed.
Your existing Ptera installation and Windows PATH are not changed.
Requires 64-bit Intel/AMD Windows 10 or 11 and working graphics drivers for animation.
Windows ARM, 32-bit Windows, and other operating systems are not tested/supported.

OPTIONAL CHECK
Double-click Check Setup.cmd to verify file integrity, dependency versions and
the engineering checks. For a real simulation plus animation, open a terminal in
this folder and run: "Check Setup.cmd" --smoke
The first simulation may spend extra time compiling numerical functions.
Ptera briefly opens an animation preview, then saves automatically without a keypress.

OUTPUTS
Studies: outputs\\studies\\<timestamp>_<name>
Each case: four default Ptera time-history PNGs, animation.webp, and wing_left.svg / wing_right.svg.
Each SVG is a full-size flat tracing outline in mm, with a 100 mm scale-check bar.
Print at Actual size / 100%, with fit-to-page disabled. Measure the bar before tracing.
Large patterns require tiled printing or a plotter. No seam or rod-pocket allowances.
Comparisons: custom PNG/CSV pairs, shared time histories and top performers CSV.
No personal studies or previous outputs are included in this download.
Disposable numerical cache: %LOCALAPPDATA%\\WingStudies\\numba.
This short per-user cache avoids Windows' path limit and may be deleted when idle.

MOVING / SHARING
Move or rename the entire extracted folder, keeping its contents together.
This edition uses relative paths and its own isolated Python runtime.
To send results back, share the named study folder inside outputs\\studies.
Keep a backup of outputs before replacing the program with a new release.
Do not run inside the ZIP or copy only the launcher.

ABOUT
Python 3.14.2 x64; PteraSoftware 5.1.0; companion 3.2.0.
Pinned dependencies and per-file SHA-256 hashes: support\\bundle.json.
Third-party license texts remain with their packages and Python runtime.
Python runtime: https://www.python.org/ftp/python/3.14.2/
Ptera: https://github.com/camUrban/PteraSoftware
This is a bundled research tool, not a separately validated hydrodynamic model.
Each simulation contains one isolated wing, rooted at the moment reference.
Estimated pair thrust = twice single-wing thrust, without interaction.
Older paired-wing plots need rerunning for non-cancelling roll moments.
Optimize the single-wing thrust/roll-moment ratio; no motor model is used. Stock Ptera requires positive forward speed.
''')
        notices=["THIRD-PARTY SOFTWARE\n\nPython license: runtime/LICENSE.txt\nPtera license: PteraSoftware/LICENSE.md\nOther licenses: runtime/Lib/site-packages/<package>.dist-info/licenses or LICENSE files.\n"]
        for d in sorted(metadata.distributions(),key=lambda d:d.metadata["Name"].lower()):
            if d.metadata["Name"] not in packages: continue
            notices.append(f"{d.metadata['Name']} {d.version}\n{d.metadata.get('License-Expression',d.metadata.get('License','See bundled package license files'))}\n")
        add_bytes("THIRD_PARTY_NOTICES.txt","\n".join(notices))
        add_bytes("support/versions.txt","Python==3.14.2\n"+"\n".join(f"{n}=={v}" for n,v in sorted(packages.items()))+"\n")
        info={"edition":NAME,"runtime_url":RUNTIME_URL,
              "runtime_zip_sha256":hashlib.file_digest(runtime.open("rb"),"sha256").hexdigest(),
              "ptera_commit":commit,"packages":packages,"sha256":digest.copy()}
        out.writestr(NAME+"/support/bundle.json",json.dumps(info,indent=2))
    temp.replace(archive)
    checksum=hashlib.file_digest(archive.open("rb"),"sha256").hexdigest()
    archive.with_suffix(".zip.sha256").write_text(checksum+"  "+archive.name+"\n",encoding="ascii")
    print(f"Created {archive}\n{len(digest)} files; {total/1024**2:.1f} MiB extracted; {archive.stat().st_size/1024**2:.1f} MiB ZIP",flush=True)


if __name__=="__main__": main()
