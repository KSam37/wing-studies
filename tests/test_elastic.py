"""Regression checks for the stabilized elastic model (runs real Ptera solves, ~30 s).

  python -m unittest discover -s tests -p test_elastic.py -v
"""
import _paths  # noqa: F401  (repo root + legacy/ on sys.path)
import unittest

from wingstudy import elastic
from wingstudy import elastic_runner as R


class ElasticChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.case, cls.settings = R.load_catalog_case(7657)
        cls.rigid = R.run(cls.case, cls.settings, None)

    def test_rigid_baseline_matches_catalog(self):
        self.assertAlmostEqual(self.rigid["mean_thrust_N"], 2.0185088, places=5)
        self.assertAlmostEqual(self.rigid["peak_abs_root_torque_Nm"], 0.9977085, places=5)

    def test_very_stiff_plate_recovers_rigid(self):
        cfg = elastic.ElasticConfig(material=elastic.Material(shear_modulus_pa=4.5e14))
        r = R.run(self.case, self.settings, cfg)
        self.assertEqual(r["status"], "ok")
        self.assertAlmostEqual(r["mean_thrust_N"], self.rigid["mean_thrust_N"], delta=0.01)
        self.assertAlmostEqual(r["peak_abs_root_torque_Nm"], self.rigid["peak_abs_root_torque_Nm"], delta=0.01)

    def test_realistic_plate_is_stable_and_knob_independent(self):
        results = []
        for factor in (0.35, 0.7):
            r = R.run(self.case, self.settings, elastic.ElasticConfig(thickness_m=0.5e-3, added_mass_factor=factor))
            self.assertEqual(r["status"], "ok", r.get("error"))
            self.assertTrue(r["settled"])
            results.append(r)
        self.assertLess(abs(results[0]["mean_thrust_N"] - results[1]["mean_thrust_N"]) / results[0]["mean_thrust_N"], 0.01)


if __name__ == "__main__":
    unittest.main()
