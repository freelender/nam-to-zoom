"""Bake the Compact label into validated templates without recompiling DSP."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from nam2zoom.artwork import COMPACT_ARTWORK, stamp_compact_artwork


def main():
    folder = ROOT / "release/precompiled/own-lite-compact"
    index = json.loads((folder / "index.json").read_text())
    assert index["effect_mode"] == "compact"
    icon = (folder / "N2ZBANK.ZIC").read_bytes()
    assert hashlib.sha256(icon).hexdigest() == index["icon_sha256"]
    updated = {}
    with tempfile.TemporaryDirectory() as temporary:
        effect = Path(temporary) / "N2ZBANK.ZD2"
        for count, record in index["banks"].items():
            raw = (folder / f"bank-{count}.ZD2").read_bytes()
            assert hashlib.sha256(raw).hexdigest() == record["sha256"]
            effect.write_bytes(raw)
            effect.with_suffix(".ZIC").write_bytes(icon)
            stamp_compact_artwork(effect)
            updated[count] = effect.read_bytes()
            new_icon = effect.with_suffix(".ZIC").read_bytes()
    for count, raw in updated.items():
        (folder / f"bank-{count}.ZD2").write_bytes(raw)
        index["banks"][count]["sha256"] = hashlib.sha256(raw).hexdigest()
    (folder / "N2ZBANK.ZIC").write_bytes(new_icon)
    index["icon_sha256"] = hashlib.sha256(new_icon).hexdigest()
    index["artwork_variant"] = COMPACT_ARTWORK
    (folder / "index.json").write_text(json.dumps(index, indent=2) + "\n", encoding="ascii")
    print("Compact label added to all three templates; DSP source/code unchanged.")


if __name__ == "__main__":
    main()
