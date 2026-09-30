"""Prepare and build one offline Zoom effect from 1-5 compact NAM models."""

from __future__ import annotations

import hashlib
import json
import platform
import re
import struct
import subprocess
from pathlib import Path

from .compact import expected_parameters, inspect


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "dsp" / "nam_a2_bank_zd2"
KERNEL = ROOT / "dsp" / "nam_a2_compact"
STOMPHACKS = ROOT / ".tooling" / "stomphacks"
TOOLCHAIN = ROOT / ".tooling" / "cgt-8.3.1" / "ti-cgt-c6000_8.3.1"
EFFECT_ID = "07000f87"
FILENAME = "N2ZBANK"
MAX_MODELS = 5
WORDS_PER_MODEL = expected_parameters(3)


def normalize_labels(paths: list[Path], labels: list[str] | None) -> list[str]:
    if labels is not None and len(labels) != len(paths):
        raise ValueError("provide exactly one --label per model, or none")
    if labels is None:
        labels = []
        for index, path in enumerate(paths, 1):
            stem = re.sub(r"[^A-Z0-9]", "", path.stem.upper())
            labels.append((stem[:5] or f"M{index}"))
    if any(not 1 <= len(label) <= 5 or not label.isascii()
           or not all(ch.isalnum() or ch in "-_" for ch in label)
           for label in labels):
        raise ValueError("pedal labels must be 1-5 printable ASCII letters, digits, - or _")
    if len({label.upper() for label in labels}) != len(labels):
        raise ValueError("pedal labels must be unique (use --label to disambiguate)")
    return labels


def load_models(paths: list[Path], labels: list[str] | None = None):
    if not 1 <= len(paths) <= MAX_MODELS:
        raise ValueError("a bank needs 1-5 NAM files")
    names = normalize_labels(paths, labels)
    models = []
    for path, label in zip(paths, names):
        if path.suffix.lower() != ".nam":
            raise ValueError(f"{path}: expected a .nam file")
        if path.stat().st_size > 16 * 1024 * 1024:
            raise ValueError(f"{path}: file exceeds the 16 MiB validation limit")
        raw = path.read_bytes()
        try:
            model = inspect(json.loads(raw.decode("utf-8")))
        except (UnicodeError, json.JSONDecodeError, ValueError, TypeError, KeyError,
                AttributeError, IndexError, OverflowError, struct.error) as exc:
            raise ValueError(f"{path}: unsupported NAM model: {exc}") from exc
        if model.channels != 3 or len(model.weights) != WORDS_PER_MODEL:
            raise ValueError(f"{path}: bank requires the 3-channel compact model")
        models.append((path, label, model.weight_bytes(), hashlib.sha256(raw).hexdigest()))
    return models


def prepare_bank(models, output: Path) -> Path:
    if output.exists():
        raise FileExistsError(f"output already exists: {output}")
    output.mkdir(parents=True)
    for source in (SOURCE / "bank_effect.c", KERNEL / "compact_pair.c",
                   KERNEL / "compact_pair.h", KERNEL / "compact_kernel.h"):
        (output / source.name).write_bytes(source.read_bytes())
    icon_name = "nam_a2_zoom_ms50g_plus.png"
    (output / icon_name).write_bytes((SOURCE / "assets" / icon_name).read_bytes())
    count = len(models)
    selector_labels = [entry[1] for entry in models]
    if count == 1:
        selector_labels.append("EMPTY")
    (output / "bank_config.h").write_text(
        "#ifndef N2Z_BANK_CONFIG_H\n#define N2Z_BANK_CONFIG_H\n"
        + f"#define BANK_MODEL_COUNT {count}u\n"
        + "#define N2Z_OPTIMIZED_KERNEL 1\n"
        + f"#define BANK_SELECTOR_MAX {len(selector_labels) - 1}u\n"
        + f"#define BANK_WORDS_PER_MODEL {WORDS_PER_MODEL}u\n"
        + "#endif\n", encoding="ascii"
    )
    (output / "weights.f32").write_bytes(b"".join(entry[2] for entry in models))
    manifest = {
        "name": "N2Z Bank", "filename": FILENAME, "id": EFFECT_ID,
        "version": "0.01", "display": "N2Z Bank", "badge": "BANK",
        "icon_png": icon_name,
        "description": "Compact NAM bank with two-sample processing.",
        "dspload": 150,
        "kernel": "bank_effect.c", "kernel_section": "text",
        "allow_stack": True, "opt_level": 3, "opt_for_space": None,
        "state_bytes": 128, "scaffold": "cleanroom",
        "const_blob": {
            "symbol": "N2ZBankWeights", "words": count * WORDS_PER_MODEL,
            "init": "weights.f32",
        },
        "params": [
            {"name": "Model", "values": selector_labels, "default": 0,
             "explanation": "Selects the active NAM model."},
            {"name": "Bass", "max": 100, "default": 50,
             "explanation": "Low-frequency tone level; 50 is flat."},
            {"name": "Mid", "max": 100, "default": 50,
             "explanation": "Mid-frequency tone level; 50 is flat."},
            {"name": "Treble", "max": 100, "default": 50,
             "explanation": "High-frequency tone level; 50 is flat."},
            {"name": "Vol", "max": 100, "default": 50,
             "explanation": "Modeled output level; 50 is unity."},
            {"name": "Input", "max": 100, "default": 50,
             "explanation": "Signal level before NAM; 50 is unity."},
            {"name": "Mix", "max": 100, "default": 100,
             "explanation": "Dry/wet balance; 0 is dry and 100 is fully modeled."},
        ],
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="ascii"
    )
    lock = {
        "format": "nam2zoom.compact-bank.v1", "installed": False,
        "note": "Offline build only. Never upload without a new hardware review and approval.",
        "models": [
            {"slot": i, "label": label, "source": str(path.resolve()),
             "source_sha256": source_hash, "weights_sha256": hashlib.sha256(weights).hexdigest()}
            for i, (path, label, weights, source_hash) in enumerate(models)
        ],
    }
    lock["optimized_kernel"] = True
    lock["load_profile"] = "pair-150"
    lock["processing_samples"] = 2
    lock["history_bytes"] = 20076
    (output / "bank.json").write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")
    return output / "manifest.json"


def build_bank(manifest: Path) -> Path:
    templates = ROOT / "release/templates"
    if (templates / "index.json").is_file():
        from .template import fill_template

        return fill_template(templates, manifest)
    if (ROOT / "runtime/portable.marker").exists():
        raise FileNotFoundError("Portable bank templates are missing; extract the complete ZIP again")
    venv_bin = "Scripts" if platform.system() == "Windows" else "bin"
    venv_python = "python.exe" if platform.system() == "Windows" else "python3"
    python = STOMPHACKS / ".venv" / venv_bin / venv_python
    builder = STOMPHACKS / "tools" / "zd2_make_effect.py"
    compiler = TOOLCHAIN / "bin" / "cl6x.exe"
    for dependency in (python, builder, compiler):
        if not dependency.is_file():
            raise FileNotFoundError(f"missing build dependency: {dependency}")
    import os
    env = os.environ.copy()
    env["ZOOM_TI_CGT"] = str(TOOLCHAIN)
    subprocess.run([str(python), str(builder), str(manifest.resolve())],
                   cwd=STOMPHACKS, env=env, check=True)
    effect = manifest.parent / "build" / f"{FILENAME}.ZD2"
    icon = effect.with_suffix(".ZIC")
    if not effect.is_file() or not icon.is_file():
        raise RuntimeError("builder did not produce the ZD2 and ZIC pair")
    return effect
