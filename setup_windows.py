"""One-time Windows setup and path-independent launch. Uses only stdlib initially."""
from pathlib import Path
import hashlib
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import urllib.request
import venv
import zipfile

ROOT=Path(__file__).resolve().parent
LOCK=ROOT/"requirements-windows.lock"
SOURCE=ROOT/"ptera-source.json"

def configuration():
    local=Path(os.environ["LOCALAPPDATA"])/"WingStudies"
    key=hashlib.sha256(str(ROOT.resolve()).casefold().encode()).hexdigest()[:16]
    return local/"checkouts"/(key+".json"),local/"environments"/key

def run(args,**kwargs):
    subprocess.run([str(a) for a in args],check=True,cwd=ROOT,**kwargs)

def fingerprint():
    return hashlib.sha256(LOCK.read_bytes()+SOURCE.read_bytes()).hexdigest()

def verify_source():
    source=json.loads(SOURCE.read_text(encoding="utf8"))
    for name,expected in source["native_sha256"].items():
        path=ROOT/"PteraSoftware"/name
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=expected:
            raise RuntimeError(f"Pinned Ptera source mismatch: {name}. Keep native solver changes in a separate checkout.")

def ensure_source():
    target=ROOT/"PteraSoftware"
    if not (target/"setup.cfg").is_file():
        if target.exists() and any(target.iterdir()):
            raise RuntimeError("PteraSoftware is nonempty but incomplete. Restore the pinned submodule before setup.")
        source=json.loads(SOURCE.read_text(encoding="utf8"))
        url=f"https://codeload.github.com/camUrban/PteraSoftware/zip/{source['commit']}"
        print("Downloading the pinned official Ptera source (first setup only)…",flush=True)
        with urllib.request.urlopen(url,timeout=120) as response:data=response.read()
        if hashlib.sha256(data).hexdigest()!=source["archive_sha256"]:
            raise RuntimeError("Ptera download checksum mismatch; nothing was installed.")
        with tempfile.TemporaryDirectory(prefix="wing-studies-ptera-") as folder:
            folder=Path(folder);archive=folder/"source.zip";archive.write_bytes(data)
            with zipfile.ZipFile(archive) as z:
                expected=f"PteraSoftware-{source['commit']}"
                for info in z.infolist():
                    resolved=(folder/info.filename).resolve()
                    if not resolved.is_relative_to(folder.resolve()) or Path(info.filename).parts[0]!=expected:
                        raise RuntimeError("Unexpected Ptera archive path.")
                z.extractall(folder)
            shutil.copytree(folder/expected,target,dirs_exist_ok=True)
    verify_source()

def verify_environment(python):
    # Fail before changing the launcher pointer if any pinned package is absent.
    code="""import importlib.metadata as m,json,pathlib,struct,sys
assert sys.version_info[:2]==(3,14) and struct.calcsize('P')==8
for line in pathlib.Path(sys.argv[1]).read_text().splitlines():
 if line and not line.startswith('#'):
  name,version=line.split('==');assert m.version(name)==version,(name,m.version(name),version)
assert m.version('PteraSoftware')=='5.1.0'
import numpy,scipy,numba,matplotlib,pyvista,vtk,mujoco,webp
print('Pinned packages and scientific imports verified.',flush=True)
"""
    run([python,"-I","-c",code,LOCK])
    run([python,"-I","-m","pip","check"])

def register(python):
    verify_environment(python)
    config,_=configuration();config.parent.mkdir(parents=True,exist_ok=True)
    temp=config.with_suffix(".tmp")
    temp.write_text(json.dumps({"python":str(Path(python).resolve()),"fingerprint":fingerprint()},indent=2),encoding="utf8")
    os.replace(temp,config)

def configured_python():
    config,_=configuration()
    if not config.is_file():raise RuntimeError("Run Setup Windows.cmd once before launching this checkout.")
    value=json.loads(config.read_text(encoding="utf8"))
    if value["fingerprint"]!=fingerprint():raise RuntimeError("Dependencies changed. Run Setup Windows.cmd again.")
    path=Path(value["python"])
    if not path.is_file():raise RuntimeError("The environment is missing. Run Setup Windows.cmd again.")
    return path

def main(args=None):
    args=list(sys.argv[1:] if args is None else args)
    if os.name!="nt" or sys.version_info[:2]!=(3,14) or struct.calcsize("P")!=8:
        raise RuntimeError("Use 64-bit Python 3.14 on Windows. Tested with Python 3.14.2.")
    if args and args[0]=="--launch":
        python=configured_python()
        if "--check-installation" in args[1:]:
            verify_source();verify_environment(python)
            run([python,"-m","unittest","discover","-s",ROOT/"WingStudy","-p","test_*.py"])
            print("Installation and application checks passed.",flush=True)
            return
        run([python,"-u",ROOT/"WingStudy/app.py",*args[1:]])
        return
    ensure_source()
    if args:
        if len(args)!=2 or args[0]!="--use-python":raise ValueError("Expected --use-python <existing verified interpreter>, or no arguments.")
        register(args[1]);return
    _,env=configuration()
    if not (env/"Scripts/python.exe").is_file():
        print("Creating a private environment outside your project folder…",flush=True)
        venv.EnvBuilder(with_pip=True).create(env)
    python=env/"Scripts/python.exe"
    run([python,"-m","pip","install","--disable-pip-version-check","pip==25.3"])
    run([python,"-m","pip","install","--disable-pip-version-check","-r",LOCK])
    # PyPI's older 5.1.0 metadata excludes 3.14. The pinned upstream source has
    # explicit 3.14 support; build that exact checkout without replacing its deps.
    run([python,"-m","pip","install","--disable-pip-version-check","--no-deps",ROOT/"PteraSoftware"])
    register(python)
    print("Setup complete. Your studies will stay in this checkout's outputs folder.",flush=True)

if __name__=="__main__":
    try:main()
    except (OSError,ValueError,RuntimeError,subprocess.SubprocessError,zipfile.BadZipFile) as exc:
        print(f"\nWing Studies: {exc}",file=sys.stderr)
        sys.exit(1)
