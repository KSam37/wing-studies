"""Checks for the offline Windows bundle; no installation or network access."""
from pathlib import Path
import argparse
import hashlib
import importlib.metadata as metadata
import json
import os
import struct
import zipfile
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()
    report = json.loads((ROOT/"support"/"bundle.json").read_text(encoding="utf-8"))
    assert struct.calcsize("P")==8 and sys.version_info[:3]==(3,14,2), "Wrong bundled Python runtime."
    assert Path(sys.executable).resolve().is_relative_to(ROOT/"runtime"), "Not using bundled Python."
    assert sys.flags.isolated and sys.flags.ignore_environment, "Runtime isolation is missing."
    assert all(Path(p).resolve().is_relative_to(ROOT) for p in sys.path), "An external Python search path leaked into the bundle."
    print("Checking bundled files...", flush=True)
    def verify_file(item):
        rel,expected=item
        path = ROOT/rel
        assert path.is_file(), f"Missing {rel}. Use Extract All on the complete ZIP."
        with path.open("rb") as stream:
            assert hashlib.file_digest(stream,"sha256").hexdigest()==expected, f"Changed/corrupt file: {rel}"
    with ThreadPoolExecutor(max_workers=8) as pool:
        for _ in pool.map(verify_file,report["sha256"].items()): pass
    for name, version in report["packages"].items():
        assert metadata.version(name)==version, f"Unexpected dependency version: {name}"
    import pterasoftware
    import model
    assert Path(pterasoftware.__file__).resolve().is_relative_to(ROOT/"PteraSoftware")
    assert model.OUTPUTS.resolve().is_relative_to(ROOT)
    # Import native extensions before declaring the installation healthy.
    import numpy, scipy, numba, pyvista, vtk, mujoco, webp
    for module in (numpy,scipy,numba,pyvista,vtk,mujoco,webp):
        assert Path(module.__file__).resolve().is_relative_to(ROOT), f"External dependency: {module.__name__}"
    print(f"All {len(report['sha256'])} files and {len(report['packages'])} package versions verified.", flush=True)
    result = subprocess.run([sys.executable, str(ROOT/"WingStudy"/"test_study.py")], cwd=ROOT)
    if result.returncode:
        raise RuntimeError("Engineering checks failed; see the messages above.")
    result = subprocess.run([sys.executable, str(ROOT/"WingStudy"/"test_catalog.py")], cwd=ROOT)
    if result.returncode:raise RuntimeError("Master catalog checks failed.")
    if args.smoke:
        import copy
        import app
        config=copy.deepcopy(model.DEFAULT)
        config["name"]="Portable package verification"
        config["shape_sweep"].update(span_m=.6,chord_count=4,ranges=[
            {"min_m":c,"max_m":c,"count":1} for c in (.14,.12,.07,0)])
        config["settings"].update(cycles=3,span_panels=4,chord_panels=2,wake_model="prescribed",wake_cycles=2)
        config['tail']=copy.deepcopy(model.DEFAULT['tail'])
        config['tail'].update(enabled=False,pitch_deg=8,span_panels=2,chord_panels=2)
        config['waveform']={'mode':'custom','points':'0,0\n.15,1\n.35,0\n.65,-1\n1,0'}
        print("Running a small real UVLM case with custom waveform and one isolated wing, including animation...", flush=True)
        study_id=app.start(config)["id"]
        app.PROCESS.wait()
        study=model.OUTPUTS/study_id
        status=model.read_json(study/"status.json")
        assert status["state"]=="complete", f"Study failed. Read {study/'run.log'}"
        case=study/"case_0001"
        assert len(list(case.glob("*.png")))==4
        assert len(list(case.iterdir()))==7, "Unexpected per-case outputs."
        import xml.etree.ElementTree as ET
        template=ET.parse(case/"wing_right.svg").getroot()
        assert template.attrib["width"].endswith("mm") and template.attrib["height"].endswith("mm")
        bar=template.find("{http://www.w3.org/2000/svg}line[@id='scale-check']")
        assert float(bar.attrib["x2"])-float(bar.attrib["x1"])==100
        from PIL import Image
        with Image.open(case/"animation.webp") as animation:
            assert animation.n_frames>1, "Animation is not animated."
            animation.seek(animation.n_frames-1); animation.load()
            frames=animation.n_frames
        data=model.case_data(study,"case_0001")
        assert len(data["history"])>0
        assert 'tail_thrust_N' not in data['history_columns']
        assert 'single_wing_thrust_N' in data['history_columns']
        assert 'single_wing_root_roll_moment_Nm' in data['history_columns']
        assert 'ideal_phase_drive_load_torque_Nm' not in data['history_columns']
        assert data['metrics']['shape_objective_version']=='isolated_single_wing_mean_thrust_peak_roll_v2'
        assert data['metrics']['shape_ratio_valid']
        assert data['case']['omitted_zero_chord_count']==1
        assert len(data['case']['sections'])==3
        assert all(s['chord_m']>0 for s in data['case']['sections'])
        assert (study/'comparisons/shape_comparison.png').is_file()
        model.shape_comparison(study,export=True)
        landscape=model.shape_landscape(study,repeat_only=any(model.shape_eligible(r) for r in model.read_json(study/'results.json')),export=True)
        assert len(landscape['points'])==1 and landscape['interpolation_kind']=='points'
        assert (model.OUTPUTS/landscape['file']).is_file()
        assert not data['metrics']['tail_enabled']
        assert data['metrics']['simulation_mode']==model.SIMULATION_MODE
        import numpy as np
        values=np.asarray(data['history']);columns=data['history_columns']
        roll=values[:,columns.index('rolling_moment_wind_Nm')]
        root=values[:,columns.index('single_wing_root_roll_moment_Nm')]
        np.testing.assert_allclose(roll,-root,atol=1e-8)
        assert np.max(np.abs(roll))>.01
        np.testing.assert_allclose(values[:,columns.index('estimated_two_wing_thrust_N')],2*values[:,columns.index('thrust_N')])
        assert data['metrics']['estimated_two_wing_mean_thrust_N']==2*data['metrics']['single_wing_mean_thrust_N']
        for axes in (["chord_1_m","chord_3_m"],["chord_1_m","chord_2_m","chord_3_m"]):
            model.design_plot(study,axes,model.OBJECTIVE,{})
        model.overlay([{"study":study_id,"id":"case_0001"}])
        assert not list(study.rglob("*.pdf"))
        import catalog
        data_before=catalog.listing(model)
        assert data_before['case_count']==1
        number=data_before['rows'][0]['global_case_no']
        repeated_id=app.start(config)['id'];app.PROCESS.wait()
        repeated=model.OUTPUTS/repeated_id
        assert model.read_json(repeated/'status.json')['state']=='complete'
        repeated_row=model.read_json(repeated/'results.json')[0]
        assert repeated_row['global_case_no']==number and repeated_row['reused_from']['study']==study_id
        assert 'Building case_' not in (repeated/'run.log').read_text(encoding='utf-8')
        assert catalog.listing(model)['case_count']==1
        assert catalog.listing(model)['occurrence_count']==2
        with zipfile.ZipFile(model.OUTPUTS.parent/'master_runs.xlsx') as z:
            workbook=ET.fromstring(z.read('xl/workbook.xml'))
            assert [s.get('name') for s in workbook.find('{'+catalog.NS+'}sheets')]==['Wing parameters','Ranked results']
        print('PASS: master workbook, stable case numbers, and cross-study reuse without another solve.',flush=True)
        # Exercise the actual server entry point without depending on a particular
        # browser, a fixed port, or a previously running development server.
        import urllib.request
        server=subprocess.Popen([sys.executable,"-u",str(ROOT/"WingStudy"/"app.py"),
                                 "--no-browser","--port","0"],stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT,text=True,cwd=ROOT,
                                creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
        try:
            line=server.stdout.readline().strip()
            assert line.startswith("Wing Studies: http://127.0.0.1:"), line
            url=line.split("Wing Studies: ",1)[1]
            with urllib.request.urlopen(url+"/api/defaults",timeout=20) as response:
                defaults=json.load(response)
            assert Path(defaults["output_root"]).resolve()==model.OUTPUTS.resolve()
            with urllib.request.urlopen(url+"/ui.js",timeout=20) as response:
                assert b"renderBestDesign" in response.read()
            with urllib.request.urlopen(url+"/api/studies",timeout=20) as response:
                assert any(s["id"]==study_id for s in json.load(response))
        finally:
            server.terminate(); server.wait(timeout=20)
        print(f"PASS: simulation, four default PNGs, full-size SVG, {frames}-frame WebP, 2D/3D and overlay PNG/CSV exports.", flush=True)
        print("PASS: local GUI server, latest winning-design UI, study list and relocated output path.",flush=True)
        print(f"Verification results: {study}", flush=True)
    print("PASS: Wing Studies is ready. No external Python or Ptera installation was used.", flush=True)


if __name__=="__main__":
    try:
        main()
    except Exception as exc:
        print(f"CHECK FAILED: {exc}", file=sys.stderr, flush=True)
        raise
