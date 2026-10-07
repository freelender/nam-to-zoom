"""Validation leakage, reproducible probes and unaligned fidelity metrics."""

import json
import io
from contextlib import redirect_stdout
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

try:
    import numpy as np
    import soundfile as sf
except ImportError:
    np = sf = None

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from nam2zoom.adapt import RATE, prepare_configs, training_split, cache_key
from benchmark_adaptation import evaluate_report, probe_audio, scores


class QualityReviewTests(unittest.TestCase):
    def test_failed_conversion_can_be_reviewed_without_retraining(self):
        from nam2zoom import adapt as backend
        from test_compact_shape import model
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, di, cache = root / "source.nam", root / "di.wav", root / "cache"
            source.write_bytes(b"source")
            di.write_bytes(b"di")

            def prepare(source, di, work, rate, ir):
                dry, wet = work / "dry.wav", work / "wet.wav"
                dry.write_bytes(b"dry")
                wet.write_bytes(b"wet")
                return dry, wet, False, {}

            def train(command, **kwargs):
                export = Path(command[6]) / "run" / "model.nam"
                export.parent.mkdir()
                export.write_text(json.dumps(model(3)))

            with patch.object(backend, "classify", return_value={"status": "adaptable", "sample_rate": 44100}), \
                 patch.object(backend, "prepare_pair", side_effect=prepare), \
                 patch.object(backend, "_run", side_effect=train) as trainer, \
                 patch.object(backend, "quality", return_value={"esr": .05384, "correlation": .99}), \
                 patch.object(backend, "training_split", return_value={"duplicate_intro_excluded": True}), \
                 patch.object(backend, "write_preview", return_value=root / "preview"), \
                 redirect_stdout(io.StringIO()) as output:
                with self.assertRaisesRegex(ValueError, "quality gate"):
                    backend.adapt(source, di, cache, epochs=300)
                self.assertEqual(trainer.call_count, 1)
                student = backend.adapt(source, di, cache, epochs=300, review_quality=True)
                self.assertTrue(student.is_file())
                self.assertEqual(trainer.call_count, 1)
                result = json.loads(next(line[15:] for line in output.getvalue().splitlines()
                                         if line.startswith("QUALITY_RESULT=")))
                self.assertEqual(result["status"], "review-required")
                self.assertEqual(result["max_esr"], .05)
                self.assertEqual(result["esr"], .05384)
                # A prior acceptance must not bypass a later strict request.
                with self.assertRaisesRegex(ValueError, "quality gate"):
                    backend.adapt(source, di, cache, epochs=300)
                # Index-only cache reuse must also report the failed score for review.
                next(cache.glob("*/quality.json")).unlink()
                backend.adapt(source, di, cache, epochs=300, review_quality=True)
                self.assertEqual(trainer.call_count, 1)
                self.assertEqual(output.getvalue().count('"status": "review-required"'), 2)
                # The desktop's first run can collect a fresh failed-quality result too.
                backend.adapt(source, di, root / "fresh-cache", epochs=300, review_quality=True)
                self.assertEqual(trainer.call_count, 2)
                self.assertEqual(output.getvalue().count('"status": "review-required"'), 3)

    def test_review_does_not_allow_invalid_or_tampered_cached_model(self):
        from nam2zoom.adapt import cached_model, digest
        from test_compact_shape import model
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            student = root / "student.nam"
            student.write_text(json.dumps(model(3)))
            record = {"model": "student.nam", "model_sha256": digest(student),
                      "esr": .01, "correlation": 1.1}
            index = root / "key.json"
            index.write_text(json.dumps(record))
            with self.assertRaisesRegex(ValueError, "invalid quality scores"):
                cached_model(root, "key", .05, review_quality=True)
            record["correlation"] = .99
            index.write_text(json.dumps(record))
            student.write_text("tampered")
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                cached_model(root, "key", .05, review_quality=True)


