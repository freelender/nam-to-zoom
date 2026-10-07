"""Classify NAM imports for the direct or PC-adapted compact-bank path."""

from __future__ import annotations

import json
from pathlib import Path

from .compact import geometry, inspect as inspect_compact


RENDERABLE = {"WaveNet", "LSTM", "Linear", "Sequential", "SlimmableContainer"}


def classify(path: Path, profile="compact") -> dict:
    geometry(profile)
    if path.suffix.lower() != ".nam":
        raise ValueError("expected a .nam file")
    if path.stat().st_size > 64 * 1024 * 1024:
        raise ValueError("NAM file exceeds the 64 MiB import limit")
    try:
        model = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid NAM JSON: {exc}") from exc
    if not isinstance(model, dict):
        raise ValueError("NAM root must be an object")
    architecture = model.get("architecture")
    rate = model.get("sample_rate", 48000)
    if not isinstance(rate, (int, float)) or rate not in (44100, 48000):
        return {"status": "unsupported", "architecture": architecture,
                "sample_rate": rate, "reason": "only 44.1 and 48 kHz imports are supported"}
    try:
        compact = inspect_compact(model, profile)
        if compact.channels == 3:
            return {"status": "direct", "architecture": architecture,
                    "sample_rate": int(rate), "reason": f"{profile} bank shape", "model_profile": profile}
    except (ValueError, TypeError, KeyError, AttributeError, IndexError):
        pass
    if architecture not in RENDERABLE:
        return {"status": "unsupported", "architecture": architecture,
                "sample_rate": int(rate), "reason": "NAM Core renderer does not support this architecture"}
    return {"status": "adaptable", "architecture": architecture,
            "sample_rate": int(rate), "reason": "needs PC rendering and quality-gated training"}
