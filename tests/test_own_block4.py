"""Full-rate four-sample engine versus the released two-sample engine."""
import _ctypes
import ctypes
import json
import math
import os
from pathlib import Path
import random
import re
import shutil
import subprocess
import tempfile
import unittest

from test_kernel_optimization import find_clang

ROOT = Path(__file__).resolve().parents[1]
Pointer = ctypes.POINTER(ctypes.c_float)


class State(ctypes.Structure):
    _fields_ = [("positions", ctypes.c_uint16 * 24)]


def compare(model_weights, candidate_source=None, candidate_header=None, compact_effect=False):
    clang = find_clang()
    if not clang:
        raise unittest.SkipTest("host Clang unavailable")
    libraries = []
    results = {}
    with tempfile.TemporaryDirectory() as temporary:
        directory = Path(temporary)
        header = candidate_header or ROOT / "dsp/nam_a2_own_host/block4.h"
        shutil.copyfile(header, directory / "compact_pair.h")
        candidate_size = int(re.search(r"N2Z_FULL_HISTORY_FLOATS\s+(\d+)|PAIR_HISTORY_FLOATS\s+(\d+)", header.read_text()).group(1) or re.search(r"PAIR_HISTORY_FLOATS\s+(\d+)", header.read_text()).group(1))
        candidate_lanes = 16 if "compact_process_block" in header.read_text() else 4
        if compact_effect:
            candidate_size, candidate_lanes = 20118, 12
        rng = random.Random(491)
        # Silence, impulses, varying levels, transients and sustained multitone;
        # long enough to wrap even the longest ring several times.
        samples = [0.0 if i < 256 else (0.9 if i % 997 == 0 else
                   (0.8 if i > 12000 else 0.08) * math.sin(i * .037)
                   + .04 * math.sin(i * .173) + rng.uniform(-.015, .015))
                   for i in range(24000)]
        weights = (ctypes.c_float * 1871).from_buffer_copy(model_weights)
        try:
            for name, source, size, lanes in (
                ("pair", ROOT / "dsp/nam_a2_lite/compact_pair.c", 19182, 2),
                ("quad", candidate_source or ROOT / "dsp/nam_a2_own_host/block4.c", candidate_size, candidate_lanes),
                ("v180", ROOT / "tests/fixtures/own_block4_v180.c", 19542, 4),
                ("v181", ROOT / "tests/fixtures/own_block4_v181.c", 19542, 4)):
                symbol = "compact_process_pair" if lanes == 2 else ("compact_process_block" if lanes in (12,16) else "compact_process_quad")
                dll = directory / (name + (".dll" if os.name == "nt" else ".so"))
                command = [clang, "-O3", "-ffp-contract=off", "-shared", "-I", str(directory), str(source), "-o", str(dll)]
                if name == "quad" and compact_effect:
                    command += ["-DN2Z_COMPACT_EFFECT=1"]
                if os.name == "nt":
                    command += ["-Wl,/export:" + symbol]
                subprocess.run(command, check=True, capture_output=True)
                library = ctypes.CDLL(str(dll))
                libraries.append(library)
                function = getattr(library, symbol)
                function.restype = None
                function.argtypes = [Pointer, Pointer, ctypes.POINTER(State)] + (
                    [ctypes.c_float, ctypes.c_float, Pointer, Pointer] if lanes == 2 else [Pointer, Pointer])
                runs = []
                for _ in range(2):
                    guard = (ctypes.c_float * (size + 2))()
                    guard[0] = guard[-1] = 12345
                    history = ctypes.cast(ctypes.byref(guard, 4), Pointer)
                    state, outputs = State(), []
                    for offset in range(0, len(samples), lanes):
                        output = (ctypes.c_float * lanes)()
                        if lanes == 2:
                            function(weights, history, ctypes.byref(state), *samples[offset:offset+2],
                                     ctypes.cast(output, Pointer), ctypes.cast(ctypes.byref(output, 4), Pointer))
                        else:
                            function(weights, history, ctypes.byref(state),
                                     (ctypes.c_float * lanes)(*samples[offset:offset+lanes]), output)
                        outputs.extend(output)
                    assert guard[0] == guard[-1] == 12345, "history overrun"
                    assert all(math.isfinite(x) for x in outputs), "nonfinite output"
                    runs.append(outputs)
                assert runs[0] == runs[1], "nondeterministic reset"
                results[name] = runs[0]
                del function
            assert results["quad"] == results["v180"], "four-sample audio changed from v1.8.0"
            assert results["quad"] == results["v181"], "audio changed from v1.8.1"
            error = sum((a-b)**2 for a, b in zip(results["pair"], results["quad"]))
            energy = sum(a*a for a in results["pair"])
            report = {"max_absolute_error": max(abs(a-b) for a,b in zip(results["pair"], results["quad"])),
                      "error_to_signal_energy": error / max(energy, 1e-30), "samples": len(samples),
                      "bit_identical_to_v180_native": True, "bit_identical_to_v181_native": True}
            assert report["max_absolute_error"] < 2e-5, report
            assert report["error_to_signal_energy"] < 1e-9, report
            return report
        finally:
            for library in libraries:
                if os.name == "nt":
                    _ctypes.FreeLibrary(library._handle)


class OwnBlock4Tests(unittest.TestCase):
    def test_audio_wraps_bounds_and_reset(self):
        import struct
        for seed in (4, 34, 94):
            rng = random.Random(seed)
            weights = [rng.uniform(-.08, .08) for _ in range(1871)]
            weights[-1] = 1
            compare(struct.pack("<1871f", *weights))


if __name__ == "__main__":
    import sys
    if len(sys.argv) == 2 and Path(sys.argv[1]).is_dir():
        sys.path.insert(0, str(ROOT / "tools"))
        from nam2zoom.bank import load_models
        print(json.dumps({path.name: compare(load_models([path], ["TEST"], profile="lite")[0][2])
                          for path in sorted(Path(sys.argv[1]).glob("*.nam"))}, indent=2))
    else:
        unittest.main()
