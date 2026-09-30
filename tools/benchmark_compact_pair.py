"""Offline host throughput and TI listing comparison; never connects to a pedal."""

import argparse
import _ctypes
import ctypes
import hashlib
import json
import math
import os
from pathlib import Path
import random
import re
import statistics
import struct
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from test_kernel_optimization import State, find_clang

SOURCE = ROOT / "dsp/experiments/compact_pair_bench.c"
TI = ROOT / ".tooling/cgt-8.3.1/ti-cgt-c6000_8.3.1"


def section_sizes(path):
    raw = path.read_bytes()
    if raw[:5] != b"\x7fELF\x01":
        raise ValueError("expected ELF32 TI object")
    header = struct.unpack_from("<16sHHIIIIIHHHHHH", raw)
    offset, stride, count, strings = header[6], header[11], header[12], header[13]
    sections = [struct.unpack_from("<10I", raw, offset + i * stride) for i in range(count)]
    names = raw[sections[strings][4]:sections[strings][4] + sections[strings][5]]
    return {names[s[0]:].split(b"\0", 1)[0].decode(): s[5] for s in sections if s[0]}


def function_metrics(text):
    matches = list(re.finditer(r";\* FUNCTION NAME:\s*(\w+)", text))
    result = {}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = text[match.start():end]
        frame = re.search(r"Local Frame Size[^\r\n]*=\s*(\d+) byte", body)
        result[match[1]] = {"local_frame_bytes": int(frame[1]) if frame else None,
                            "static_sp_operand_occurrences": len(re.findall(r"\*SP", body)),
                            "local_call_targets": sorted(set(re.findall(
                                r"\bCALLP?\s+\.\w+\s+(\w+)", body)))}
    def peak(name, visited):
        if name in visited:
            raise ValueError("recursive local call graph cannot be bounded here")
        row = result[name]
        children = [target for target in row["local_call_targets"] if target in result]
        return (row["local_frame_bytes"] or 0) + max(
            (peak(child, visited | {name}) for child in children), default=0)

    for name in result:
        result[name]["known_local_peak_frame_bytes"] = peak(name, set())
    return result


def ti_report(folder, pair):
    compiler = TI / "bin/cl6x.exe"
    if not compiler.is_file():
        return {"status": "skipped", "reason": "TI 8.3.1 compiler unavailable"}
    obj = folder / "benchmark.obj"
    command = [str(compiler), "--c99", "--opt_level=3", "--silicon_version=6740",
               "--abi=eabi", "--endian=little", "--object_format=elf", "--symdebug:none",
               "--mem_model:const=data", "--mem_model:data=far_aggregates",
               "--keep_asm", "--src_interlist", f"--include_path={TI / 'include'}"]
    if pair:
        command.append("--define=BENCH_PAIR=1")
    command += ["-c", str(SOURCE), f"--output_file={obj}"]
    result = subprocess.run(command, cwd=folder, check=True, capture_output=True, text=True)
    (folder / "compile.log").write_text(result.stdout + result.stderr, encoding="utf-8")
    listing = folder / "compact_pair_bench.asm"
    text = listing.read_text(encoding="utf-8")
    schedules = []
    for block in text.split("SOFTWARE PIPELINE INFORMATION")[1:]:
        end = block.find(";** --------------------------------------------------------------------------*")
        block = block[:end] if end >= 0 else block[:5000]
        schedules.append([line.strip(";* \t") for line in block.splitlines()
                          if any(token in line for token in
                                 ("Loop source", "Loop Unroll", "Known Minimum",
                                  "Known Maximum", "ii =", "Bound", "Disqualified",
                                  "Collapsed", "prolog", "epilog", "Register"))])
    return {"status": "compiled", "command": command, "sections": section_sizes(obj),
            "functions": function_metrics(text),
            "frames": re.findall(r"Local Frame Size[^\r\n]+", text),
            "static_sp_operand_occurrences": len(re.findall(r"\*SP", text)),
            "pipeline_annotations": schedules,
            "listing": str(listing), "object_sha256": hashlib.sha256(obj.read_bytes()).hexdigest()}


