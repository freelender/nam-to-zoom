"""Wrap an offline timing kit in an existing Windows portable ZIP; no hardware access."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import zipfile


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kit", type=Path)
    parser.add_argument("portable_zip", type=Path)
    parser.add_argument("output_zip", type=Path)
    args = parser.parse_args()
    if args.output_zip.exists():
        parser.error("output already exists")
    metadata = json.loads((args.kit / "timing-kit.json").read_text(encoding="utf-8"))
    files = ["timing-kit.json", "decode_lite_timing.py", "Run.ps1", "README.md"]
    for variant in ("original", "optimized"):
        for extension in ("ZD2", "ZIC"):
            name = f"{variant}/build/N2ZBANK.{extension}"
            if digest(args.kit / name) != metadata["variants"][variant][extension.lower() + "_sha256"]:
                raise ValueError(f"invalid hash: {name}")
            files.append(name)
    with zipfile.ZipFile(args.portable_zip) as source:
        roots = {name.split("/", 1)[0] for name in source.namelist()}
        if len(roots) != 1:
            raise ValueError("portable ZIP must have one root directory")
        root = roots.pop()
        if f"{root}/runtime/python/python.exe" not in source.namelist():
            raise ValueError("Windows Python runtime missing")
        if any("/diagnostics/lite-timing/" in name for name in source.namelist()):
            raise ValueError("source already includes a diagnostic kit")
    shutil.copyfile(args.portable_zip, args.output_zip)
    with zipfile.ZipFile(args.output_zip, "a", compression=zipfile.ZIP_DEFLATED) as target:
        for name in files:
            target.write(args.kit / name, f"{root}/diagnostics/lite-timing/{name}")
        target.writestr(f"{root}/Lite Timing.cmd", '@echo off\r\npowershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0diagnostics\\lite-timing\\Run.ps1"\r\npause\r\n')
    with zipfile.ZipFile(args.output_zip) as result:
        names = result.namelist()
        if len(names) != len(set(names)) or result.testzip() is not None:
            raise ValueError("ZIP validation failed")
        for name in files:
            if result.read(f"{root}/diagnostics/lite-timing/{name}") != (args.kit / name).read_bytes():
                raise ValueError(f"ZIP content differs: {name}")
    checksum = digest(args.output_zip)
    args.output_zip.with_suffix(".zip.sha256").write_text(f"{checksum}  {args.output_zip.name}\n", encoding="ascii")
    print(f"Private diagnostic portable ZIP: {args.output_zip}\nSHA256: {checksum}")


if __name__ == "__main__":
    main()
