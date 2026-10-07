"""Offline fidelity experiments; never builds effects or contacts a pedal.

Run with the developer training Python. Teacher/model/audio files stay local.
The independent synthetic probes are diagnostic, not a listening benchmark.
"""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time

from nam2zoom import adapt
from nam2zoom.compact import expected_parameters, inspect
from nam2zoom.hybrid import classify

ROOT = Path(__file__).resolve().parents[1]
PROFILES = ("legacy", "guarded", "cosine")


def scores(prediction, target, rate=44100):
    import numpy as np

    p, t = np.asarray(prediction, dtype=np.float64), np.asarray(target, dtype=np.float64)
    if p.ndim != 1 or p.shape != t.shape or not len(t):
        raise ValueError("evaluation audio must have matching nonempty mono shapes")
    if not np.isfinite(p).all() or not np.isfinite(t).all() or np.max(np.abs(p)) >= 8:
        raise ValueError("invalid or unsafe evaluation audio")
    power = float(np.dot(t, t))
    if power <= 1e-12 or np.std(p) == 0:
        raise ValueError("silent evaluation target or prediction")
    error = p - t
    # Include spectral magnitude error without fitting gain or aligning delays.
    n, hop = 2048, 512
    window = np.hanning(n)
    pframes = np.lib.stride_tricks.sliding_window_view(p, n)[::hop]
    tframes = np.lib.stride_tricks.sliding_window_view(t, n)[::hop]
    ps = np.abs(np.fft.rfft(pframes * window, axis=1))
    ts = np.abs(np.fft.rfft(tframes * window, axis=1))
    return {"esr": float(np.dot(error, error) / power),
            "correlation": float(np.corrcoef(p, t)[0, 1]),
            "rmse": float(np.sqrt(np.mean(error ** 2))),
            "spectral_error": float(np.linalg.norm(ps - ts) / max(np.linalg.norm(ts), 1e-12)),
            "sample_rate": rate}


def probe_audio(seed=20261006):
    """New deterministic plucks, sustained harmonics, noise and a sweep."""
    import numpy as np

    fs = adapt.RATE
    x = np.zeros(12 * fs, dtype=np.float32)
    rng = np.random.default_rng(seed)
    # First second is silence; later analysis discards a full second of context.
    for i, fundamental in enumerate((82.41, 110.0, 146.83, 196.0, 246.94, 329.63)):
        t = np.arange(fs) / fs
        tone = sum(np.sin(2 * np.pi * fundamental * h * t + rng.uniform(-np.pi, np.pi)) / h
                   for h in range(1, 7))
        x[(i + 1) * fs:(i + 2) * fs] = tone * np.exp(-4 * t)
    t = np.arange(2 * fs) / fs
    x[7 * fs:9 * fs] = .3 * (np.sin(2 * np.pi * 110 * t) + .5 * np.sin(2 * np.pi * 330 * t))
    x[9 * fs:10 * fs] = .15 * rng.standard_normal(fs)
    t = np.arange(fs) / fs
    x[10 * fs:11 * fs] = .3 * np.sin(2 * np.pi * (30 * t + (10000 - 30) * t * t / 2))
    return (x * (.6 / np.max(np.abs(x)))).astype(np.float32)


def run(command, log, env=None):
    with log.open("w", encoding="utf-8") as stream:
        subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT, env=env, check=True)


