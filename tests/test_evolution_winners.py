"""Winner evolution animations: lineage lookup, GIF, index.json, and attachment to the atlas data."""
import _paths  # noqa: F401  (repo root on sys.path)

import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

try:
    import matplotlib  # noqa: F401
    import PIL  # noqa: F401
    HAVE_PLOT = True
except ImportError:
    HAVE_PLOT = False


def fake_campaign(folder: Path, winner_key: str) -> None:
    folder.mkdir(parents=True)
    db = sqlite3.connect(folder / "campaign.sqlite")
    db.executescript("""
      create table searches(search_id text, phase text, level text, freq real, objective text, status text, tref real, mref real);
      create table lineages(search_id text, lineage text, half_span real, family text, status text, evals int);
      create table designs(key text, chords text, half_span real, thrust real, torque real, status text);
      create table accepted(search_id text, lineage text, seq int, key text, score real, pass int, node int, kind text);
    """)
    db.execute("insert into searches values('t0.50r@1Hz/lambda_1.25','focus','t0.50r',1.0,'lambda_1.25','done',2.0,1.0)")
    db.execute("insert into lineages values('t0.50r@1Hz/lambda_1.25','L07',0.32,'convex','done',40)")
    for seq in range(6):
        key = winner_key if seq == 4 else f"{seq:024x}"
        chords = [0.2] + [round(0.12 - 0.012 * seq - 0.01 * j, 4) for j in range(6)] + [0.0]
        db.execute("insert into designs values(?,?,?,?,?,?)", (key, json.dumps(chords), 0.32 + 0.005 * seq,
                                                                 1.5 + 0.1 * seq, 0.8 + 0.03 * seq, "verified"))
        db.execute("insert into accepted values('t0.50r@1Hz/lambda_1.25','L07',?,?,?,1,0,'step')", (seq, key, 0.1 * seq))
    db.commit()
    db.close()


class EvolutionLabels(unittest.TestCase):
    def test_objective_labels(self):
        from wingstudy.elastic_evolution import objective_label
        self.assertEqual(objective_label("lambda_1.25")["lambda"], 1.25)
        self.assertIsNone(objective_label("torque_1Nm")["lambda"])
        self.assertIn("no λ", objective_label("torque_1Nm")["label"])


@unittest.skipUnless(HAVE_PLOT, "matplotlib and Pillow are needed to render GIFs")
class EvolutionWinners(unittest.TestCase):
    def test_render_index_and_attach(self):
        from wingstudy.elastic_evolution import atlas_winners
        import atlas_data
        key = "ab" * 12
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            fake_campaign(tmp / "campaign", key)
            atlas = tmp / "atlas"
            (atlas / "data").mkdir(parents=True)
            winners = [{"study": "rod", "model": "t0.50r", "freq": 1.0, "key": key, "media": {"poster": "p.webp"}},
                       {"study": "rod", "model": "rigid", "freq": 1.0, "key": "cd" * 12}]
            (atlas / "data" / "meta.json").write_text(json.dumps({"winners": winners}), encoding="utf-8")
            self.assertEqual(atlas_winners(tmp / "campaign", "rod", atlas), 1)
            index = json.loads((atlas / "media" / "evolution" / "rod" / "index.json").read_text(encoding="utf-8"))
            e = index[key[:16]]
            self.assertEqual((e["lambda"], e["steps"], e["family"]), (1.25, 4, "convex"))   # seed + 4 steps to the winner
            self.assertTrue((atlas / "media" / e["gif"]).stat().st_size > 1000)
            D = {"winners": winners}
            self.assertEqual(atlas_data.attach_evolution(D, atlas / "media"), 1)
            self.assertEqual(D["winners"][0]["media"], {"poster": "p.webp", "evolution": e["gif"]})
            self.assertNotIn("evolution", D["winners"][1])


if __name__ == "__main__":
    unittest.main()
