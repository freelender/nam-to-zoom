"""Separate architecture, teacher, cache and portable-template checks."""
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from nam2zoom import adapt
from nam2zoom.compact import geometry, inspect, expected_parameters, pair_history_bytes, reserved_dsp_load
from nam2zoom.bank import load_models, prepare_bank
from nam2zoom.hybrid import classify
from nam2zoom.template import fill_template
from test_compact_shape import model


def lite_model():
    data = model(3)
    sub = data["config"]["submodels"][0]["model"]
    layer = sub["config"]["layers"][0]
    kernels, dilations, head = geometry("lite")
    layer.update(kernel_sizes=list(kernels), dilations=list(dilations),
                 activation=[{"type": "LeakyReLU", "negative_slope": .01}] * len(kernels),
                 gating_mode=["none"] * len(kernels), secondary_activation=[None] * len(kernels))
    layer["head"]["kernel_size"] = head
    sub["weights"] = [0.] * expected_parameters(3, "lite")
    return data


class LiteProfileTests(unittest.TestCase):
    def test_full_native_geometry_and_resources(self):
        parsed = inspect(lite_model(), "lite")
        self.assertEqual(parsed.profile, "lite")
        self.assertEqual(len(parsed.weights), 1871)
        self.assertEqual(parsed.receptive_field, 6347)
        self.assertEqual(pair_history_bytes("lite"), 76728)
        self.assertEqual(reserved_dsp_load("lite"), 270)
        self.assertEqual(reserved_dsp_load("compact"), 150)
        config = json.loads(adapt.model_template("lite").read_text())
        layer = config["net"]["config"]["submodels"][0]["config"]["layers_configs"][0]
        kernels, dilations, head = geometry("lite")
        self.assertEqual(layer["kernel_sizes"], list(kernels))
        self.assertEqual(layer["dilations"], list(dilations))
        self.assertEqual(layer["head"]["kernel_size"], head)
        native = ROOT / ".tooling/neural-amp-modeler/nam/train/_resources/config_model_packed.json"
        if native.exists():
            official = json.loads(native.read_text())["net"]["config"]["submodels"][0]["config"]["layers_configs"][0]
            self.assertEqual(layer, official)

    def test_wrong_profile_requires_adaptation_and_bank_rejects_it(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "lite.nam"
            path.write_text(json.dumps(lite_model()))
            self.assertEqual(classify(path, "lite")["status"], "direct")
            self.assertEqual(classify(path, "compact")["status"], "adaptable")
            with self.assertRaisesRegex(ValueError, "geometry"):
                load_models([path], profile="compact")
            self.assertEqual(len(load_models([path], profile="lite")[0][2]), 1871 * 4)
            path.write_text(json.dumps(model(3)))
            self.assertEqual(classify(path, "lite")["status"], "adaptable")

    def test_configs_and_cache_are_separate_with_and_without_ir(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, di, ir = [root / name for name in ("source.nam", "di.wav", "ir.wav")]
            for path in (source, di, ir):
                path.write_bytes(b"fixture")
            for cab in (None, ir):
                self.assertNotEqual(adapt.cache_key(source, di, 300, cab),
                                    adapt.cache_key(source, di, 300, cab, profile="lite"))
            configs = adapt.prepare_configs(di, di, root, 300, profile="lite")
            config = json.loads(configs[1].read_text())
            self.assertEqual(config["loss"]["mrstft_weight"], .0005)
            self.assertEqual(len(config["net"]["config"]["submodels"][0]["config"]["layers_configs"][0]["dilations"]), 23)

    def test_completed_recovery_cannot_cross_architectures(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, di = root / "source.nam", root / "di.wav"
            source.write_bytes(b"source"); di.write_bytes(b"di")
            key = adapt.cache_key(source, di, 300, profile="lite")
            work = root / (key[:12] + "-complete")
            work.mkdir()
            student = work / "student.nam"
            student.write_text(json.dumps(lite_model()))
            report = {"pipeline": adapt.PIPELINE_VERSION, "epochs": 300,
                      "source_sha256": adapt.digest(source), "training_di_sha256": adapt.digest(di),
                      "student": str(student), "student_sha256": adapt.digest(student),
                      "esr": .01, "correlation": .99, "model_profile": "compact"}
            report_path = work / "quality.json"
            report_path.write_text(json.dumps(report))
            self.assertIsNone(adapt.completed_candidate(root, key, source, di, 300, .05, profile="lite"))
            report["model_profile"] = "lite"
            report_path.write_text(json.dumps(report))
            self.assertIsNotNone(adapt.completed_candidate(root, key, source, di, 300, .05, profile="lite"))

    def test_lite_teacher_selects_original_lite_submodel(self):
        try:
            import numpy as np
            import soundfile as sf
        except ImportError:
            self.skipTest("teacher checks require audio libraries")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, di = root / "source.nam", root / "di.wav"
            source.write_text(json.dumps({"architecture": "SlimmableContainer", "sample_rate": 48000}))
            x = .1 * np.sin(np.arange(44100 * 30) * .06)
            sf.write(di, x, 44100, subtype="FLOAT")
            commands = []
            def render(command):
                commands.append(command)
                y, rate = sf.read(command[-2])
                sf.write(command[-1], y * .5, rate, subtype="FLOAT")
            for profile, slim in (("compact", "1.0"), ("lite", "0.0")):
                work = root / profile
                work.mkdir()
                with patch.object(adapt, "_run", side_effect=render):
                    dry, wet, _, _ = adapt.prepare_pair(source, di, work, 48000, profile=profile)
                self.assertEqual(commands[-1][1:3], ["--slim", slim])
                self.assertEqual(sf.info(wet).samplerate, 44100)
                self.assertEqual(sf.info(dry).frames, sf.info(wet).frames)


@unittest.skipUnless(os.environ.get("NAM2ZOOM_LITE_TEMPLATE_DIR"), "maintainer compiles Lite templates")
class LiteTemplateTests(unittest.TestCase):
    def test_underreserved_lite_template_is_rejected(self):
        import shutil
        from nam2zoom.template import digest
        from zd2 import parse_zd2_bytes, compute_checksum
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            directory = root / "templates"
            shutil.copytree(os.environ["NAM2ZOOM_LITE_TEMPLATE_DIR"], directory)
            path = directory / "bank-1.ZD2"
            raw = bytearray(path.read_bytes())
            zd2 = parse_zd2_bytes(bytes(raw))
            info = next(chunk for chunk in zd2.chunks if chunk.tag == "INFO")
            struct.pack_into("<f", raw, info.offset + 8 + len(info.data) - 4, 150.)
            struct.pack_into("<I", raw, 8, compute_checksum(raw))
            path.write_bytes(raw)
            index_path = directory / "index.json"
            index = json.loads(index_path.read_text())
            index["banks"]["1"]["sha256"] = digest(bytes(raw))
            index_path.write_text(json.dumps(index))
            manifest = prepare_bank([(root / "fixture.nam", "AMP", bytes(1871 * 4), "fixture")],
                                    root / "bank", profile="lite")
            with self.assertRaisesRegex(ValueError, "DSP reservation"):
                fill_template(directory, manifest)
            self.assertFalse((manifest.parent / "build").exists())

    def test_all_capacities_patch_weights_without_changing_code(self):
        from elf32 import parse_elf32
        from zd2 import parse_zd2_bytes
        templates = Path(os.environ["NAM2ZOOM_LITE_TEMPLATE_DIR"])
        index = json.loads((templates / "index.json").read_text())
        for count in range(1, 4):
            with self.subTest(count=count), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                payload = struct.pack("<1871f", *([.01] * 1871))
                models = [(root / "fixture.nam", f"AMP{i}", payload, "fixture") for i in range(count)]
                manifest = prepare_bank(models, root / "bank", profile="lite")
                self.assertEqual(json.loads(manifest.read_text())["dspload"], 270)
                lock = json.loads((manifest.parent / "bank.json").read_text())
                self.assertEqual(lock["history_bytes"], 76728)
                built = fill_template(templates, manifest).read_bytes()
                actual = parse_zd2_bytes(built)
                self.assertTrue(actual.checksum_valid)
                info = next(chunk for chunk in actual.chunks if chunk.tag == "INFO")
                self.assertEqual(struct.unpack_from("<f", info.data, len(info.data) - 4)[0], 270)
                original = parse_zd2_bytes((templates / f"bank-{count}.ZD2").read_bytes())
                for section in parse_elf32(original.data_chunk.data).sections:
                    if section.name != ".const":
                        self.assertEqual(original.data_chunk.data[section.offset:section.offset + section.size],
                                         actual.data_chunk.data[section.offset:section.offset + section.size])
                offset = index["banks"][str(count)]["weights_offset"]
                self.assertEqual(built[offset:offset + len(payload) * count], payload * count)
                if os.environ.get("NAM2ZOOM_TEMPLATE_DIR"):
                    with self.assertRaisesRegex(ValueError, "profile mismatch"):
                        fill_template(Path(os.environ["NAM2ZOOM_TEMPLATE_DIR"]), manifest)
