#!/usr/bin/env python3
"""Read-only command line access to supported Zoom MS Plus pedals."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

from atomic_replace import atomic_replace
from msplus_midi import (
    MidiTimeout,
    MidiUnavailable,
    ReadOnlyMSPlus,
    list_ports,
    open_default_device,
)
from msplus_protocol import MS_PLUS_DEVICE, ProtocolError
from nam2zoom.devices import require_supported_device


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Read-only Zoom MS Plus identification and backup tool"
    )
    parser.add_argument("--input", help="exact MIDI input port name")
    parser.add_argument("--output", help="exact MIDI output port name")
    parser.add_argument("--port-index", type=int, default=0, help="matching Zoom port index")
    parser.add_argument("--timeout", type=float, default=2.0, help="response timeout in seconds")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("ports", help="list MIDI input and output ports")
    subparsers.add_parser("identify", help="request the device identity")
    subparsers.add_parser("patch-info", help="show patch count and size")

    patch = subparsers.add_parser("download-patch", help="download one patch")
    patch.add_argument("location", type=int, help="one-based patch location")
    patch.add_argument("destination", type=Path)

    subparsers.add_parser("list-files", help="list device files")
    device_file = subparsers.add_parser("download-file", help="download one device file")
    device_file.add_argument("filename")
    device_file.add_argument("destination", type=Path)

    backup = subparsers.add_parser(
        "backup", help="download every patch and file into a new directory"
    )
    backup.add_argument("destination", type=Path)
    backup.add_argument(
        "--resume",
        action="store_true",
        help="verify and continue an incomplete backup directory",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "ports":
            return show_ports()
        with open_default_device(
            args.input, args.output, args.port_index, args.timeout
        ) as transport:
            with ReadOnlyMSPlus(transport) as pedal:
                return run_command(args, pedal)
    except (MidiTimeout, MidiUnavailable, ProtocolError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


def show_ports() -> int:
    inputs, outputs = list_ports()
    print("MIDI inputs:")
    for index, name in enumerate(inputs):
        print(f"  [{index}] {name}")
    print("MIDI outputs:")
    for index, name in enumerate(outputs):
        print(f"  [{index}] {name}")
    return 0


def run_command(args: argparse.Namespace, pedal: ReadOnlyMSPlus) -> int:
    if args.command == "identify":
        identity = pedal.identify()
        print_identity(identity)
        return 0

    identity = pedal.identify()
    _require_supported(identity)
    pedal.enable_pc_mode()

    if args.command == "patch-info":
        info = pedal.patch_info()
        print(f"Patches: {info.count}")
        print(f"Patch size: {info.patch_size} bytes")
        print(f"Patches per bank: {info.patches_per_bank}")
    elif args.command == "download-patch":
        _refuse_existing(args.destination)
        info = pedal.patch_info()
        block = pedal.download_patch(args.location, info)
        args.destination.write_bytes(block.data)
        print(f"Wrote {len(block.data)} bytes to {args.destination}")
    elif args.command == "list-files":
        for name in pedal.list_files():
            print(name)
    elif args.command == "download-file":
        _refuse_existing(args.destination)
        data = pedal.download_file(args.filename)
        args.destination.write_bytes(data)
        print(f"Wrote {len(data)} bytes to {args.destination}")
    elif args.command == "backup":
        backup_device(pedal, identity, args.destination, resume=args.resume)
    return 0


def backup_device(
    pedal: ReadOnlyMSPlus, identity, destination: Path, resume: bool = False
) -> None:
    manifest_path = destination / "manifest.json"
    if resume:
        manifest = _load_resume_manifest(manifest_path, identity)
        if manifest.get("complete"):
            print(f"Backup is already complete: {destination}")
            return
    else:
        if destination.exists():
            raise FileExistsError(f"Backup destination already exists: {destination}")
        manifest = {
            "format": "nam2zoom.msplus.backup.v1",
            "complete": False,
            "identity": _identity_record(identity),
            "patches": [],
            "files": [],
        }

    patches_dir = destination / "patches"
    files_dir = destination / "files"
    patches_dir.mkdir(parents=True, exist_ok=resume)
    files_dir.mkdir(exist_ok=resume)
    manifest["complete"] = False
    _write_manifest(manifest_path, manifest)

    info = pedal.patch_info()
    patch_info_record = {
        "count": info.count,
        "patch_size": info.patch_size,
        "patches_per_bank": info.patches_per_bank,
    }
    previous_patch_info = manifest.get("patch_info")
    if previous_patch_info is not None and previous_patch_info != patch_info_record:
        raise ProtocolError("Pedal patch layout differs from the incomplete backup")
    manifest["patch_info"] = patch_info_record

    patch_records = _records_by_key(manifest["patches"], "location")
    for location in range(1, info.count + 1):
        relative = Path("patches") / f"{location:03d}.zptc"
        previous = patch_records.get(location)
        if previous is not None:
            _require_valid_record(destination, relative, previous)
            print(f"Patch {location}/{info.count}: already verified")
            continue
        data = pedal.download_patch(location, info).data
        (destination / relative).write_bytes(data)
        manifest["patches"].append(_file_record(relative, data, location=location))
        _write_manifest(manifest_path, manifest)
        print(f"Patch {location}/{info.count}: {len(data)} bytes")

    names = pedal.list_files()
    file_records = _records_by_key(manifest["files"], "device_name")
    missing_names = set(file_records) - set(names)
    if missing_names:
        raise ProtocolError(
            "Pedal file listing differs from the incomplete backup; missing: "
            + ", ".join(sorted(missing_names))
        )
    local_names: set[str] = set()
    for index, name in enumerate(names, start=1):
        safe_name = _safe_device_filename(name)
        folded_name = safe_name.casefold()
        if folded_name in local_names:
            raise ProtocolError(
                f"Device filenames collide on this filesystem: {safe_name!r}"
            )
        local_names.add(folded_name)
        relative = Path("files") / safe_name
        previous = file_records.get(name)
        if previous is not None:
            _require_valid_record(destination, relative, previous)
            print(f"File {index}/{len(names)}: {name} (already verified)")
            continue
        data = pedal.download_file(name)
        (destination / relative).write_bytes(data)
        manifest["files"].append(_file_record(relative, data, device_name=name))
        _write_manifest(manifest_path, manifest)
        print(f"File {index}/{len(names)}: {name} ({len(data)} bytes)")

    manifest["complete"] = True
    _write_manifest(manifest_path, manifest)
    print(f"Backup complete: {destination}")


def print_identity(identity) -> None:
    print(f"Device ID: 0x{identity.device_id:02x}")
    print(f"Family: 0x{identity.family_code:04x}")
    print(f"Model: 0x{identity.model_number:04x}")
    print(f"Version: {identity.version}")


def _require_supported(identity) -> None:
    if identity.family_code != MS_PLUS_DEVICE:
        raise ProtocolError(
            f"Refusing MS Plus commands for identity family 0x{identity.family_code:04x}"
        )
    try:
        require_supported_device(
            identity.family_code, identity.model_number, identity.version
        )
    except ValueError as exc:
        raise ProtocolError(str(exc)) from exc


def _refuse_existing(path: Path) -> None:
    if path.exists():
        raise FileExistsError(f"Refusing to overwrite existing path: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)


def _safe_device_filename(name: str) -> str:
    if Path(name).name != name or name in {".", ".."} or not name:
        raise ProtocolError(f"Unsafe filename returned by pedal: {name!r}")
    return name


def _identity_record(identity) -> dict[str, Any]:
    return {
        "device_id": identity.device_id,
        "family_code": identity.family_code,
        "model_number": identity.model_number,
        "version": identity.version,
    }


def _load_resume_manifest(path: Path, identity) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"Incomplete backup manifest not found: {path}")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("format") != "nam2zoom.msplus.backup.v1":
        raise ProtocolError("Backup manifest has an unsupported format")
    if manifest.get("identity") != _identity_record(identity):
        raise ProtocolError("Connected pedal identity differs from the backup manifest")
    if not isinstance(manifest.get("patches"), list) or not isinstance(
        manifest.get("files"), list
    ):
        raise ProtocolError("Backup manifest has invalid patch or file records")
    return manifest


def _records_by_key(records: list[dict[str, Any]], key: str) -> dict[Any, dict[str, Any]]:
    result: dict[Any, dict[str, Any]] = {}
    for record in records:
        value = record.get(key)
        if value in result:
            raise ProtocolError(f"Backup manifest repeats {key} {value!r}")
        result[value] = record
    return result


def _require_valid_record(
    root: Path, expected_relative: Path, record: dict[str, Any]
) -> None:
    if record.get("path") != expected_relative.as_posix():
        raise ProtocolError(
            f"Unexpected path in backup manifest: {record.get('path')!r}"
        )
    path = root / expected_relative
    if not path.is_file():
        raise ProtocolError(f"Backup file is missing: {path}")
    data = path.read_bytes()
    if record.get("size") != len(data) or record.get("sha256") != hashlib.sha256(
        data
    ).hexdigest():
        raise ProtocolError(f"Backup file failed manifest verification: {path}")


def _file_record(path: Path, data: bytes, **extra: Any) -> dict[str, Any]:
    return {
        **extra,
        "path": path.as_posix(),
        "size": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def _write_manifest(path: Path, manifest: dict[str, Any]) -> None:
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    atomic_replace(temporary, path)


if __name__ == "__main__":
    raise SystemExit(main())
