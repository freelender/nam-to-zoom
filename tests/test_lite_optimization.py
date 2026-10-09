"""Differential full-rate Lite tests against the frozen pre-optimization kernel."""
import _ctypes
import ctypes
import math
import os
from pathlib import Path
import random
import subprocess
import tempfile
import unittest

from test_kernel_optimization import find_clang

ROOT = Path(__file__).resolve().parents[1]


class State(ctypes.Structure):
    _fields_ = [("layer_pos", ctypes.c_uint16 * 23), ("head_pos", ctypes.c_uint16)]


class LiteOptimizationTests(unittest.TestCase):
    def test_audio_rings_guards_and_resets(self):
        clang = find_clang()
        if not clang:
            self.skipTest("host Clang unavailable")
        with tempfile.TemporaryDirectory() as temporary:
            libraries, functions = [], []
            pointer = ctypes.POINTER(ctypes.c_float)
            try:
                for index, source in enumerate((ROOT / "tests/fixtures/lite_pair_original.c",
                                                ROOT / "tests/fixtures/lite_pair_shared_load_experiment.c")):
                    dll = Path(temporary) / (f"kernel{index}.dll" if os.name == "nt" else f"kernel{index}.so")
                    command = [clang, "-O3", "-ffp-contract=off", "-shared",
                               "-I", str(ROOT / "dsp/nam_a2_lite"), str(source), "-o", str(dll)]
                    if os.name == "nt":
                        command.append("-Wl,/export:compact_process_pair")
                    subprocess.run(command, check=True, capture_output=True)
                    library = ctypes.CDLL(str(dll))
                    libraries.append(library)
                    function = library.compact_process_pair
                    function.argtypes = [pointer, pointer, ctypes.POINTER(State), ctypes.c_float,
                                         ctypes.c_float, pointer, pointer]
                    function.restype = None
                    functions.append(function)
                for seed in (4, 34, 94):
                    rng = random.Random(seed)
                    weights = (ctypes.c_float * 1871)(*[rng.uniform(-.08, .08) for _ in range(1871)])
                    weights[-1] = 1
                    samples = [0.0 if i < 512 else (.5 if i % 509 == 0 else
                               .2 * math.sin(i * .011) + rng.uniform(-.02, .02)) for i in range(18000)]
                    results = []
                    for function in functions:
                        # Each run starts with fresh state, also testing reset determinism.
                        runs = []
                        for _ in range(2):
                            guarded = (ctypes.c_float * 19184)()
                            guarded[0] = guarded[-1] = 12345
                            history = ctypes.cast(ctypes.byref(guarded, 4), pointer)
                            state, output = State(), []
                            for offset in range(0, len(samples), 2):
                                y0, y1 = ctypes.c_float(), ctypes.c_float()
                                function(weights, history, ctypes.byref(state), *samples[offset:offset + 2],
                                         ctypes.byref(y0), ctypes.byref(y1))
                                output.extend((y0.value, y1.value))
                            self.assertEqual((guarded[0], guarded[-1]), (12345, 12345))
                            self.assertTrue(all(math.isfinite(value) for value in output))
                            runs.append(output)
                        self.assertEqual(runs[0], runs[1])
                        results.append((runs[0], bytes(state), list(guarded)))
                    expected, actual = results
                    self.assertEqual(expected[1], actual[1])
                    self.assertLess(max(abs(a - b) for a, b in zip(expected[0], actual[0])), 1e-5)
                    energy = sum(value * value for value in expected[0])
                    error = sum((a - b) ** 2 for a, b in zip(expected[0], actual[0]))
                    self.assertLess(error / max(energy, 1e-20), 1e-10)
                    self.assertLess(max(abs(a - b) for a, b in zip(expected[2], actual[2])), 1e-5)
            finally:
                functions.clear()
                if "function" in locals():
                    del function
                for library in libraries:
                    if os.name == "nt":
                        _ctypes.FreeLibrary(library._handle)