def host_report(folder, pair, weights, samples):
    clang = find_clang()
    if not clang:
        return {"status": "skipped", "reason": "host Clang unavailable"}, None
    library_path = folder / ("benchmark.dll" if os.name == "nt" else "benchmark.so")
    command = [clang, "-O3", "-ffp-contract=off", "-Wno-unknown-pragmas", "-shared"]
    if pair:
        command.append("-DBENCH_PAIR=1")
    if os.name == "nt":
        command.append("-Wl,/export:compact_benchmark")
    command += [str(SOURCE), "-o", str(library_path)]
    subprocess.run(command, check=True, capture_output=True)
    library = ctypes.CDLL(str(library_path))
    function = library.compact_benchmark
    pointer = ctypes.POINTER(ctypes.c_float)
    function.argtypes = [pointer, pointer, ctypes.POINTER(State), pointer, pointer, ctypes.c_uint]
    function.restype = None
    count = len(samples)
    w = (ctypes.c_float * 659)(*weights)
    x = (ctypes.c_float * count)(*samples)
    y = (ctypes.c_float * count)()
    history_count = 5019 if pair else 9948
    runs = []
    try:
        for _ in range(8):
            history = (ctypes.c_float * history_count)()
            state = State()
            start = time.perf_counter()
            function(w, history, ctypes.byref(state), x, y, count)
            runs.append(time.perf_counter() - start)
        median = statistics.median(runs[1:])
        return {"status": "measured_on_host", "command": command,
                "seconds": runs[1:], "median_seconds": median,
                "samples_per_second": count / median, "samples": count,
                "history_bytes": history_count * 4}, bytes(y)
    finally:
        del function
        if os.name == "nt":
            _ctypes.FreeLibrary(library._handle)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    rng = random.Random(34)
    weights = [rng.uniform(-0.08, 0.08) for _ in range(659)]
    weights[-1] = 1.0
    samples = [math.sin(i * 0.011) * 0.2 for i in range(65536)]
    report = {"scope": "kernel-only offline experiment; no firmware timing or DSP-load measurement",
              "production_changed": False, "variants": {},
              "limits": ["PC throughput is not C674x throughput",
                         "Object-wide code, frames and SP counts include standalone and inlined code",
                         "Loop initiation intervals omit setup, drain, other code and memory/interrupt stalls",
                         "Known local frame peaks omit firmware caller and unknown imported callees",
                         "No bank callback, model-switch, control or pedal lifecycle validation"],
              "sources": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                          for p in (SOURCE, ROOT / "dsp/nam_a2_compact/compact_pair.c",
                                    ROOT / "dsp/nam_a2_compact/compact_pair.h",
                                    ROOT / "dsp/nam_a2_compact/compact_kernel.c",
                                    ROOT / "dsp/nam_a2_compact/compact_kernel.h")}}
    results = []
    for pair in (False, True):
        name = "pair" if pair else "scalar"
        folder = output / name
        folder.mkdir()
        host, audio = host_report(folder, pair, weights, samples)
        results.append(audio)
        report["variants"][name] = {"host": host, "ti": ti_report(folder, pair)}
    if all(r is not None for r in results):
        report["host_output_bit_exact"] = results[0] == results[1]
        if not report["host_output_bit_exact"]:
            raise ValueError("benchmark outputs differ; do not interpret timings")
        scalar = report["variants"]["scalar"]["host"]["median_seconds"]
        pair = report["variants"]["pair"]["host"]["median_seconds"]
        report["host_speed_ratio_scalar_over_pair"] = scalar / pair
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    for relative in report["sources"]:
        destination = output / "sources" / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes((ROOT / relative).read_bytes())
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