def render(model, audio, output, log, env, rate):
    import numpy as np
    import soundfile as sf
    from scipy.signal import resample_poly

    x, fs = sf.read(audio, dtype="float32")
    native = output.with_name(output.stem + "-input.wav")
    sf.write(native, resample_poly(x, rate // 300, fs // 300), rate, subtype="FLOAT")
    command = [str(adapt.RENDERER)]
    if classify(model)["architecture"] == "SlimmableContainer":
        command += ["--slim", "1.0"]
    run(command + [str(model), str(native), str(output)], log, env)
    y, actual_rate = sf.read(output, dtype="float32")
    if actual_rate != rate or y.ndim != 1 or len(y) != sf.info(native).frames:
        raise ValueError("renderer output rate, channels or length differs from input")
    y = resample_poly(y, fs // 300, rate // 300).astype(np.float32)
    if len(y) < len(x):
        raise ValueError("renderer output is shorter than evaluation input")
    return y[:len(x)]


def evaluate_report(report_path, output, probe_seed, test_di=None):
    """Evaluate existing exports on fresh audio without retraining."""
    import numpy as np
    import soundfile as sf

    original = json.loads(report_path.read_text(encoding="utf-8"))
    if (original.get("format") != "nam2zoom.fidelity-benchmark.v1"
            or original.get("status") != "complete" or not original.get("results")):
        raise ValueError("evaluation requires a complete benchmark report")
    rows = original["results"]
    for row in rows:
        for name in ("source", "student"):
            if adapt.digest(Path(row[name])) != row[name + "_sha256"]:
                raise ValueError(f"{name} changed since the benchmark")
    fs = adapt.RATE
    if test_di:
        x, actual_rate = sf.read(test_di, dtype="float32")
        if (actual_rate != fs or x.ndim != 1 or len(x) < 4 * fs
                or not np.isfinite(x).all() or np.max(np.abs(x)) > 1):
            raise ValueError("test DI must be finite mono 44.1 kHz audio, at least four seconds, within +/-1")
        if adapt.digest(test_di) == original["training_di_sha256"]:
            raise ValueError("test DI must differ from training DI")
    else:
        x = probe_audio(probe_seed)
    output.mkdir(parents=True, exist_ok=False)
    test = output / "independent-di.wav"
    sf.write(test, x, fs, subtype="FLOAT")
    env = os.environ.copy()
    env.update(OMP_NUM_THREADS="2", MKL_NUM_THREADS="2")
    report = {"format": "nam2zoom.fidelity-evaluation.v1", "status": "running",
              "expected_runs": len(rows), "benchmark": str(report_path),
              "benchmark_sha256": adapt.digest(report_path),
              "renderer_sha256": adapt.digest(adapt.RENDERER),
              "probe_seed": None if test_di else probe_seed,
              "test_kind": "user-provided-independent-DI" if test_di else "synthetic-diagnostic",
              "test_di_sha256": adapt.digest(test), "results": []}
    report_file = output / "results.json"
    targets = {}
    for number, row in enumerate(rows):
        source, student = Path(row["source"]), Path(row["student"])
        native_rate = classify(source)["sample_rate"]
        probes = {}
        work = output / f"run-{number + 1}"
        work.mkdir()
        for gain in (.25, .5, 1.0):
            key = (row["source_sha256"], gain)
            audio = output / f"probe-{gain}.wav"
            if not audio.exists():
                sf.write(audio, x * gain, fs, subtype="FLOAT")
            if key not in targets:
                target_file = output / f"target-{len(targets) + 1}.wav"
                targets[key] = render(source, audio, target_file,
                                      target_file.with_suffix(".log"), env, native_rate)
            prediction = render(student, audio, work / f"probe-{gain}.wav",
                                work / f"probe-{gain}.log", env, fs)
            probes[str(gain)] = scores(prediction[fs:], targets[key][fs:])
        result = {key: row[key] for key in ("source", "source_sha256", "student", "student_sha256", "profile", "seed")}
        result.update(loss=row.get("loss"), independent_probes=probes,
                      mean_probe_esr=float(np.mean([p["esr"] for p in probes.values()])),
                      mean_probe_spectral_error=float(np.mean([p["spectral_error"] for p in probes.values()])))
        report["results"].append(result)
        report_file.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        print(f"Evaluated {source.name}, loss {result['loss']}: ESR {result['mean_probe_esr']:.5f}, "
              f"spectral error {result['mean_probe_spectral_error']:.5f}", flush=True)
    report["status"] = "complete"
    report_file.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(f"Results: {report_file}", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("models", nargs="*", type=Path)
    parser.add_argument("--evaluate-report", type=Path,
                        help="evaluate a complete report's existing exports without retraining")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--epochs", type=int, default=30)
    parser.add_argument("--profiles", nargs="+", choices=PROFILES, default=list(PROFILES))
    parser.add_argument("--seeds", nargs="+", type=int, default=[0])
    parser.add_argument("--mrstft-weights", nargs="+", type=float,
                        help="spectral-loss weight sweep; requires --profiles legacy")
    parser.add_argument("--probe-seed", type=int, default=20261006)
    parser.add_argument("--training-di", type=Path, default=ROOT / "apps/nam2zoom-desktop/Assets/TRAINING_DI.wav")
    parser.add_argument("--test-di", type=Path, help="independent mono 44.1 kHz DI; never used to train/select checkpoints")
    args = parser.parse_args()
    if bool(args.models) == bool(args.evaluate_report):
        parser.error("provide model paths or --evaluate-report")
    if args.probe_seed < 0:
        parser.error("probe seed must be nonnegative")
    if not 1 <= args.epochs <= 300:
        parser.error("epochs must be 1..300")
    if len(set(args.profiles)) != len(args.profiles) or len(set(args.seeds)) != len(args.seeds):
        parser.error("profiles and seeds must be unique")
    if args.mrstft_weights is not None:
        if args.profiles != ["legacy"]:
            parser.error("loss sweeps require --profiles legacy to isolate the loss change")
        if (len(set(args.mrstft_weights)) != len(args.mrstft_weights)
                or any(not math.isfinite(w) or w <= 0 for w in args.mrstft_weights)):
            parser.error("MRSTFT weights must be unique, finite and positive")
    variants = [(p, w) for p in args.profiles for w in (args.mrstft_weights or [None])]
    args.output = args.output.resolve()
    if args.evaluate_report:
        if args.mrstft_weights is not None:
            parser.error("evaluation cannot change training loss weights")
        evaluate_report(args.evaluate_report.resolve(strict=True), args.output,
                        args.probe_seed, args.test_di)
        return
    args.training_di = args.training_di.resolve(strict=True)
    import numpy as np
    import soundfile as sf
    import torch

    args.output.mkdir(parents=True, exist_ok=False)
    env = os.environ.copy()
    env.update(OMP_NUM_THREADS="2", MKL_NUM_THREADS="2", MPLBACKEND="Agg",
               MPLCONFIGDIR=str(args.output / "mpl-cache"), PYTHONUNBUFFERED="1")
    test = args.output / "independent-di.wav"
    if args.test_di:
        x, fs = sf.read(args.test_di, dtype="float32")
        if fs != adapt.RATE or x.ndim != 1 or len(x) < 4 * fs or not np.isfinite(x).all() or np.max(np.abs(x)) > 1:
            raise ValueError("test DI must be finite mono 44.1 kHz audio, at least four seconds, within +/-1")
        # Exact duplicate files are insufficient for independent evaluation.
        if adapt.digest(args.test_di) == adapt.digest(args.training_di):
            raise ValueError("test DI must differ from training DI")
    else:
        x, fs = probe_audio(args.probe_seed), adapt.RATE
    sf.write(test, x, fs, subtype="FLOAT")
    report = {"format": "nam2zoom.fidelity-benchmark.v1", "epochs": args.epochs,
              "status": "running", "expected_runs": len(args.models) * len(variants) * len(args.seeds),
              "training_di_sha256": adapt.digest(args.training_di),
              "test_di_sha256": adapt.digest(test),
              "test_kind": "user-provided-independent-DI" if args.test_di else "synthetic-diagnostic",
              "probe_seed": None if args.test_di else args.probe_seed,
              "test_selection": "used for experiment comparisons; never used for gradients or checkpoint selection",
              "environment": {"torch": torch.__version__, "cuda": torch.cuda.is_available(),
                              "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None},
              "student": {"channels": 3, "layers": len(adapt.KERNEL_SIZES), "weights": expected_parameters(3)},
              "renderer_sha256": adapt.digest(adapt.RENDERER), "results": []}
    report_path = args.output / "results.json"
    report_path.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    for number, source in enumerate(args.models):
        source = source.resolve(strict=True)
        decision = classify(source)
        if decision["status"] != "adaptable":
            raise ValueError(f"benchmark teacher must need adaptation: {source}")
        case = args.output / f"model-{number + 1}"
        case.mkdir()
        print(f"Preparing teacher {source.name}", flush=True)
        dry, wet, overs, _ = adapt.prepare_pair(source, args.training_di, case, decision["sample_rate"])
        targets = {}
        for gain in (.25, .5, 1.0):
            audio = case / f"probe-{gain}.wav"
            sf.write(audio, x * gain, fs, subtype="FLOAT")
            targets[gain] = render(source, audio, case / f"target-{gain}.wav",
                                   case / f"target-{gain}.log", env, decision["sample_rate"])
        for seed in args.seeds:
            for profile, spectral_weight in variants:
                label = profile if spectral_weight is None else f"{profile}-mrstft-{spectral_weight!r}"
                work = case / f"{label}-seed-{seed}"
                work.mkdir()
                data, model, learning = adapt.prepare_configs(
                    dry, wet, work, args.epochs, independent_validation=profile != "legacy")
                dc = json.loads(data.read_text())
                mc = json.loads(model.read_text())
                lc = json.loads(learning.read_text())
                lc["trainer"]["enable_progress_bar"] = False
                if spectral_weight is not None:
                    mc["loss"]["mrstft_weight"] = spectral_weight
                if profile == "cosine":
                    mc["lr_scheduler"] = {"class": "CosineAnnealingLR", "kwargs": {
                        "T_max": args.epochs, "eta_min": 0.00002}}
                    lc["trainer"]["gradient_clip_val"] = 1.0
                for path, config in ((data, dc), (model, mc), (learning, lc)):
                    path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
                training = work / "training"
                training.mkdir()
                training_env = env.copy()
                if overs:
                    training_env["NAM2ZOOM_ALLOW_FLOAT_OVERS"] = "1"
                # Set every training RNG before model creation, after importing NAM
                # (its full trainer sets a default torch seed at import time).
                code = ("import json, pathlib, random, numpy as np, torch; "
                        "from nam.train.full import main; "
                        f"random.seed({seed}); np.random.seed({seed}); torch.manual_seed({seed}); "
                        "import sys; main(*[json.load(open(p)) for p in sys.argv[1:4]], "
                        "pathlib.Path(sys.argv[4]), no_show=True, make_plots=False)")
                print(f"Training {source.name}: {label}, seed {seed}, {args.epochs} epochs", flush=True)
                start = time.perf_counter()
                run([sys.executable, "-c", code, str(data), str(model), str(learning), str(training)],
                    work / "training.log", training_env)
                seconds = time.perf_counter() - start
                exports = list(training.rglob("model.nam"))
                if len(exports) != 1:
                    raise ValueError("expected one student export")
                student = exports[0]
                inspect(json.loads(student.read_text()))
                validation = adapt.quality(student, dry, wet, work)
                probes = {}
                for gain, target in targets.items():
                    audio = case / f"probe-{gain}.wav"
                    prediction = render(student, audio, work / f"probe-{gain}.wav",
                                        work / f"probe-{gain}.log", env, adapt.RATE)
                    probes[str(gain)] = scores(prediction[fs:], target[fs:])
                row = {"source": str(source), "source_sha256": adapt.digest(source),
                       "profile": profile, "seed": seed, "seconds": seconds,
                       "loss": mc["loss"],
                       "student": str(student), "student_sha256": adapt.digest(student),
                       "config_sha256": {p.name: adapt.digest(p) for p in (data, model, learning)},
                       "validation": validation, "independent_probes": probes,
                       "mean_probe_esr": float(np.mean([p["esr"] for p in probes.values()])),
                       "mean_probe_spectral_error": float(np.mean([p["spectral_error"] for p in probes.values()]))}
                report["results"].append(row)
                report_path.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
                print(f"  validation ESR {validation['esr']:.5f}, independent ESR {row['mean_probe_esr']:.5f}, "
                      f"spectral error {row['mean_probe_spectral_error']:.5f}, {seconds:.1f}s", flush=True)
    report["status"] = "complete"
    report_path.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(f"Results: {report_path}", flush=True)


if __name__ == "__main__":
    main()
