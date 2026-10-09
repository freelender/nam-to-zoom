"""Profile limits reject oversized banks before reading files or creating output."""
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from nam2zoom.bank import load_models, prepare_bank, max_models
from nam2zoom.compact import expected_parameters

class BankLimitTests(unittest.TestCase):
    def test_lite_four_files_rejected_before_reading(self):
        with self.assertRaisesRegex(ValueError, "lite bank needs 1-3"):
            load_models([Path("missing.nam")] * 4, profile="lite")

    def test_template_rejects_oversized_manifest(self):
        import json
        from nam2zoom.template import fill_template
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / "bank.json").write_text(json.dumps({"model_profile": "lite"}))
            manifest = directory / "manifest.json"
            manifest.write_text(json.dumps({"params": [], "const_blob": {"words": 4 * 1871}}))
            with self.assertRaisesRegex(ValueError, "model count"):
                fill_template(directory / "missing-templates", manifest)

    def test_limits_and_build_boundaries(self):
        self.assertEqual(max_models("lite"), 3)
        self.assertEqual(max_models("compact"), 10)
        for profile, maximum in (("lite", 3), ("compact", 10)):
            models = [(Path("fixture.nam"), f"M{i}", bytes(expected_parameters(3, profile) * 4), "fixture")
                      for i in range(maximum + 1)]
            with tempfile.TemporaryDirectory() as temporary:
                output = Path(temporary) / "bank"
                with self.assertRaisesRegex(ValueError, "bank needs"):
                    prepare_bank(models, output, profile=profile)
                self.assertFalse(output.exists())
                self.assertTrue(prepare_bank(models[:maximum], output, profile=profile).is_file())
