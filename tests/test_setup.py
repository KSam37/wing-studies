"""Installer safeguards; no network requests or package installations."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location("setup_windows",Path(__file__).resolve().parents[1]/"tools"/"setup_windows.py")
setup=importlib.util.module_from_spec(spec);spec.loader.exec_module(setup)

class SetupChecks(unittest.TestCase):
    def test_native_solver_matches_pin(self):setup.verify_source()
    def test_checkout_move_changes_environment_location(self):
        with tempfile.TemporaryDirectory() as td,patch.dict(setup.os.environ,{"LOCALAPPDATA":td}):
            first=setup.configuration()
            with patch.object(setup,"ROOT",Path(td)/"other checkout"):
                second=setup.configuration()
            self.assertNotEqual(first,second)
            self.assertTrue(first[1].is_relative_to(Path(td)))
    def test_missing_setup_has_actionable_error(self):
        with tempfile.TemporaryDirectory() as td,patch.dict(setup.os.environ,{"LOCALAPPDATA":td}):
            with self.assertRaisesRegex(RuntimeError,"Run Setup Windows.cmd"):setup.configured_python()
    def test_changed_lock_requires_setup(self):
        with tempfile.TemporaryDirectory() as td,patch.dict(setup.os.environ,{"LOCALAPPDATA":td}):
            config,_=setup.configuration();config.parent.mkdir(parents=True)
            config.write_text(json.dumps({"python":"missing.exe","fingerprint":"old"}))
            with self.assertRaisesRegex(RuntimeError,"Dependencies changed"):setup.configured_python()
    def test_bad_native_file_rejected(self):
        with tempfile.TemporaryDirectory() as td,patch.object(setup,"ROOT",Path(td)):
            with self.assertRaisesRegex(RuntimeError,"Pinned Ptera source mismatch"):setup.verify_source()
    def test_nonempty_incomplete_checkout_never_overwritten(self):
        with tempfile.TemporaryDirectory() as td,patch.object(setup,"ROOT",Path(td)):
            target=Path(td)/"PteraSoftware";target.mkdir();note=target/"my-file.txt";note.write_text("preserve")
            with self.assertRaisesRegex(RuntimeError,"nonempty but incomplete"):setup.ensure_source()
            self.assertEqual(note.read_text(),"preserve")

if __name__=="__main__":unittest.main()
