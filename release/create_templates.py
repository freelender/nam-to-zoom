"""Release-maintainer command: compile zero-weight templates with the developer toolchain."""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from elf32 import parse_elf32
from zd2 import parse_zd2_bytes
from nam2zoom.bank import build_bank, prepare_bank, max_models
from nam2zoom.compact import expected_parameters, reserved_dsp_load
from nam2zoom.template import sources, digest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--profile", choices=("compact", "lite"), default="compact")
    args = parser.parse_args()
    words = expected_parameters(3, args.profile)
    if (ROOT / ("release/templates-lite/index.json" if args.profile == "lite" else "release/templates/index.json")).exists():
        parser.error("remove the generated release/templates cache before compiling new templates")
    args.output.mkdir(parents=True, exist_ok=False)
    args.work.mkdir(parents=True, exist_ok=False)
    index = {"format": "nam2zoom.templates.v1", "banks": {},
             "model_profile": args.profile,
             "reserved_dsp_load": reserved_dsp_load(args.profile),
             "dsp_source_sha256": {name: digest((ROOT / name).read_bytes()) for name in sources(args.profile)}}
    for count in range(1, max_models(args.profile) + 1):
        models = [(ROOT / "release/create_templates.py", f"SLT{i+1}",
                   bytes(words * 4), "zero-weight-release-template")
                  for i in range(count)]
        manifest = prepare_bank(models, args.work / str(count), profile=args.profile)
        effect = build_bank(manifest)
        zd2 = parse_zd2_bytes(effect.read_bytes())
        stripped = parse_elf32(zd2.data_chunk.data)
        unstripped = parse_elf32((effect.parent / "N2ZBANK.out").read_bytes())
        symbols = {s.name: s for s in unstripped.symbols}
        const = next(s for s in stripped.sections if s.name == ".const")
        offsets = {}
        for key, name in (("weights_offset", "N2ZBankWeights"), ("labels_offset", "Aw_P2_tab")):
            relative = symbols[name].value - const.address
            if not 0 <= relative < const.size:
                raise ValueError(f"{name} is not in .const")
            offsets[key] = zd2.data_chunk.offset + 8 + const.offset + relative
        index["banks"][str(count)] = {"sha256": hashlib.sha256(zd2.data).hexdigest(), **offsets}
        shutil.copyfile(effect, args.output / f"bank-{count}.ZD2")
        icon = effect.with_suffix(".ZIC").read_bytes()
        icon_hash = hashlib.sha256(icon).hexdigest()
        if "icon_sha256" in index and index["icon_sha256"] != icon_hash:
            raise ValueError("template icons differ")
        index["icon_sha256"] = icon_hash
        (args.output / "N2ZBANK.ZIC").write_bytes(icon)
    (args.output / "index.json").write_text(json.dumps(index, indent=2) + "\n", encoding="ascii")


if __name__ == "__main__":
    main()
