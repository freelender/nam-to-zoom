#!/usr/bin/env python3
"""Read-only structural audit of a DIY ZD2/icon against a pedal backup."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
from pathlib import Path
import struct
import subprocess
import sys

from elf32 import ELFError, parse_elf32
from zd2 import ZD2Error, parse_zd2_bytes


CHUNKS = ["ICON", "TXJ1", "TXE1", "INFO", "DATA", "PRMJ", "PRME"]
RELOCATIONS = {1, 9, 10}


def check_zic(data: bytes) -> tuple[bytes | None, list[str]]:
    errors: list[str] = []
    if len(data) < 32 or data[:4] != b"ZBMP":
        return None, ["companion ZIC lacks a complete ZBMP header"]
    descriptor_size = struct.unpack_from("<I", data, 4)[0]
    if descriptor_size != 24:
        return None, [f"ZIC descriptor size is {descriptor_size}, expected 24"]
    dimensions = []
    terminated = False
    for offset in range(8, 32, 4):
        width, height = struct.unpack_from("<HH", data, offset)
        if width == height == 0:
            terminated = True
            if any(data[offset:32]):
                errors.append("ZIC descriptor tail after terminator is nonzero")
            break
        if not width or not height:
            errors.append("ZIC frame has a zero dimension")
            break
        dimensions.append((width, height))
    if not terminated:
        errors.append("ZIC frame table has no zero terminator")
    if dimensions != [(72, 97), (102, 128)]:
        errors.append(f"ZIC frame geometry is {dimensions}, expected two MS Plus frames")
    cursor = 32
    first_bitmap = None
    for index, (width, height) in enumerate(dimensions):
        size = width * ((height + 7) // 8)
        if index == 0:
            first_bitmap = data[cursor : cursor + size]
        cursor += size
    if cursor != len(data):
        errors.append(f"ZIC frame data spans {cursor} bytes, file has {len(data)}")
    return first_bitmap, errors


def audit_bytes(
    zd2_data: bytes, zic_data: bytes, installed: dict[str, int], installed_names: set[str] | None = None
) -> list[str]:
    errors: list[str] = []
    try:
        zd2 = parse_zd2_bytes(zd2_data)
    except ZD2Error as exc:
        return [f"ZD2 parse failed: {exc}"]
    if zd2.length != 120:
        errors.append(f"ZD2 header @4 is {zd2.length}, expected constant 120")
    if not zd2.checksum_valid:
        errors.append("ZD2 checksum is invalid")
    if zd2.target not in (0x80, 0x90):
        errors.append(f"ZD2 target 0x{zd2.target:08x} is not observed on this MS Plus backup")
    if [chunk.tag for chunk in zd2.chunks] != CHUNKS:
        errors.append("ZD2 chunk sequence differs from the reviewed MS Plus corpus")
    if zd2.group != (zd2.effect_id >> 24):
        errors.append("effect ID group byte does not match ZD2 group")
    if not 0x07000F01 <= zd2.effect_id <= 0x07000FEF:
        errors.append(f"effect ID 0x{zd2.effect_id:08x} is outside the DIY SFX range")
    if not zd2.name or len(zd2.name) > 10:
        errors.append("effect name is empty or longer than 10 characters")
    if any(existing_id == zd2.effect_id for existing_id in installed.values()):
        errors.append(f"effect ID 0x{zd2.effect_id:08x} collides with the backup")
    if installed_names and zd2.name.casefold() in installed_names:
        errors.append(f"effect name {zd2.name!r} collides with the backup")
    if zd2.dspload is None or not math.isfinite(zd2.dspload) or not 0 < zd2.dspload <= 270:
        errors.append("INFO DSP load is missing, nonfinite, or outside 0..270")
    if any(zd2.trailer):
        errors.append("ZD2 trailer is not all zero")

    first_bitmap, icon_errors = check_zic(zic_data)
    errors.extend(icon_errors)
    icon_chunk = next((chunk for chunk in zd2.chunks if chunk.tag == "ICON"), None)
    if icon_chunk is None or first_bitmap != icon_chunk.data:
        errors.append("ZD2 ICON does not match the companion ZIC first frame")

    if zd2.data_chunk is None:
        errors.append("ZD2 has no DATA chunk")
        return errors
    try:
        elf = parse_elf32(zd2.data_chunk.data)
    except ELFError as exc:
        errors.append(f"DATA ELF parse failed: {exc}")
        return errors
    if (elf.header.osabi, elf.header.elf_type, elf.header.machine) != (64, 3, 140):
        errors.append("DATA is not a C6000 EABI ET_DYN image")
    if elf.imports:
        errors.append("DATA ELF has unresolved dynamic imports")
    bad_relocations = {item.type for item in elf.relocations} - RELOCATIONS
    if bad_relocations:
        errors.append(f"DATA ELF has unsupported relocations: {sorted(bad_relocations)}")
    executable_loads = [
        program for program in elf.programs
        if program.type == 1 and program.flags & 1
        and program.virtual_address <= elf.header.entry
        < program.virtual_address + program.file_size
    ]
    if not executable_loads:
        errors.append("ELF entry point is not inside an executable load segment")
    return errors


def load_backup(backup: Path) -> tuple[dict[str, int], set[str], Path]:
    manifest_path = backup / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("format") != "nam2zoom.msplus.backup.v1" or manifest.get("complete") is not True:
        raise ValueError("backup manifest has the wrong format or is not marked complete")
    records = manifest.get("patches", []) + manifest.get("files", [])
    if len(manifest.get("patches", [])) != 100 or not manifest.get("files"):
        raise ValueError("backup manifest lacks its expected patches or files")
    backup_root = backup.resolve()
    for item in records:
        path = (backup / item["path"]).resolve()
        if not path.is_relative_to(backup_root):
            raise ValueError(f"backup manifest path escapes its root: {item['path']}")
        data = path.read_bytes()
        if len(data) != item.get("size") or hashlib.sha256(data).hexdigest() != item.get("sha256"):
            raise ValueError(f"backup file is absent or hash-mismatched: {item['path']}")
    flst = backup / "files" / "FLST_SEQ.ZT2"
    flst_entry = next(
        (item for item in manifest.get("files", []) if item.get("path") == "files/FLST_SEQ.ZT2"),
        None,
    )
    if flst_entry is None:
        raise ValueError("backup manifest omits FLST_SEQ.ZT2")
    installed = {}
    installed_names = set()
    for path in (backup / "files").glob("*.ZD2"):
        zd2 = parse_zd2_bytes(path.read_bytes())
        installed[path.name.upper()] = zd2.effect_id
        installed_names.add(zd2.name.casefold())
    if not installed:
        raise ValueError("backup contains no ZD2 files")
    return installed, installed_names, flst


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("effect", type=Path)
    parser.add_argument("--backup", type=Path, default=root / "backups" / "ms50g-plus")
    parser.add_argument("--stomphacks", type=Path, default=root / ".tooling" / "stomphacks")
    args = parser.parse_args()
    icon = args.effect.with_suffix(".ZIC")
    try:
        installed, installed_names, flst = load_backup(args.backup)
        if args.effect.name.upper() in installed:
            raise ValueError(f"filename {args.effect.name} collides with the backup")
        errors = audit_bytes(args.effect.read_bytes(), icon.read_bytes(), installed, installed_names)
    except (OSError, ValueError, ZD2Error, KeyError, TypeError) as exc:
        errors = [str(exc)]
    if errors:
        for error in errors:
            print(f"FAIL {error}")
        return 1

    venv_bin = "Scripts" if platform.system() == "Windows" else "bin"
    venv_python = "python.exe" if platform.system() == "Windows" else "python3"
    python = args.stomphacks / ".venv" / venv_bin / venv_python
    checker = args.stomphacks / "tools" / "flst_check.py"
    if not python.is_file() or not checker.is_file():
        print("FAIL Stomphacks FLST simulation dependencies are unavailable")
        return 1
    print("PASS ZD2, companion icon, ELF, and backup collision checks", flush=True)
    try:
        result = subprocess.run([str(python), str(checker), str(flst), "--simulate-add", str(args.effect)])
    except OSError as exc:
        print(f"FAIL effect-list simulation could not run: {exc}")
        return 1
    if result.returncode:
        print("FAIL offline effect-list simulation")
        return 1
    print("PASS offline audit only; this is not hardware approval")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
