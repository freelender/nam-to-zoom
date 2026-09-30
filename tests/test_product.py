"""Tests for the distributable bank pipeline without pedal or GPU access."""

import json
import hashlib
import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from nam2zoom.bank import load_models, normalize_labels, prepare_bank  # noqa: E402
from nam2zoom.compact import expected_parameters  # noqa: E402
from nam2zoom.hybrid import classify  # noqa: E402
from test_compact_shape import model  # noqa: E402


class ProductTests(unittest.TestCase):
    def test_embedded_di_matches_desktop_digest(self):
        # This macOS port has no apps/nam2zoom-desktop (WinForms); its SwiftUI
        # replacement carries the same constant and embedded resource.
        source = (ROOT / "Sources/nam2zoomMac/AppViewModel.swift").read_text(encoding="utf-8")
        expected = re.search(r'bundledDiSha256 =\s*\n?\s*"([A-F0-9]+)"', source).group(1)
        actual = hashlib.sha256(
            (ROOT / "Sources/nam2zoomMac/Resources/TRAINING_DI.wav").read_bytes()
        ).hexdigest().upper()
        self.assertEqual(actual, expected)

    def test_prepare_one_model_bank(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "amp.nam"
            source.write_text(json.dumps(model(3)), encoding="utf-8")
            self.assertEqual(classify(source)["status"], "direct")
            models = load_models([source], ["AMP01"])
            manifest = prepare_bank(models, root / "bank")
            data = json.loads(manifest.read_text(encoding="ascii"))
            self.assertEqual(data["dspload"], 150)
            self.assertEqual(data["const_blob"]["words"], expected_parameters(3))
            self.assertEqual(data["params"][0]["values"], ["AMP01", "EMPTY"])
            self.assertEqual([param["name"] for param in data["params"]],
                             ["Model", "Bass", "Mid", "Treble", "Vol", "Input", "Mix"])
            self.assertEqual(data["params"][-1]["max"], 100)
            self.assertEqual(data["params"][-1]["default"], 100)
            self.assertTrue((root / "bank" / "bank_effect.c").is_file())
            self.assertTrue((root / "bank" / "nam_a2_zoom_ms50g_plus.png").is_file())
            self.assertIn("#define N2Z_OPTIMIZED_KERNEL 1",
                          (root / "bank/bank_config.h").read_text(encoding="ascii"))
            lock = json.loads((root / "bank/bank.json").read_text(encoding="utf-8"))
            self.assertEqual(lock["load_profile"], "pair-150")
            self.assertEqual(lock["processing_samples"], 2)
            self.assertEqual(lock["history_bytes"], 20076)
            for name in ("compact_pair.c", "compact_pair.h"):
                self.assertEqual((root / "bank" / name).read_bytes(),
                                 (ROOT / "dsp/nam_a2_compact" / name).read_bytes())

    def test_label_rules(self):
        paths = [Path("one.nam"), Path("two.nam")]
        self.assertEqual(normalize_labels(paths, ["ONE", "TWO"]), ["ONE", "TWO"])
        with self.assertRaisesRegex(ValueError, "unique"):
            normalize_labels(paths, ["SAME", "same"])
        with self.assertRaisesRegex(ValueError, "1-5"):
            normalize_labels(paths, ["TOOLONG", "TWO"])


if __name__ == "__main__":
    unittest.main()
