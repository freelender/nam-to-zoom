"""Guarded MS Plus bank replacement through the Stomphacks DIY installer."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import re

from .devices import DeviceProfile, require_supported_device


ROOT = Path(__file__).resolve().parents[2]
STOMP = ROOT / ".tooling/stomphacks"
BANK_NAME = "N2ZBANK.ZD2"
BANK_ICON = "N2ZBANK.ZIC"
BANK_ID = 0x07000F87


class DeployError(RuntimeError):
    pass


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        sha = hashlib.sha256()
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            sha.update(block)
    return sha.hexdigest()


def verify_approved(effect: Path, icon: Path, effect_hash: str, icon_hash: str) -> None:
    for path, expected in ((effect, effect_hash), (icon, icon_hash)):
        if digest(path) != expected.lower():
            raise DeployError(f"approved SHA-256 no longer matches {path}")


def _run(args: list[str], *, capture: bool = False, expected: int = 0) -> str:
    print("Running:", Path(args[2]).name, " ".join(args[3:6]), flush=True)
    result = subprocess.run(args, cwd=ROOT, text=True,
                            capture_output=capture, check=False)
    if capture:
        print(result.stdout, end="", flush=True)
        if result.stderr:
            print(result.stderr, end="", file=sys.stderr, flush=True)
    if result.returncode != expected:
        print("PEDAL COMMAND FAILED. Keep the pedal powered and connected until "
              "its file-session and effect list are verified. If the tool printed "
              "DO-NOT-POWER-CYCLE, follow Stomphacks SAFETY.md rescue steps.",
              file=sys.stderr, flush=True)
        raise DeployError(f"{Path(args[1]).name} exited {result.returncode} "
                          f"(expected {expected}); no further writes attempted")
    return result.stdout if capture else ""


def _python(script: Path, *args: str) -> list[str]:
    return [sys.executable, "-u", str(script), *args]


def _tool(name: str, *args: str, capture: bool = False,
          expected: int = 0) -> str:
    script = STOMP / "tools-pedal" / name
    return _run(_python(script, *args), capture=capture, expected=expected)


def _download(name: str, output: Path) -> None:
    _run(_python(ROOT / "tools/msplus.py", "--timeout", "5", "download-file",
                 name, str(output)))


def _flst():
    sys.path.insert(0, str(STOMP / "tools"))
    import flst_check
    return flst_check


def patch_ids(path: Path) -> set[int]:
    sys.path.insert(0, str(STOMP / "zoom-zt2"))
    from decode_preset import ZPTC
    try:
        patch = ZPTC.parse(path.read_bytes())
    except Exception as exc:
        raise DeployError(f"cannot parse pedal patch {path}: {exc}") from exc
    return set(patch.ids)


def require_stock_patch(path: Path) -> None:
    sys.path.insert(0, str(STOMP / "tools-pedal"))
    from stock_catalog import STOCK_IDS
    allowed = STOCK_IDS | {0}
    unknown = patch_ids(path) - allowed
    if unknown:
        raise DeployError(f"{path.name} contains a non-stock effect ID "
                          f"({', '.join(hex(i) for i in sorted(unknown))}); "
                          "select/save stock-only patches before installing")


def require_stock_patches(current: Path, backup: Path, expected_count: int) -> None:
    require_stock_patch(current)
    patches = sorted((backup / "patches").glob("*.zptc"))
    if len(patches) != expected_count:
        raise DeployError(
            f"backup does not contain exactly {expected_count} saved patches"
        )
    for path in patches:
        require_stock_patch(path)


def _profile(family_code: object, model_number: object, version: object) -> DeviceProfile:
    if not isinstance(family_code, int) or not isinstance(model_number, int) \
            or not isinstance(version, str):
        raise DeployError("pedal identity is incomplete or malformed")
    try:
        return require_supported_device(family_code, model_number, version)
    except ValueError as exc:
        raise DeployError(str(exc)) from exc


def _profile_from_identify(output: str) -> DeviceProfile:
    fields = {}
    for name in ("Family", "Model"):
        match = re.search(rf"^{name}: 0x([0-9a-f]+)\s*$", output, re.I | re.M)
        if match is None:
            raise DeployError(f"pedal identity response lacks {name.lower()}")
        fields[name] = int(match.group(1), 16)
    version = re.search(r"^Version: ([!-~]+)\s*$", output, re.M)
    if version is None:
        raise DeployError("pedal identity response lacks firmware version")
    return _profile(fields["Family"], fields["Model"], version.group(1))


def plan_backup(effect: Path | None, icon: Path | None,
                backup: Path, current: Path) -> bool:
    sys.path.insert(0, str(ROOT / "tools"))
    from offline_effect_audit import audit_bytes, load_backup
    from zd2 import parse_zd2_bytes

    if effect is not None:
        candidate = parse_zd2_bytes(effect.read_bytes())
        if candidate.effect_id != BANK_ID or candidate.name != "N2Z Bank":
            raise DeployError("new N2ZBANK file has an unexpected effect ID or name")
    manifest = json.loads((backup / "manifest.json").read_text(encoding="utf-8"))
    identity = manifest.get("identity", {})
    profile = _profile(
        identity.get("family_code"), identity.get("model_number"),
        identity.get("version")
    )
    print(f"Detected {profile.name} firmware {profile.firmware}.", flush=True)
    installed, names, flst_path = load_backup(backup)
    require_stock_patches(current, backup, profile.patch_count)
    legacy = sorted(name for name in installed if name.startswith("N2Z")
                    and name != BANK_NAME)
    if legacy:
        raise DeployError(f"another NAM2Zoom effect is installed: {legacy}; "
                          "remove it separately before installing N2Z Bank")
    existing = BANK_NAME in installed
    if (backup / "files" / BANK_ICON).exists() != existing:
        raise DeployError("existing N2Z Bank binary/icon pair is incomplete")
    if existing:
        old = parse_zd2_bytes((backup / "files" / BANK_NAME).read_bytes())
        if old.effect_id != BANK_ID or old.name != "N2Z Bank":
            raise DeployError("existing N2ZBANK filename has an unexpected identity")
    flst = _flst()
    old_list = flst_path.read_bytes()
    valid, problems, _ = flst.validate_flst(old_list)
    if not valid:
        raise DeployError(f"backed-up effect list is invalid: {problems}")
    count = sum(entry[1] == BANK_NAME for entry in flst.parse_entries(old_list))
    if count != int(existing):
        raise DeployError("bank files and effect-list entry disagree")
    if effect is not None:
        installed.pop(BANK_NAME, None)
        names.discard("n2z bank")
        problems = audit_bytes(effect.read_bytes(), icon.read_bytes(), installed, names)
        if problems:
            raise DeployError("new bank failed offline audit: " + "; ".join(problems))
    return existing


def plan_live(effect: Path | None, icon: Path | None,
              session: Path, current: Path) -> tuple[bool, Path]:
    """Check live catalog and patches without making a full device backup."""
    sys.path.insert(0, str(ROOT / "tools"))
    from offline_effect_audit import audit_bytes
    from zd2 import parse_zd2_bytes

    if effect is not None:
        candidate = parse_zd2_bytes(effect.read_bytes())
        if candidate.effect_id != BANK_ID or candidate.name != "N2Z Bank":
            raise DeployError("new N2ZBANK file has an unexpected effect ID or name")
    identify = _run(_python(ROOT / "tools/msplus.py", "--timeout", "5", "identify"),
                    capture=True)
    profile = _profile_from_identify(identify)
    print(f"Detected {profile.name} firmware {profile.firmware}.", flush=True)
    info = _run(_python(ROOT / "tools/msplus.py", "--timeout", "5", "patch-info"),
                capture=True)
    if not re.search(rf"^Patches: {profile.patch_count}\s*$", info, re.M):
        raise DeployError(
            f"{profile.name} does not report exactly {profile.patch_count} saved patches"
        )
    require_stock_patch(current)
    with tempfile.TemporaryDirectory(prefix="patch-check-", dir=session) as temporary:
        for location in range(1, profile.patch_count + 1):
            path = Path(temporary) / f"{location:03d}.zptc"
            _run(_python(ROOT / "tools/msplus.py", "--timeout", "5",
                         "download-patch", str(location), str(path)))
            require_stock_patch(path)
    listing = _run(_python(ROOT / "tools/msplus.py", "--timeout", "5", "list-files"),
                   capture=True)
    files = set(listing.splitlines())
    if "FLST_SEQ.ZT2" not in files:
        raise DeployError("pedal file listing lacks FLST_SEQ.ZT2")
    legacy = sorted(name for name in files if name.startswith("N2Z")
                    and name.upper().endswith((".ZD2", ".ZIC"))
                    and name not in (BANK_NAME, BANK_ICON))
    if legacy:
        raise DeployError(f"another NAM2Zoom effect is installed: {legacy}")
    existing = BANK_NAME in files
    if (BANK_ICON in files) != existing:
        raise DeployError("existing N2Z Bank binary/icon pair is incomplete")
    live = session / "live-check"
    live.mkdir()
    flst_path = live / "FLST_SEQ.ZT2"
    _download("FLST_SEQ.ZT2", flst_path)
    old_list = flst_path.read_bytes()
    valid, problems, entries = _flst().validate_flst(old_list)
    if not valid:
        raise DeployError(f"pedal effect list is invalid: {problems}")
    count = sum(entry[1] == BANK_NAME for entry in entries)
    if count != int(existing):
        raise DeployError("bank files and effect-list entry disagree")
    installed = {entry[1]: entry[3] for entry in entries if entry[4]}
    if len(installed) != sum(bool(entry[4]) for entry in entries):
        raise DeployError("pedal effect list contains duplicate installed filenames")
    if effect is not None:
        installed.pop(BANK_NAME, None)
        problems = audit_bytes(effect.read_bytes(), icon.read_bytes(), installed)
        if problems:
            raise DeployError("new bank failed offline audit: " + "; ".join(problems))
    if existing:
        old_effect = live / BANK_NAME
        _download(BANK_NAME, old_effect)
        _download(BANK_ICON, live / BANK_ICON)
        old = parse_zd2_bytes(old_effect.read_bytes())
        if old.effect_id != BANK_ID or old.name != "N2Z Bank":
            raise DeployError("existing N2ZBANK filename has an unexpected identity")
    return existing, live


def _read_effect_list(destination: Path) -> bytes:
    _download("FLST_SEQ.ZT2", destination)
    data = destination.read_bytes()
    good, problems, _ = _flst().validate_flst(data)
    if not good:
        raise DeployError("pedal effect list failed readback validation: "
                          + "; ".join(problems))
    return data


def install_bank(effect: Path, session: Path, effect_hash: str,
                 icon_hash: str, *, full_backup: bool = True) -> str:
    effect = effect.resolve(strict=True)
    icon = effect.with_suffix(".ZIC")
    if effect.name != BANK_NAME or not icon.is_file():
        raise DeployError("expected N2ZBANK.ZD2 and companion N2ZBANK.ZIC")
    verify_approved(effect, icon, effect_hash, icon_hash)
    session = session.resolve()
    session.mkdir(parents=True, exist_ok=False)
    frozen = session / "approved"
    frozen.mkdir()
    (frozen / BANK_NAME).write_bytes(effect.read_bytes())
    (frozen / BANK_ICON).write_bytes(icon.read_bytes())
    effect, icon = frozen / BANK_NAME, frozen / BANK_ICON
    verify_approved(effect, icon, effect_hash, icon_hash)

    _tool("pedal_diy.py", "install", str(effect), "--dry-run")
    opener = _tool("safe_connect.py", str(session / "preflight"), capture=True)
    if "Autosave OFF - CONFIRMED" not in opener or "CRC ok" not in opener:
        raise DeployError("autosave OFF or current-patch CRC was not confirmed")
    require_stock_patch(session / "preflight/CURRENT.ZPTC")
    current = session / "preflight/CURRENT.ZPTC"
    if full_backup:
        _run(_python(ROOT / "tools/msplus.py", "--timeout", "5", "backup",
                     str(session / "backup")))
        backup = session / "backup"
        existing = plan_backup(effect, icon, backup, current)
        prior = backup / "files"
    else:
        existing, prior = plan_live(effect, icon, session, current)
    before = (prior / "FLST_SEQ.ZT2").read_bytes()
    verify_approved(effect, icon, effect_hash, icon_hash)
    if existing:
        old_effect = prior / BANK_NAME
        old_icon = prior / BANK_ICON
        if digest(old_effect) == effect_hash.lower() and digest(old_icon) == icon_hash.lower():
            print("N2Z Bank is already installed with these exact bytes; no pedal write needed.",
                  flush=True)
            return "already-installed"
        _tool("pedal_diy.py", "uninstall", str(old_effect), "--dry-run")

    print("Preflight and stock-patch checks passed. Starting non-cancellable pedal transfer.",
          flush=True)
    if existing:
        _tool("pedal_diy.py", "uninstall", str(old_effect))
        for name in (BANK_NAME, BANK_ICON):
            _tool("readback.py", name, str(session / f"removed-{name}"), expected=1)
        removed = _read_effect_list(session / "after-uninstall-FLST_SEQ.ZT2")
        good, problems = _flst().expect_single_remove(before, removed, BANK_NAME)
        if not good:
            raise DeployError("uninstall effect-list diff is wrong: " + "; ".join(problems))
        before = removed

    verify_approved(effect, icon, effect_hash, icon_hash)
    _tool("pedal_diy.py", "install", str(effect))
    for name, expected in ((BANK_NAME, effect_hash), (BANK_ICON, icon_hash)):
        destination = session / "readback" / name
        _tool("readback.py", name, str(destination))
        if digest(destination) != expected.lower():
            raise DeployError(f"pedal readback differs from approved {name}")
    after = _read_effect_list(session / "after-install-FLST_SEQ.ZT2")
    good, problems = _flst().expect_single_add(before, after, BANK_NAME)
    if not good:
        raise DeployError("install effect-list diff is wrong: " + "; ".join(problems))
    print("N2Z Bank installed and independently verified. Do not save a patch "
          "containing the experimental effect.", flush=True)
    return "installed"


def uninstall_bank(session: Path, *, full_backup: bool = True) -> str:
    session = session.resolve()
    session.mkdir(parents=True, exist_ok=False)
    opener = _tool("safe_connect.py", str(session / "preflight"), capture=True)
    if "Autosave OFF - CONFIRMED" not in opener or "CRC ok" not in opener:
        raise DeployError("autosave OFF or current-patch CRC was not confirmed")
    current = session / "preflight/CURRENT.ZPTC"
    require_stock_patch(current)
    if full_backup:
        _run(_python(ROOT / "tools/msplus.py", "--timeout", "5", "backup",
                     str(session / "backup")))
        backup = session / "backup"
        existing = plan_backup(None, None, backup, current)
        prior = backup / "files"
    else:
        existing, prior = plan_live(None, None, session, current)
    if not existing:
        print("N2Z Bank is not installed; no pedal write needed.", flush=True)
        return "not-installed"

    old_effect = prior / BANK_NAME
    old_icon = prior / BANK_ICON
    effect_hash, icon_hash = digest(old_effect), digest(old_icon)
    before = (prior / "FLST_SEQ.ZT2").read_bytes()
    _tool("pedal_diy.py", "uninstall", str(old_effect), "--dry-run")
    verify_approved(old_effect, old_icon, effect_hash, icon_hash)
    print("Preflight and stock-patch checks passed. Starting non-cancellable pedal uninstall.",
          flush=True)
    _tool("pedal_diy.py", "uninstall", str(old_effect))
    for name in (BANK_NAME, BANK_ICON):
        _tool("readback.py", name, str(session / f"removed-{name}"), expected=1)
    removed = _read_effect_list(session / "after-uninstall-FLST_SEQ.ZT2")
    good, problems = _flst().expect_single_remove(before, removed, BANK_NAME)
    if not good:
        raise DeployError("uninstall effect-list diff is wrong: " + "; ".join(problems))
    print("N2Z Bank uninstalled and independently verified.", flush=True)
    return "uninstalled"
