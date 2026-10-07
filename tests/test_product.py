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
    def test_16_layer_experimental_exports_require_retraining(self):
        previous = model(3)
        submodel = previous["config"]["submodels"][0]["model"]
        layer = submodel["config"]["layers"][0]
        for key in ("kernel_sizes", "dilations", "activation", "gating_mode", "secondary_activation"):
            layer[key] = layer[key] + layer[key][:2]
        submodel["weights"] = [0.0] * 749
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "previous.nam"
            path.write_text(json.dumps(previous))
            self.assertEqual(classify(path)["status"], "adaptable")
            with self.assertRaisesRegex(ValueError, "geometry"):
                load_models([path], ["OLD"])

    def test_training_template_matches_pedal_geometry(self):
        from nam2zoom.compact import DILATIONS, KERNEL_SIZES, HEAD_KERNEL
        template = json.loads((ROOT / "training/a2-mid-44100/model.json").read_text())
        layer = template["net"]["config"]["submodels"][0]["config"]["layers_configs"][0]
        self.assertEqual(layer["kernel_sizes"], list(KERNEL_SIZES))
        self.assertEqual(layer["dilations"], list(DILATIONS))
        self.assertEqual(layer["head"]["kernel_size"], HEAD_KERNEL)
        self.assertEqual(layer["channels"], 3)

    def test_embedded_di_matches_desktop_digest(self):
        source = (ROOT / "apps/nam2zoom-desktop/Program.cs").read_text(encoding="utf-8")
        expected = re.search(r'BundledDiSha256 = "([A-F0-9]+)"', source).group(1)
        actual = hashlib.sha256(
            (ROOT / "apps/nam2zoom-desktop/Assets/TRAINING_DI.wav").read_bytes()
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
            self.assertTrue((root / "bank" / "nam_a2_amp_readable.png").is_file())
            self.assertIn("#define N2Z_OPTIMIZED_KERNEL 1",
                          (root / "bank/bank_config.h").read_text(encoding="ascii"))
            lock = json.loads((root / "bank/bank.json").read_text(encoding="utf-8"))
            self.assertEqual(lock["load_profile"], "pair-150")
            self.assertEqual(lock["processing_samples"], 2)
            self.assertEqual(lock["history_bytes"], 20076)
            self.assertEqual(lock["network_layers"], 14)
            self.assertEqual(lock["weights_per_model"], 659)
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

    def test_ten_models_and_eleventh_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "amp.nam"
            source.write_text(json.dumps(model(3)))
            models = load_models([source] * 10, [f"AMP{i}" for i in range(10)])
            manifest = prepare_bank(models, root / "ten")
            config = json.loads(manifest.read_text())
            self.assertEqual(len(config["params"][0]["values"]), 10)
            self.assertEqual(config["const_blob"]["words"], 6590)
            with self.assertRaisesRegex(ValueError, "1-10 NAM"):
                load_models([source] * 11)
            with self.assertRaisesRegex(ValueError, "bank weights"):
                prepare_bank(models + models[:1], root / "eleven")
            self.assertFalse((root / "eleven").exists())


if __name__ == "__main__":
    unittest.main()
