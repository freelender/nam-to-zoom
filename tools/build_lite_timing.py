"""Developer-only: build two private, temporary Lite timing effects (no USB writes)."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from nam2zoom.bank import load_models, prepare_bank, STOMPHACKS, TOOLCHAIN
from nam2zoom.platforms import venv_python


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model", type=Path, help="already converted three-channel Lite NAM")
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    models = load_models([args.model], ["TIME"], profile="lite")
    model_hash = hashlib.sha256(models[0][2]).hexdigest()
    report = {"format": "nam2zoom.lite-timing.v1", "private_model_weights": True,
              "weights_sha256": model_hash, "installed": False, "variants": {}}
    env = os.environ.copy()
    env["ZOOM_TI_CGT"] = str(TOOLCHAIN)
    for index, name in enumerate(("original", "optimized")):
        manifest_path = prepare_bank(models, output / name, profile="lite")
        directory = manifest_path.parent
        kernel = "lite_pair_original.c" if index == 0 else "lite_pair_shared_load_experiment.c"
        shutil.copyfile(ROOT / "tests/fixtures" / kernel, directory / "compact_pair.c")
        shutil.copyfile(ROOT / "dsp/nam_a2_bank_zd2/timing_effect.c", directory / "timing_effect.c")
        (directory / "timing_config.h").write_text(
            f"#define N2Z_TIMING_VARIANT {index}u\n#define N2Z_TIMING_MODEL_TAG 0x{model_hash[:8]}u\n",
            encoding="ascii")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest.update(kernel="timing_effect.c", state_bytes=184,
                        description=f"Temporary {name} Lite timing diagnostic. Never save a patch.")
        manifest["params"][0]["values"][0] = "ORIG" if index == 0 else "OPT"
        manifest["kernel_cflags"] = ["--keep_asm", f"--asm_directory={directory / 'build'}"]
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="ascii")
        subprocess.run([str(venv_python(STOMPHACKS / ".venv")),
                        str(STOMPHACKS / "tools/zd2_make_effect.py"), str(manifest_path)],
                       cwd=STOMPHACKS, env=env, check=True)
        hashes = {}
        for suffix in ("ZD2", "ZIC"):
            artifact = directory / "build" / f"N2ZBANK.{suffix}"
            hashes[suffix.lower() + "_sha256"] = hashlib.sha256(artifact.read_bytes()).hexdigest()
        # Refuse a target that lost its counter reads or writes the counter.
        listing = (directory / "build/timing_effect.asm").read_text(encoding="utf-8")
        instructions = [line.split(";", 1)[0] for line in listing.splitlines()]
        counter = [line for line in instructions if "TSCL" in line]
        if not counter or any("TSCL," not in line for line in counter):
            raise RuntimeError(f"unexpected TSCL instructions: {counter}")
        report["variants"][name] = hashes
    (output / "timing-kit.json").write_text(json.dumps(report, indent=2) + "\n", encoding="ascii")
    shutil.copyfile(ROOT / "tools/decode_lite_timing.py", output / "decode_lite_timing.py")
    shutil.copyfile(ROOT / "release/lite-timing/Run.ps1", output / "Run.ps1")
    shutil.copyfile(ROOT / "docs/LITE_TIMING.md", output / "README.md")
    print(f"Private diagnostic kit built offline: {output}")


if __name__ == "__main__":
    main()
