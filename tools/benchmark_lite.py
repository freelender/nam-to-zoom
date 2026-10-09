"""Offline original/optimized Lite comparison; PC timing is not pedal timing."""
import _ctypes
import argparse
import ctypes
import json
import math
import os
from pathlib import Path
import random
import shutil
import statistics
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from test_kernel_optimization import find_clang
from benchmark_compact_pair import section_sizes, function_metrics


class State(ctypes.Structure):
    _fields_ = [("layer_pos", ctypes.c_uint16 * 23), ("head_pos", ctypes.c_uint16)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(ROOT / "dsp/nam_a2_lite/compact_pair.h", output / "compact_pair.h")
    clang = find_clang()
    if not clang:
        raise RuntimeError("Clang is required")
    pointer = ctypes.POINTER(ctypes.c_float)
    rng = random.Random(716)
    weights = (ctypes.c_float * 1871)(*[rng.uniform(-.08, .08) for _ in range(1871)])
    weights[-1] = 1
    count = 65536
    samples = (ctypes.c_float * count)(*[0 if i < 512 else .2 * math.sin(i * .011)
                                       + rng.uniform(-.02, .02) for i in range(count)])
    report = {"scope": "isolated kernel; no pedal speed, firmware stack limit or saved-patch claim",
              "variants": {}}
    baseline = None
    ti = ROOT / ".tooling/cgt-8.3.1/ti-cgt-c6000_8.3.1"
    for name, source in (("original", ROOT / "tests/fixtures/lite_pair_original.c"),
                         ("optimized", ROOT / "tests/fixtures/lite_pair_shared_load_experiment.c")):
        shutil.copyfile(source, output / f"{name}.c")
        wrapper = output / f"{name}-wrapper.c"
        wrapper.write_text(f'#include "{name}.c"\n'
                           'void replay(const float *w,float *h,CompactPairState *s,const float *x,float *y,unsigned n)'
                           '{unsigned i;for(i=0;i<n;i+=2)compact_process_pair(w,h,s,x[i],x[i+1],y+i,y+i+1);}\n',
                           encoding="utf-8")
        dll = output / (f"{name}.dll" if os.name == "nt" else f"{name}.so")
        command = [clang, "-O3", "-ffp-contract=off", "-shared", str(wrapper), "-o", str(dll)]
        if os.name == "nt":
            command.append("-Wl,/export:replay")
        subprocess.run(command, check=True, capture_output=True)
        library = ctypes.CDLL(str(dll))
        function = library.replay
        function.argtypes = [pointer, pointer, ctypes.POINTER(State), pointer, pointer, ctypes.c_uint]
        function.restype = None
        runs = []
        try:
            for _ in range(8):
                history = (ctypes.c_float * 19182)()
                state, actual = State(), (ctypes.c_float * count)()
                start = time.perf_counter()
                function(weights, history, ctypes.byref(state), samples, actual, count)
                runs.append(time.perf_counter() - start)
            if baseline is None:
                baseline = list(actual)
            errors = [float(a) - float(b) for a, b in zip(actual, baseline)]
            row = {"host_median_seconds": statistics.median(runs[1:]),
                   "max_absolute_error": max(map(abs, errors)),
                   "relative_squared_error": sum(e * e for e in errors) / sum(v * v for v in baseline)}
            if (ti / "bin/cl6x.exe").exists():
                command = [str(ti / "bin/cl6x.exe"), "--c99", "--silicon_version=6740", "--abi=eabi",
                           "-O3", "--keep_asm", "--src_interlist", "--compile_only",
                           f"--include_path={ti / 'include'}", f"--obj_directory={output}",
                           f"--asm_directory={output}", str(output / f"{name}.c")]
                subprocess.run(command, check=True, capture_output=True)
                row["ti_text_bytes"] = section_sizes(output / f"{name}.obj")[".text"]
                row["ti_functions"] = function_metrics((output / f"{name}.asm").read_text(encoding="utf-8"))
                row["ti_command"] = command
            report["variants"][name] = row
        finally:
            del function
            if os.name == "nt":
                _ctypes.FreeLibrary(library._handle)
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