class StandardLossTests(unittest.TestCase):
    def test_standard_training_config(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = prepare_configs(root / "dry.wav", root / "wet.wav", root, 300)
            configs = [json.loads(path.read_text()) for path in paths]
            self.assertEqual(configs[1]["loss"]["mrstft_weight"], .0005)
            self.assertEqual(configs[2]["trainer"]["max_epochs"], 300)

    def test_standard_cache_key_preserves_existing_entries_with_and_without_ir(self):
        import hashlib
        from nam2zoom.adapt import digest, PIPELINE_VERSION, IR_PIPELINE_VERSION, MODEL_TEMPLATE, LEARNING_TEMPLATE
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, di, ir = [root / name for name in ("amp.nam", "di.wav", "cab.wav")]
            for path in (source, di, ir):
                path.write_bytes(path.name.encode())
            for cab in (None, ir):
                # Match the standard key before the loss option was removed.
                material = ((IR_PIPELINE_VERSION if cab else PIPELINE_VERSION) + "\n"
                            + digest(source) + "\n" + digest(di) + "\nepochs=300\n"
                            + f"model_config={digest(MODEL_TEMPLATE)}\n"
                            + f"learning_config={digest(LEARNING_TEMPLATE)}\n"
                            + (f"ir={digest(cab)}\n" if cab else ""))
                self.assertEqual(cache_key(source, di, 300, cab),
                                 hashlib.sha256(material.encode("ascii")).hexdigest())

    def test_recovery_rejects_other_loss_profile(self):
        from nam2zoom.adapt import completed_candidate, digest, PIPELINE_VERSION
        from test_compact_shape import model
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, di = root / "amp.nam", root / "di.wav"
            source.write_bytes(b"source")
            di.write_bytes(b"di")
            key = cache_key(source, di, 300)
            work = root / (key[:12] + "-completed")
            work.mkdir()
            student = work / "student.nam"
            student.write_text(json.dumps(model(3)))
            (work / "quality.json").write_text(json.dumps({
                "pipeline": PIPELINE_VERSION, "epochs": 300,
                "source_sha256": digest(source), "training_di_sha256": digest(di),
                "student": str(student), "student_sha256": digest(student),
                "esr": .01, "correlation": .99, "loss_profile": "weaker-spectral"}))
            self.assertIsNone(completed_candidate(root, key, source, di, 300, .05))
            report_path = work / "quality.json"
            report = json.loads(report_path.read_text())
            report["loss_profile"] = "standard"
            report_path.write_text(json.dumps(report))
            self.assertIsNotNone(completed_candidate(root, key, source, di, 300, .05))


@unittest.skipIf(np is None, "quality tests require the training Python environment")
class AdaptationQualityTests(unittest.TestCase):
    def test_duplicate_intro_is_not_used_for_training(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            rng = np.random.default_rng(7)
            x = rng.normal(0, .1, 30 * RATE).astype("float32")
            x[-9 * RATE:] = x[:9 * RATE]
            dry = root / "dry.wav"
            sf.write(dry, x, RATE, subtype="FLOAT")
            data, _, _ = prepare_configs(dry, root / "wet.wav", root, 100,
                                         independent_validation=True)
            config = json.loads(data.read_text())
            self.assertEqual(config["train"]["start_seconds"], 9.25)
            self.assertEqual(config["train"]["stop_seconds"], -9.25)
            self.assertEqual(config["validation"]["start_seconds"], -9.0)
            self.assertTrue(training_split(dry)["duplicate_intro_excluded"])

    def test_default_preserves_established_training_split(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data, _, _ = prepare_configs(root / "dry.wav", root / "wet.wav", root, 100)
            config = json.loads(data.read_text())
            self.assertIsNone(config["train"]["start_seconds"])
            self.assertEqual(config["train"]["stop_seconds"], -9.0)

    def test_nonrepeated_di_retains_intro_and_leaves_history_guard(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "dry.wav"
            x = np.random.default_rng(11).normal(0, .1, 30 * RATE).astype("float32")
            sf.write(path, x, RATE, subtype="FLOAT")
            split = training_split(path)
            self.assertIsNone(split["start_seconds"])
            self.assertFalse(split["duplicate_intro_excluded"])
            self.assertEqual(split["stop_seconds"], -9.25)

    def test_short_smoke_test_validation_window_is_supported(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "dry.wav"
            sf.write(path, np.zeros(2 * RATE, dtype="float32"), RATE, subtype="FLOAT")
            with patch("nam2zoom.adapt.VALIDATION_SECONDS", .25):
                split = training_split(path)
            self.assertEqual(split["start_seconds"], .5)
            self.assertEqual(split["stop_seconds"], -.5)

    def test_new_cache_key_invalidates_previous_pipeline_cache(self):
        import hashlib
        from nam2zoom.adapt import digest
        with tempfile.TemporaryDirectory() as temporary:
            source, di = Path(temporary) / "amp.nam", Path(temporary) / "di.wav"
            source.write_bytes(b"source")
            di.write_bytes(b"di")
            old = hashlib.sha256(("teacher-student-full-v1\n" + digest(source)
                                 + "\n" + digest(di) + "\nepochs=100\n").encode("ascii")).hexdigest()
            self.assertNotEqual(cache_key(source, di, 100), old)

    def test_metrics_do_not_hide_gain_or_timing_errors(self):
        x = probe_audio()[RATE:]
        self.assertEqual(scores(x, x)["esr"], 0)
        self.assertAlmostEqual(scores(x * .5, x)["esr"], .25, places=6)
        self.assertGreater(scores(np.roll(x, 100), x)["esr"], .1)

    def test_training_config_changes_invalidate_cache(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, di, config = root / "amp.nam", root / "di.wav", root / "learning.json"
            source.write_bytes(b"source")
            di.write_bytes(b"di")
            config.write_text("first")
            with patch("nam2zoom.adapt.LEARNING_TEMPLATE", config):
                first = cache_key(source, di, 100)
                config.write_text("second")
                self.assertNotEqual(first, cache_key(source, di, 100))

    def test_probes_are_reproducible_and_nonclipping(self):
        x = probe_audio()
        np.testing.assert_array_equal(x, probe_audio())
        self.assertFalse(np.array_equal(x, probe_audio(seed=12)))
        self.assertLessEqual(float(np.max(np.abs(x))), .600001)
        self.assertEqual(len(x), 12 * RATE)

    def test_metrics_reject_invalid_audio(self):
        x = probe_audio()[RATE:]
        for invalid in (np.full_like(x, np.nan), np.full_like(x, 8), np.zeros_like(x), x[:-1]):
            with self.subTest(shape=invalid.shape):
                with self.assertRaises(ValueError):
                    scores(invalid, x)

    def test_followup_rejects_modified_export_before_rendering(self):
        from nam2zoom.adapt import digest
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, student = root / "teacher.nam", root / "student.nam"
            source.write_bytes(b"teacher")
            student.write_bytes(b"export")
            report = root / "results.json"
            report.write_text(json.dumps({
                "format": "nam2zoom.fidelity-benchmark.v1", "status": "complete",
                "results": [{"source": str(source), "source_sha256": digest(source),
                             "student": str(student), "student_sha256": digest(student)}]}))
            student.write_bytes(b"different export")
            with patch("benchmark_adaptation.render") as renderer:
                with self.assertRaisesRegex(ValueError, "student changed"):
                    evaluate_report(report, root / "followup", 0)
                renderer.assert_not_called()
            self.assertFalse((root / "followup").exists())


if __name__ == "__main__":
    unittest.main()
