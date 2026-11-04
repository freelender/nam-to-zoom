"""Prepare and build one offline Zoom effect from 1-10 NAM models."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import struct
import subprocess
from pathlib import Path

from .compact import expected_parameters, geometry, pair_history_bytes, reserved_dsp_load, inspect, require_enabled_profile
from .platforms import venv_python


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "dsp" / "nam_a2_bank_zd2"
KERNEL = ROOT / "dsp" / "nam_a2_compact"
STOMPHACKS = ROOT / ".tooling" / "stomphacks"
TOOLCHAIN = ROOT / ".tooling" / "cgt-8.3.1" / "ti-cgt-c6000_8.3.1"
EFFECT_ID = "04001787"
FILENAME = "N2ZBANK"
MAX_MODELS = 10
OWN_HOST_DSP_LOAD = 260  # Full: below the 270 boundary; admission metadata, not CPU use.
COMPACT_EFFECT_DSP_LOAD = 190
OWN_HOST_COEFFICIENT_SLOTS = {"Model": 12, "Gain": 13, "Volume": 8, "Mix": 9, "Bass": 5, "Middle": 6, "Treble": 7}

def own_host_dsp_load(compact_effect=False):
    return COMPACT_EFFECT_DSP_LOAD if compact_effect else OWN_HOST_DSP_LOAD


def max_models(profile):
    require_enabled_profile(profile)
    return 5 if profile == "lite" else MAX_MODELS

WORDS_PER_MODEL = expected_parameters(3)


def normalize_labels(paths: list[Path], labels: list[str] | None) -> list[str]:
    if labels is not None and len(labels) != len(paths):
        raise ValueError("provide exactly one --label per model, or none")
    if labels is None:
        labels = []
        for index, path in enumerate(paths, 1):
            stem = re.sub(r"[^A-Z0-9]", "", path.stem.upper())
            labels.append((stem[:6] or f"M{index}"))
    if any(not 1 <= len(label) <= 6 or not label.isascii()
           or not all(ch.isalnum() or ch in "-_" for ch in label)
           for label in labels):
        raise ValueError("pedal labels must be 1-6 printable ASCII letters, digits, - or _")
    if len({label.upper() for label in labels}) != len(labels):
        raise ValueError("pedal labels must be unique (use --label to disambiguate)")
    return labels


def load_models(paths: list[Path], labels: list[str] | None = None, *, profile="compact"):
    words = expected_parameters(3, profile)
    if not 1 <= len(paths) <= max_models(profile):
        raise ValueError(f"a {profile} bank needs 1-{max_models(profile)} NAM files")
    names = normalize_labels(paths, labels)
    models = []
    for path, label in zip(paths, names):
        if path.suffix.lower() != ".nam":
            raise ValueError(f"{path}: expected a .nam file")
        if path.stat().st_size > 16 * 1024 * 1024:
            raise ValueError(f"{path}: file exceeds the 16 MiB validation limit")
        raw = path.read_bytes()
        try:
            model = inspect(json.loads(raw.decode("utf-8")), profile)
        except (UnicodeError, json.JSONDecodeError, ValueError, TypeError, KeyError,
                AttributeError, IndexError, OverflowError, struct.error) as exc:
            raise ValueError(f"{path}: unsupported NAM model: {exc}") from exc
        if model.channels != 3 or len(model.weights) != words:
            raise ValueError(f"{path}: bank requires the 3-channel {profile} model")
        models.append((path, label, model.weight_bytes(), hashlib.sha256(raw).hexdigest()))
    return models


def prepare_bank(models, output: Path, *, profile="compact", own_host=False, compact_effect=False) -> Path:
    words = expected_parameters(3, profile)
    if compact_effect and not own_host:
        raise ValueError("Compact effect mode requires the full Lite owned host")
    dsp_load = own_host_dsp_load(compact_effect) if own_host else reserved_dsp_load(profile)
    if not 1 <= len(models) <= max_models(profile):
        raise ValueError(f"a {profile} bank needs 1-{max_models(profile)} NAM files")
    if any(len(row[2]) != words * 4 for row in models):
        raise ValueError(f"bank weights do not match {profile}")
    kernel = KERNEL if profile == "compact" else ROOT / "dsp/nam_a2_lite"
    if output.exists():
        raise FileExistsError(f"output already exists: {output}")
    output.mkdir(parents=True)
    for source in (SOURCE / "bank_effect.c", kernel / "compact_pair.c",
                   kernel / "compact_pair.h", kernel / "compact_kernel.h"):
        shutil.copyfile(source, output / source.name)
    if own_host:
        if profile != "lite":
            raise ValueError("the owned host accepts full Lite models only")
        shutil.copyfile(ROOT / "dsp/nam_a2_own_host/host.c", output / "bank_effect.c")
        shutil.copyfile(ROOT / "dsp/nam_a2_own_host" / ("compact_block.c" if compact_effect else "block4.c"), output / "compact_pair.c")
        shutil.copyfile(ROOT / "dsp/nam_a2_own_host/block4.h", output / "compact_pair.h")
        for name in ("compact_runtime.h", "compact_filters.h"):
            shutil.copyfile(ROOT / "dsp/nam_a2_own_host" / name, output / name)
    icon_name = "nam_a2_amp_readable.png"
    shutil.copyfile(SOURCE / "assets" / icon_name, output / icon_name)
    count = len(models)
    selector_labels = [entry[1] for entry in models]
    if count == 1:
        selector_labels.append("EMPTY")
    (output / "bank_config.h").write_text(
        "#ifndef N2Z_BANK_CONFIG_H\n#define N2Z_BANK_CONFIG_H\n"
        + f"#define BANK_MODEL_COUNT {count}u\n"
        + "#define N2Z_OPTIMIZED_KERNEL 1\n"
        + f"#define BANK_SELECTOR_MAX {len(selector_labels) - 1}u\n"
        + f"#define BANK_WORDS_PER_MODEL {words}u\n"
        + "#endif\n", encoding="ascii"
    )
    (output / "weights.f32").write_bytes(b"".join(entry[2] for entry in models))
    manifest = {
        "name": "N2Z Bank", "filename": FILENAME, "id": EFFECT_ID,
        # The upstream numeric cutoff predates the local PREAMP NAM range.
        "allow_any_id": True,
        "version": "0.01", "display": "N2Z Bank", "badge": "BANK",
        "icon_png": icon_name,
        "icon_frames": [[97, 97], [128, 128]],
        "icon_trim": True,
        "icon_stock_knobs": True,
        "description": f"{profile.capitalize()} NAM bank with two-sample processing.",
        "dspload": dsp_load,
        "kernel": "bank_effect.c", "kernel_section": "text",
        "allow_stack": True, "opt_level": 3, "opt_for_space": None,
        "state_bytes": 128, "scaffold": "cleanroom",
        "const_blob": {
            "symbol": "N2ZBankWeights", "words": count * words,
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
    if own_host:
        if compact_effect:
            manifest["kernel_cflags"] = ["--define=N2Z_COMPACT_EFFECT=1"]
        manifest["description"] = "Full A2 Lite 44.1 kHz NAM: Model/Gain/Volume/Mix, then Bass/Middle/Treble."
        original = {p["name"]:dict(p) for p in manifest["params"]}
        original["Gain"] = dict(original["Input"], name="Gain",
                                explanation="Input drive before NAM; 50 is unity, 0 is zero input and 100 is twice unity.")
        original["Volume"] = dict(original["Vol"], name="Volume")
        original["Middle"] = dict(original["Mid"], name="Middle")
        manifest["params"] = [original[name] for name in OWN_HOST_COEFFICIENT_SLOTS]
        for param in manifest["params"]:
            param["slot"] = OWN_HOST_COEFFICIENT_SLOTS[param["name"]]
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
    lock["load_profile"] = f"{'block16' if own_host else 'pair'}-{dsp_load}"
    lock["reserved_dsp_load"] = dsp_load
    lock["processing_samples"] = 16 if own_host else 2
    lock["model_profile"] = profile
    if own_host:
        lock["control_layout"] = "nam2zoom-seven-v1"
        lock["effect_mode"] = "compact" if compact_effect else "full"
        lock["processing_samples"] = 12 if compact_effect else 16
    lock["hardware_status"] = "experimental" if profile == "lite" else "tested"
    lock["history_bytes"] = ((20118 + 356) if compact_effect else 20406) * 4 if own_host else pair_history_bytes(profile)
    lock["network_layers"] = len(geometry(profile)[0])
    lock["weights_per_model"] = words
    (output / "bank.json").write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")
    return output / "manifest.json"


def build_bank(manifest: Path, *, force_compile=False) -> Path:
    lock = json.loads((manifest.parent / "bank.json").read_text())
    profile = lock.get("model_profile", "compact")
    require_enabled_profile(profile)
    templates = ROOT / "release/templates"
    if profile == "lite":
        templates = ROOT / "release/templates-lite"
    if lock.get("control_layout") == "nam2zoom-seven-v1":
        folder = "own-lite-compact" if lock.get("effect_mode") == "compact" else "own-lite"
        templates = ROOT / "release" / ("templates-" + folder)
        if not (templates / "index.json").is_file() and not (ROOT / "runtime/portable.marker").exists():
            templates = ROOT / "release/precompiled" / folder
    if not force_compile and (templates / "index.json").is_file():
        from .template import fill_template

        return fill_template(templates, manifest)
    if (ROOT / "runtime/portable.marker").exists():
        raise FileNotFoundError("Portable bank templates are missing; extract the complete ZIP again")
    python = venv_python(STOMPHACKS / ".venv")
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
    if lock.get("control_layout") == "nam2zoom-seven-v1" and lock.get("effect_mode") == "compact":
        from .artwork import stamp_compact_artwork
        stamp_compact_artwork(effect)
    return effect
