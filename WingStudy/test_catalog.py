"""Catalog identity, reuse, provenance and portable Excel regression checks."""
import copy
import csv
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET
import zipfile
import model
import catalog

class CatalogChecks(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=model.HERE)
        self.out=Path(self.temp.name)/"studies";self.out.mkdir()
        self.patch=patch.object(model,"OUTPUTS",self.out);self.patch.start()
        config=copy.deepcopy(model.DEFAULT)
        config["shape_sweep"].update(chord_count=3,ranges=[{"min_m":v,"max_m":v,"count":1} for v in (.1,.08,.05)])
        config["settings"].update(span_panels=4,chord_panels=2,cycles=3,dt_s=.025,wake_model="prescribed",wake_cycles=2)
        self.spec=model.plan(config);self.spec.update(ptera_version="5.1.0",companion_version="3.1.0")
    def tearDown(self):self.patch.stop();self.temp.cleanup()
    def saved(self,name="source",thrust=2.,moment=1.):
        spec=copy.deepcopy(self.spec);catalog.prepare(model,spec,name)
        study=self.out/name;study.mkdir();case=spec["cases"][0];folder=study/case["id"];folder.mkdir()
        model.write_json(study/"manifest.json",spec)
        for filename in catalog.CASE_FILES:(folder/filename).write_bytes(b"test fixture"*8)
        (study/"comparisons").mkdir()
        columns=model.HISTORY_COLUMNS+model.SINGLE_WING_HISTORY_COLUMNS+model.TORQUE_HISTORY_COLUMNS
        with (study/"comparisons/time_histories.csv").open("w",newline="") as f:
            writer=csv.writer(f);writer.writerow(["case",*columns])
            writer.writerows([case["id"],*([i*.025]+[0.]*(len(columns)-1))] for i in range(121))
        row={**case,"status":"ok","shape_ratio_valid":True,"cycle_repeatable":True,
             "single_wing_mean_thrust_N":thrust,"single_wing_peak_abs_roll_moment_Nm":moment,
             catalog.OBJECTIVE:thrust/moment,"mean_thrust_N":thrust,"mean_lift_N":0.,"window_start_s":2.,"window_end_s":3.}
        catalog.record(model,spec,name,row);model.write_json(study/"results.json",[row])
        return spec,study,row
    def test_identity_changes_with_every_physical_setting(self):
        case=self.spec["cases"][0];s=self.spec["settings"];baseline=catalog.signature(model,case,s)
        for key,value in {"frequency_hz":2.,"amplitude_deg":22.,"speed_mps":.6,"rho":1000.,"nu":1e-6,
                          "dt_s":.02,"cycles":4,"span_panels":6,"chord_panels":3,"wake_model":"free",
                          "wake_cycles":1,"cycle_tolerance_pct":3.,"waveform":{"mode":"custom","points":[[0,0],[1,0]]}}.items():
            changed=copy.deepcopy(s);changed[key]=value
            self.assertNotEqual(catalog.signature(model,case,changed),baseline,key)
        changed=copy.deepcopy(case);changed["sections"][1]["chord_m"]+=.01
        self.assertNotEqual(catalog.signature(model,changed,s),baseline)
        changed=copy.deepcopy(case);changed.update(id="case_9999",design_name="Another name",global_case_no=900)
        self.assertEqual(catalog.signature(model,changed,{**s,"case_budget":1}),baseline)
        self.assertNotEqual(catalog.signature(model,case,s,{"different_solver":True}),baseline)
    def test_stable_number_and_cross_study_reuse(self):
        first,source,row=self.saved();second=copy.deepcopy(self.spec);catalog.prepare(model,second,"destination")
        self.assertEqual(first["cases"][0]["global_case_no"],second["cases"][0]["global_case_no"])
        directory=self.out/"destination"/"case_0001";directory.mkdir(parents=True)
        metrics=catalog.reuse(model,second["cases"][0],second["settings"],directory)
        self.assertIsNotNone(metrics);self.assertEqual(metrics["reused_from"]["study"],"source")
        self.assertEqual(len(list(directory.iterdir())),7)
        newrow={**second["cases"][0],**metrics,"status":"ok"}
        catalog.record(model,second,"destination",newrow)
        data=catalog.listing(model);self.assertEqual(data["case_count"],1);self.assertEqual(data["occurrence_count"],2)
        self.assertEqual(data["rows"][0]["_study"],"source")
        self.assertEqual(sum(o["reused"] for o in data["rows"][0]["occurrences"]),1)
        self.assertNotIn("id",metrics)
    def test_missing_failed_and_unverified_results_do_not_reuse(self):
        spec,source,row=self.saved();destination=self.out/"other"/"case_0001";destination.mkdir(parents=True)
        (source/"case_0001/animation.webp").unlink()
        self.assertIsNone(catalog.reuse(model,spec["cases"][0],spec["settings"],destination))
        with catalog.connect(model) as db:db.execute("UPDATE cases SET state='failed'")
        self.assertIsNone(catalog.reuse(model,spec["cases"][0],spec["settings"],destination))
        self.assertFalse(catalog.verified_import(model,{"companion_version":"unknown","ptera_version":"5.1.0"}))
    def test_sync_is_idempotent_and_keeps_ids_after_source_loss(self):
        spec,source,row=self.saved();catalog.sync(model);catalog.sync(model)
        data=catalog.listing(model);self.assertEqual(data["case_count"],1);number=data["rows"][0]["global_case_no"]
        (source/"case_0001/animation.webp").unlink();catalog.sync(model)
        data=catalog.listing(model);self.assertEqual(data["rows"][0]["global_case_no"],number)
        self.assertFalse(data["rows"][0]["outputs_available"])
    def test_worker_uses_completed_case_without_solving(self):
        self.saved();spec=copy.deepcopy(self.spec);catalog.prepare(model,spec,"cached")
        study=self.out/"cached";study.mkdir();model.write_json(study/"manifest.json",spec)
        with patch.object(model,"run_case",side_effect=AssertionError("Repeated solver call")),patch.object(model,"shape_comparison"),patch.object(model,"shape_landscape"):
            model.worker(study)
        self.assertEqual(model.read_json(study/"status.json")["state"],"complete")
        row=model.read_json(study/"results.json")[0];self.assertIn("reused_from",row)
        self.assertEqual(catalog.listing(model)["case_count"],1)
    def test_excel_two_sheets_rank_controls_links_and_open_file(self):
        self.saved(thrust=2.,moment=1.)
        other=copy.deepcopy(self.spec);other["cases"][0]["sections"][1]["chord_m"]+=.01
        self.spec=other;self.saved("other",thrust=3.,moment=3.)
        default=catalog.listing(model);self.assertEqual(default["rows"][0]["_study"],"source")
        by_thrust=catalog.listing(model,"single_wing_mean_thrust_N");self.assertEqual(by_thrust["rows"][0]["_study"],"other")
        path=catalog.export(model,"single_wing_mean_thrust_N",browser_url="http://127.0.0.1:9999")
        ns={"s":catalog.NS}
        with zipfile.ZipFile(path) as z:
            wb=ET.fromstring(z.read("xl/workbook.xml"));self.assertEqual([s.get("name") for s in wb.find("s:sheets",ns)],["Wing parameters","Ranked results"])
            sheet=ET.fromstring(z.read("xl/worksheets/sheet2.xml"));cells={c.get("r"):c for c in sheet.findall(".//s:c",ns)}
            self.assertEqual(float(cells["H6"].find("s:v",ns).text),3.)
            self.assertIn("COUNTIFS",cells["A6"].find("s:f",ns).text)
            self.assertIn("CHOOSE(MATCH",cells["Q6"].find("s:f",ns).text)
            self.assertIn("Single-wing mean thrust",cells["B3"].find("s:is/s:t",ns).text)
            self.assertEqual(len(sheet.find("s:dataValidations",ns)),2)
            self.assertIn(b"9999/#catalog",z.read("xl/worksheets/_rels/sheet2.xml.rels"))
        original=path.read_bytes()
        with patch.object(catalog.os,"replace",side_effect=PermissionError("Excel is open")):catalog.export(model)
        self.assertEqual(path.read_bytes(),original);self.assertIn("Close master_runs.xlsx",catalog.listing(model)["excel_pending"])
        catalog.export(model);self.assertEqual(catalog.listing(model)["excel_pending"],"")

