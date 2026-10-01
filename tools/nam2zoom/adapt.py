"""Quality-gated PC teacher/student adaptation to the 44.1 kHz bank shape."""

from __future__ import annotations

import hashlib
import json
import math
import os
import platform
from pathlib import Path
import subprocess
import sys
import tempfile

from atomic_replace import atomic_replace

from .compact import inspect as inspect_compact
from .hybrid import classify
from .ir import bake, fit_teacher_level, load_ir


ROOT = Path(__file__).resolve().parents[2]
_RENDERER_NAME = "core_render.exe" if platform.system() == "Windows" else "core_render"
RENDERER = ROOT / "reference/nam_a2/build-core-ninja" / _RENDERER_NAME
MODEL_TEMPLATE = ROOT / "training/a2-mid-44100/model.json"
LEARNING_TEMPLATE = ROOT / "training/a2-compact-44100/learning.json"
PIPELINE_VERSION = "teacher-student-full-v1"
IR_PIPELINE_VERSION = "teacher-student-ir-v2"
RATE = 44100
VALIDATION_SECONDS = 9
FLOAT_OVER_PEAK_LIMIT = 1.05


def digest(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            sha.update(block)
    return sha.hexdigest()


def cache_key(source: Path, di: Path, epochs: int, ir: Path | None = None) -> str:
    version = IR_PIPELINE_VERSION if ir else PIPELINE_VERSION
    material = (version + "\n" + digest(source) + "\n" + digest(di)
                + f"\nepochs={epochs}\n"
                + (f"ir={digest(ir)}\n" if ir else "")).encode("ascii")
    return hashlib.sha256(material).hexdigest()


def valid_scores(record: dict) -> bool:
    return (all(isinstance(record.get(name), (int, float))
                and math.isfinite(record[name]) for name in ("esr", "correlation"))
            and record["esr"] >= 0 and -1 <= record["correlation"] <= 1)


def meets_quality(record: dict, max_esr: float) -> bool:
    return record["esr"] <= max_esr and record["correlation"] >= 0.95


def cached_model(cache: Path, key: str, max_esr: float,
                 best_effort: bool = False) -> Path | None:
    index = cache / f"{key}.json"
    if not index.is_file():
        return None
    record = json.loads(index.read_text(encoding="utf-8"))
    candidate = (cache / record["model"]).resolve()
    if not candidate.is_relative_to(cache.resolve()) or not candidate.is_file():
        raise ValueError("adaptation cache points outside its root or to a missing model")
    if digest(candidate) != record["model_sha256"]:
        raise ValueError("adaptation cache model hash mismatch")
    if not valid_scores(record):
        raise ValueError("adaptation cache has invalid quality scores")
    if not best_effort:
        if record["esr"] > max_esr:
            raise ValueError(f"cached adaptation ESR {record['esr']:.4f} exceeds {max_esr:.4f}")
        if record["correlation"] < 0.95:
            raise ValueError("cached adaptation correlation is below 0.95")
    inspect_compact(json.loads(candidate.read_text(encoding="utf-8")))
    return candidate


def completed_candidate(cache: Path, key: str, source: Path, di: Path,
                        epochs: int, max_esr: float,
                        ir: Path | None = None) -> tuple[Path, dict] | None:
    candidates = []
    source_hash, di_hash = digest(source), digest(di)
    for report_path in cache.glob(f"{key[:12]}-*/quality.json"):
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
            student = Path(report["student"]).resolve(strict=True)
            if (report["pipeline"] != (IR_PIPELINE_VERSION if ir else PIPELINE_VERSION)
                    or report["epochs"] != epochs
                    or report["source_sha256"] != source_hash
                    or report["training_di_sha256"] != di_hash
                    or (ir is not None and report.get("ir_sha256") != digest(ir))
                    or not student.is_relative_to(report_path.parent.resolve())
                    or digest(student) != report["student_sha256"]
                    or not valid_scores(report)):
                continue
            inspect_compact(json.loads(student.read_text(encoding="utf-8")))
            candidates.append((student, report))
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
            continue
    return min(candidates, key=lambda item: (not meets_quality(item[1], max_esr),
                item[1]["esr"],
                -item[1]["correlation"])) if candidates else None


def write_preview(work: Path) -> Path:
    import numpy as np
    import soundfile as sf

    preview = work / "preview"
    preview.mkdir(exist_ok=True)
    count = VALIDATION_SECONDS * RATE
    sources = ((work / "teacher_44100.wav", "original.wav"),
               (work / "validation_student.wav", "converted.wav"))
    for source, name in sources:
        with sf.SoundFile(source) as stream:
            if stream.samplerate != RATE or stream.channels != 1 or stream.frames < count:
                raise ValueError(f"invalid A/B preview source: {source}")
            stream.seek(stream.frames - count)
            samples = stream.read(count, dtype="float32")
        if len(samples) != count or not np.isfinite(samples).all():
            raise ValueError(f"invalid A/B preview audio: {source}")
        if name == "converted.wav" and np.max(np.abs(samples)) >= 8.0:
            raise ValueError("student validation output exceeds the pedal's audio guard")
        sf.write(preview / name, samples, RATE, subtype="FLOAT")
    return preview


def announce_result(student: Path, scores: dict, max_esr: float) -> None:
    status = "accurate" if meets_quality(scores, max_esr) else "best-effort"
    preview = write_preview(student.parents[2])
    result = {
        "status": status, "esr": scores["esr"],
        "correlation": scores["correlation"]}
    if "ir_gain_db" in scores:
        result["ir_gain_db"] = scores["ir_gain_db"]
    print("QUALITY_RESULT=" + json.dumps(result), flush=True)
    print(f"PREVIEW_DIR={preview}", flush=True)


def _run(command: list[str], *, env: dict | None = None) -> None:
    print("Running:", Path(command[0]).name, " ".join(command[1:4]), flush=True)
    subprocess.run(command, check=True, env=env)


def validate_teacher_level(wet) -> bool:
    import numpy as np

    peak = float(np.max(np.abs(wet)))
    if not np.isfinite(peak):
        raise ValueError("teacher output contains non-finite samples")
    if peak >= 1.0:
        if peak > FLOAT_OVER_PEAK_LIMIT or np.any(np.abs(wet) == 1.0):
            raise ValueError(f"teacher output appears clipped (peak {peak:.4f}); "
                             "reduce the source model's output level before adapting")
        print(f"Teacher has floating-point overs (peak {peak:.4f}); "
              "preserving gain for training", flush=True)
        return True
    return False


def prepare_pair(source: Path, di: Path, work: Path, rate: int,
                 ir: Path | None = None) -> tuple[Path, Path, bool, dict]:
    import numpy as np
    import soundfile as sf
    from scipy.signal import resample_poly

    info = sf.info(di)
    if info.samplerate != RATE or info.channels != 1 or info.duration < 30:
        raise ValueError("training DI must be mono 44.1 kHz and at least 30 seconds")
    dry = sf.read(di, dtype="float32")[0]
    if not np.isfinite(dry).all() or np.max(np.abs(dry)) > 1.0:
        raise ValueError("training DI contains non-finite or out-of-range audio")
    if np.sqrt(np.mean(dry * dry)) < 0.001:
        raise ValueError("training DI is nearly silent")
    dry_native = resample_poly(dry, rate // 300, RATE // 300).astype("float32")
    native = work / "teacher_input.wav"
    sf.write(native, dry_native, rate, subtype="FLOAT")
    teacher_native = work / "teacher_native.wav"
    command = [str(RENDERER)]
    if classify(source)["architecture"] == "SlimmableContainer":
        command += ["--slim", "1.0"]
    command += [str(source), str(native), str(teacher_native)]
    _run(command)
    rendered, rendered_rate = sf.read(teacher_native, dtype="float32")
    if rendered_rate != rate or rendered.ndim != 1 or not np.isfinite(rendered).all():
        raise ValueError("NAM Core teacher produced invalid audio")
    wet = resample_poly(rendered, RATE // 300, rate // 300).astype("float32")
    if len(wet) < len(dry):
        wet = np.pad(wet, (0, len(dry) - len(wet)))
    wet = wet[:len(dry)]
    ir_level = {}
    if ir is not None:
        wet, ir_level = fit_teacher_level(bake(wet, load_ir(ir)))
    if np.sqrt(np.mean(wet * wet)) < 0.001:
        raise ValueError("teacher output is nearly silent")
    allow_float_overs = validate_teacher_level(wet)
    dry_path, wet_path = work / "dry_44100.wav", work / "teacher_44100.wav"
    sf.write(dry_path, dry, RATE, subtype="FLOAT")
    sf.write(wet_path, wet, RATE, subtype="FLOAT")
    return dry_path, wet_path, allow_float_overs, ir_level


def prepare_configs(dry: Path, wet: Path, work: Path, epochs: int) -> tuple[Path, Path, Path]:
    model = json.loads(MODEL_TEMPLATE.read_text(encoding="utf-8"))
    learning = json.loads(LEARNING_TEMPLATE.read_text(encoding="utf-8"))
    learning["trainer"]["accelerator"] = "auto"
    learning["trainer"]["max_epochs"] = epochs
    learning["trainer"]["enable_progress_bar"] = True
    data = {
        "train": {"start_seconds": None, "stop_seconds": -float(VALIDATION_SECONDS), "ny": 8192},
        "validation": {"start_seconds": -float(VALIDATION_SECONDS),
                       "stop_seconds": None, "ny": None,
                       "require_input_pre_silence": None},
        "common": {"x_path": str(dry.resolve()), "y_path": str(wet.resolve()), "delay": 0},
    }
    paths = [work / "data.json", work / "model.json", work / "learning.json"]
    for path, config in zip(paths, (data, model, learning)):
        path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    return tuple(paths)


def quality(student: Path, dry: Path, wet: Path, work: Path) -> dict:
    import numpy as np
    import soundfile as sf

    info = sf.info(dry)
    count = VALIDATION_SECONDS * RATE
    context = 1644
    with sf.SoundFile(dry) as stream:
        stream.seek(info.frames - count - context)
        probe = stream.read(count + context, dtype="float32")
    probe_path = work / "validation_input.wav"
    sf.write(probe_path, probe, RATE, subtype="FLOAT")
    rendered_path = work / "validation_student.wav"
    _run([str(RENDERER), str(student), str(probe_path), str(rendered_path)])
    prediction = sf.read(rendered_path, dtype="float32")[0][-count:].astype("float64")
    with sf.SoundFile(wet) as stream:
        stream.seek(info.frames - count)
        target = stream.read(count, dtype="float32").astype("float64")
    if len(prediction) != count or not np.isfinite(prediction).all():
        raise ValueError("student validation render is invalid")
    if np.max(np.abs(prediction)) >= 8.0:
        raise ValueError("student validation output exceeds the pedal's audio guard")
    error = prediction - target
    denom = float(np.dot(target, target))
    if denom <= 0:
        raise ValueError("teacher validation target is silent")
    return {"esr": float(np.dot(error, error) / denom),
            "rmse": float(np.sqrt(np.mean(error * error))),
            "correlation": float(np.corrcoef(prediction, target)[0, 1]),
            "sample_rate": RATE, "validation_seconds": VALIDATION_SECONDS}


def adapt(source: Path, di: Path, cache: Path, *, epochs: int = 100,
          max_esr: float = 0.05, prepare_only: bool = False,
          best_effort: bool = False, ir: Path | None = None) -> Path:
    source, di, cache = source.resolve(strict=True), di.resolve(strict=True), cache.resolve()
    ir = ir.resolve(strict=True) if ir is not None else None
    if epochs < 1 or epochs > 300 or not 0 < max_esr < 1:
        raise ValueError("epochs must be 1..300 and max ESR must be between 0 and 1")
    decision = classify(source)
    if decision["status"] != "adaptable" and not (ir and decision["status"] == "direct"):
        raise ValueError(f"model is {decision['status']}; adaptation requires an adaptable NAM or cab IR")
    if ir is not None:
        load_ir(ir)
    for dependency in (RENDERER, MODEL_TEMPLATE, LEARNING_TEMPLATE):
        if not dependency.is_file():
            raise FileNotFoundError(f"adaptation dependency is missing: {dependency}")
    cache.mkdir(parents=True, exist_ok=True)
    key = cache_key(source, di, epochs, ir)
    if not prepare_only:
        previous = completed_candidate(cache, key, source, di, epochs, max_esr, ir)
        if previous:
            student, report = previous
            if not best_effort and not meets_quality(report, max_esr):
                raise ValueError("previous adaptation failed the quality gate; "
                                 "enable Best effort to use it")
            index = {"model": str(student.relative_to(cache)),
                     "model_sha256": digest(student), "esr": report["esr"],
                     "correlation": report["correlation"]}
            if "ir_gain_db" in report:
                index["ir_gain_db"] = report["ir_gain_db"]
            tmp = cache / f"{key}.json.tmp"
            tmp.write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")
            atomic_replace(tmp, cache / f"{key}.json")
            print(f"Reusing verified completed adaptation: {student}", flush=True)
            announce_result(student, report, max_esr)
            return student
    ready = cached_model(cache, key, max_esr, best_effort=best_effort)
    if ready:
        print(f"Cached adaptation: {ready}", flush=True)
        record = json.loads((cache / f"{key}.json").read_text(encoding="utf-8"))
        announce_result(ready, record, max_esr)
        return ready
    work = Path(tempfile.mkdtemp(prefix=f"{key[:12]}-", dir=cache))
    print(f"Preparing teacher pair in {work}", flush=True)
    dry, wet, allow_float_overs, ir_level = prepare_pair(
        source, di, work, decision["sample_rate"], ir)
    data, model, learning = prepare_configs(dry, wet, work, epochs)
    if prepare_only:
        print("Prepared only; no training or cache publication", flush=True)
        return work
    train_root = work / "training"
    train_root.mkdir()
    env = os.environ.copy()
    # Small convolutions can spend more time coordinating CPU threads than computing.
    env.setdefault("OMP_NUM_THREADS", "2")
    env.setdefault("MKL_NUM_THREADS", "2")
    env["PYTHONUNBUFFERED"] = "1"
    env["NAM2ZOOM_TEXT_PROGRESS"] = "1"
    env["MPLBACKEND"] = "Agg"
    env["MPLCONFIGDIR"] = str(ROOT / ".tooling" / "nam-mpl-cache")
    if allow_float_overs:
        env["NAM2ZOOM_ALLOW_FLOAT_OVERS"] = "1"
    print("Starting training; CPU thread limits: "
          f"OMP={env['OMP_NUM_THREADS']}, MKL={env['MKL_NUM_THREADS']}. "
          "Initial validation runs before the first training epoch.", flush=True)
    _run([sys.executable, "-m", "nam.cli", str(data), str(model), str(learning),
          str(train_root), "--no-show", "--no-plots"], env=env)
    exports = list(train_root.glob("*/model.nam"))
    if len(exports) != 1:
        raise RuntimeError(f"expected one trained NAM export, found {len(exports)}")
    student = exports[0]
    inspect_compact(json.loads(student.read_text(encoding="utf-8")))
    scores = quality(student, dry, wet, work)
    report = {"source": str(source), "source_sha256": digest(source),
              "training_di_sha256": digest(di), "student": str(student),
              "student_sha256": digest(student),
              "pipeline": IR_PIPELINE_VERSION if ir else PIPELINE_VERSION,
              "epochs": epochs, "max_esr": max_esr, **scores}
    if ir is not None:
        report.update({"ir": str(ir), "ir_sha256": digest(ir), **ir_level})
    (work / "quality.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"Held-out ESR {scores['esr']:.5f}, correlation {scores['correlation']:.4f}", flush=True)
    if not valid_scores(scores):
        raise ValueError("adapted model has invalid quality scores")
    if not best_effort and not meets_quality(scores, max_esr):
        raise ValueError("adapted model failed the quality gate; see quality.json")
    index = {"model": str(student.relative_to(cache)), "model_sha256": digest(student),
             "esr": scores["esr"], "correlation": scores["correlation"]}
    if ir is not None:
        index["ir_gain_db"] = ir_level["ir_gain_db"]
    tmp = cache / f"{key}.json.tmp"
    tmp.write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")
    atomic_replace(tmp, cache / f"{key}.json")
    announce_result(student, report, max_esr)
    print(f"Adapted model ready: {student}", flush=True)
    return student
