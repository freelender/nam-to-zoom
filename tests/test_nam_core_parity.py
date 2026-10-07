"""Compare a real trained export through the pedal kernel and NAM Core renderer."""

import ctypes
import _ctypes
import json
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from test_kernel_optimization import State, find_clang

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from nam2zoom.compact import geometry, pair_history_bytes, inspect


@unittest.skipUnless(os.environ.get("NAM2ZOOM_PARITY_MODEL")
                     and importlib.util.find_spec("numpy") and importlib.util.find_spec("soundfile"),
                     "provide a real trained NAM and the training Python for renderer parity")
class NamCoreParityTests(unittest.TestCase):
    def test_trained_export_matches_native_renderer(self):
        import numpy as np
        import soundfile as sf
        source = Path(os.environ["NAM2ZOOM_PARITY_MODEL"]).resolve(strict=True)
        parsed = inspect(json.loads(source.read_text()))
        self.assertEqual(parsed.channels, 3)
        kernels, dilations, head = geometry(parsed.profile)
        class ProfileState(ctypes.Structure):
            _fields_ = [("layer_pos", ctypes.c_uint16 * len(kernels)), ("head_pos", ctypes.c_uint16)]
        clang = find_clang()
        self.assertIsNotNone(clang, "renderer parity requires host Clang")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            library_path = root / ("pair.dll" if os.name == "nt" else "pair.so")
            command = [clang, "-O3", "-ffp-contract=off", "-shared"]
            if os.name == "nt":
                command.append("-Wl,/export:compact_process_pair")
            kernel_dir = "nam_a2_lite" if parsed.profile == "lite" else "nam_a2_compact"
            command += [str(ROOT / "dsp" / kernel_dir / "compact_pair.c"), "-o", str(library_path)]
            subprocess.run(command, check=True, capture_output=True)
            samples = np.random.default_rng(716).uniform(-.3, .3, 10000).astype("float32")
            samples[:512] = 0
            samples[-2048:] = 0
            dry, rendered = root / "dry.wav", root / "core.wav"
            sf.write(dry, samples, 44100, subtype="FLOAT")
            subprocess.run([str(ROOT / "reference/nam_a2/build-core-ninja/core_render.exe"),
                            str(source), str(dry), str(rendered)], check=True, capture_output=True)
            expected, rate = sf.read(rendered, dtype="float32")
            self.assertEqual(rate, 44100)
            library = ctypes.CDLL(str(library_path))
            pointer = ctypes.POINTER(ctypes.c_float)
            pair = library.compact_process_pair
            pair.argtypes = [pointer, pointer, ctypes.POINTER(ProfileState), ctypes.c_float,
                             ctypes.c_float, pointer, pointer]
            pair.restype = None
            weights = (ctypes.c_float * len(parsed.weights))(*parsed.weights)
            capacity = pair_history_bytes(parsed.profile) // 4
            guarded = (ctypes.c_float * (capacity + 2))()
            guarded[0] = guarded[-1] = 12345
            history = ctypes.cast(ctypes.byref(guarded, 4), pointer)
            state = ProfileState()
            actual = np.zeros_like(samples)
            try:
                # NAM Core Reset prewarms with silence. Match the production pedal
                # callback's receptive-field warmup before comparing every input sample.
                for _ in range(0, parsed.receptive_field, 2):
                    y0, y1 = ctypes.c_float(), ctypes.c_float()
                    pair(weights, history, ctypes.byref(state), 0, 0,
                         ctypes.byref(y0), ctypes.byref(y1))
                for i in range(0, len(samples), 2):
                    y0, y1 = ctypes.c_float(), ctypes.c_float()
                    pair(weights, history, ctypes.byref(state), samples[i], samples[i + 1],
                         ctypes.byref(y0), ctypes.byref(y1))
                    actual[i:i + 2] = y0.value, y1.value
                self.assertEqual((guarded[0], guarded[-1]), (12345, 12345))
                self.assertTrue(np.isfinite(actual).all())
                error = actual.astype("float64") - expected
                energy = float(np.dot(expected.astype("float64"), expected.astype("float64")))
                self.assertGreater(energy, 1e-12)
                self.assertLess(float(np.dot(error, error)) / energy, 1e-8)
                self.assertLess(float(np.max(np.abs(error))), 1e-4)
                print(f"{parsed.profile} {len(kernels)}-layer pedal kernel vs NAM Core: max error {np.max(np.abs(error)):.3g}")
            finally:
                del pair
                if os.name == "nt":
                    _ctypes.FreeLibrary(library._handle)