class LandscapeChecks(unittest.TestCase):
    def rows(self):
        sections=[{"rhat":0.,"y_m":0.,"chord_m":.1,"x_m":0.,"pitch_deg":0.,"roll_deg":0.},
                  {"rhat":1.,"y_m":.2,"chord_m":.08,"x_m":0.,"pitch_deg":0.,"roll_deg":0.}]
        return [{"id":"case_0001","global_case_no":n,"_study":f"study{n}","_signature":str(n),"_verified":True,
                 "_settings":copy.deepcopy(model.DEFAULT["settings"]),"sections":sections,"span_m":.4,
                 "status":"ok","shape_ratio_valid":True,"cycle_repeatable":True,"simulation_mode":model.SIMULATION_MODE,
                 "area_m2":.02*n,"aspect_ratio":2./n,catalog.OBJECTIVE:float(n),
                 "single_wing_mean_thrust_N":float(n),"single_wing_peak_abs_roll_moment_Nm":1.} for n in (1,2,3)]
    def test_selected_ids_and_duplicate_local_ids(self):
        selected,spec=catalog.landscape_data(model,self.rows(),[3,1])
        self.assertEqual([p["global_case_no"] for p in spec["points"]],[3,1])
        self.assertEqual(len(set(p["case_id"] for p in spec["points"])),2)
        self.assertEqual([p["source_study"] for p in spec["points"]],["study3","study1"])
        self.assertEqual([p["source_case"] for p in spec["points"]],["case_0001"]*2)
    def test_mixed_conditions_have_no_interpolation(self):
        rows=self.rows();rows[1]["_settings"]["frequency_hz"]=123.
        _,spec=catalog.landscape_data(model,rows,[1,2,3])
        self.assertFalse(spec["triangles"]);self.assertFalse(spec["curve"])
        self.assertIn("conditions differ",spec["note"])
    def test_invalid_selection_rejected(self):
        for numbers in ([],[1,1],[999],[True],["1"]):
            with self.assertRaises(ValueError):catalog.landscape_data(model,self.rows(),numbers)
    def test_export_contains_only_selected_cases(self):
        selected,spec=catalog.landscape_data(model,self.rows(),[3,1])
        with tempfile.TemporaryDirectory(dir=model.HERE) as td:
            result=model.shape_landscape(Path(td),False,True,selected_rows=selected,selected_spec=spec)
            folder=Path(td)/"comparisons"
            with (folder/"wing_shape_landscape_all.csv").open(newline="",encoding="utf-8") as f:records=list(csv.DictReader(f))
            self.assertEqual([int(r["global_case_no"]) for r in records],[3,1])
            self.assertEqual([r["source_case"] for r in records],["case_0001"]*2)
            self.assertEqual(set(p.suffix for p in folder.iterdir()),{".csv",".png"})
            self.assertGreater((folder/"wing_shape_landscape_all.png").stat().st_size,1000)
            self.assertIn("frequency_hz",json.loads(records[0]["driving_and_solver_settings"]))

if __name__=="__main__":unittest.main()
