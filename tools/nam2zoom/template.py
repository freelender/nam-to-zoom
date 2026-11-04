"""Fill model data in a verified precompiled bank; never modify DSP instructions."""

import hashlib
import json
from pathlib import Path
import struct

from elf32 import parse_elf32
from offline_effect_audit import audit_bytes
from zd2 import compute_checksum, parse_zd2_bytes

from .compact import expected_parameters, geometry, reserved_dsp_load
from .bank import max_models, own_host_dsp_load, OWN_HOST_COEFFICIENT_SLOTS

WORDS = expected_parameters(3)
SOURCES = ("dsp/nam_a2_bank_zd2/bank_effect.c", "dsp/nam_a2_compact/compact_pair.c",
           "dsp/nam_a2_compact/compact_pair.h", "dsp/nam_a2_compact/compact_kernel.h")


def sources(profile, own_host=False, compact_effect=False):
    geometry(profile)
    result = SOURCES if profile == "compact" else tuple(name.replace("nam_a2_compact/", "nam_a2_lite/") for name in SOURCES)
    return ("dsp/nam_a2_own_host/host.c", ("dsp/nam_a2_own_host/compact_block.c" if compact_effect else "dsp/nam_a2_own_host/block4.c"),
            "dsp/nam_a2_own_host/block4.h", "dsp/nam_a2_own_host/compact_runtime.h",
            "dsp/nam_a2_own_host/compact_filters.h", result[3]) if own_host else result


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fill_template(templates: Path, manifest: Path) -> Path:
    lock = json.loads((manifest.parent / "bank.json").read_text())
    profile = lock.get("model_profile", "compact")
    own_host = lock.get("control_layout") == "nam2zoom-seven-v1"
    dsp_load = own_host_dsp_load(lock.get("effect_mode") == "compact") if own_host else reserved_dsp_load(profile)
    words = expected_parameters(3, profile)
    config = json.loads(manifest.read_text(encoding="ascii"))
    params = config["params"]
    count = config["const_blob"]["words"] // words
    if not 1 <= count <= max_models(profile) or config["const_blob"]["words"] != count * words:
        raise ValueError("invalid template model count")
    index = json.loads((templates / "index.json").read_text(encoding="ascii"))
    if index.get("format") != "nam2zoom.templates.v1":
        raise ValueError("unsupported bank template format")
    if index.get("model_profile", "compact") != profile:
        raise ValueError("bank template model profile mismatch")
    if index.get("control_layout") != lock.get("control_layout"):
        raise ValueError("bank template control layout mismatch")
    if own_host and index.get("effect_mode") != lock.get("effect_mode"):
        raise ValueError("bank template Full/Compact mode mismatch")
    if own_host and (index.get("coefficient_slots") != OWN_HOST_COEFFICIENT_SLOTS or
                     {p["name"]:p.get("slot") for p in params} != OWN_HOST_COEFFICIENT_SLOTS):
        raise ValueError("bank template coefficient slots mismatch; regenerate templates")
    if own_host and lock.get("effect_mode") == "compact":
        from .artwork import COMPACT_ARTWORK
        if index.get("artwork_variant") != COMPACT_ARTWORK:
            raise ValueError("Compact template mode label is missing; regenerate templates")
    root = Path(__file__).resolve().parents[2]
    if index.get("dsp_source_sha256") != {name: digest((root / name).read_bytes()) for name in sources(profile, own_host, lock.get("effect_mode") == "compact")}:
        raise ValueError("bank templates do not match the current DSP sources")
    record = index["banks"][str(count)]
    raw = (templates / f"bank-{count}.ZD2").read_bytes()
    icon = (templates / "N2ZBANK.ZIC").read_bytes()
    if digest(raw) != record["sha256"] or digest(icon) != index["icon_sha256"]:
        raise ValueError("bank template or icon hash mismatch")
    expected_params = ["Model", "Bass", "Mid", "Treble", "Vol", "Input", "Mix"]
    defaults = [0, 50, 50, 50, 50, 50, 100]
    if own_host:
        expected_params = ["Model", "Gain", "Volume", "Mix", "Bass", "Middle", "Treble"]
        defaults = [0, 50, 50, 100, 50, 50, 50]
    if ([p["name"] for p in params] != expected_params or config["dspload"] != dsp_load
            or [p.get("default") for p in params] != defaults
            or [p.get("max", len(p.get("values", [])) - 1) for p in params]
            != [max(1, count - 1)] + [100] * (len(expected_params) - 1)):
        raise ValueError("manifest does not match the compiled template controls")
    zd2 = parse_zd2_bytes(raw)
    info = next(chunk for chunk in zd2.chunks if chunk.tag == "INFO")
    if index.get("reserved_dsp_load", dsp_load) != dsp_load or struct.unpack_from("<f", info.data, len(info.data) - 4)[0] != dsp_load:
        raise ValueError("template DSP reservation does not match the model profile; regenerate templates")
    elf = parse_elf32(zd2.data_chunk.data)
    const = next(section for section in elf.sections if section.name == ".const")
    base = zd2.data_chunk.offset + 8 + const.offset
    labels = params[0]["values"]
    if len(labels) != max(2, count):
        raise ValueError("selector does not match template capacity")
    weights = (manifest.parent / config["const_blob"]["init"]).read_bytes()
    if len(weights) != count * words * 4:
        raise ValueError("template weight size mismatch")
    if any(not (-float("inf") < value < float("inf"))
           for value in struct.unpack(f"<{count * words}f", weights)):
        raise ValueError("template weights must be finite")
    labels_data = b"".join(label.encode("ascii").ljust(8, b"\0") for label in labels)
    if any(not 1 <= len(label) <= 6 for label in labels):
        raise ValueError("invalid template selector label")
    output = bytearray(raw)
    ranges = [(record["weights_offset"], weights), (record["labels_offset"], labels_data)]
    spans = []
    for offset, payload in ranges:
        if not isinstance(offset, int) or not base <= offset < offset + len(payload) <= base + const.size:
            raise ValueError("template patch range escapes the constant section")
        spans.append((offset, offset + len(payload)))
        output[offset:offset + len(payload)] = payload
    if max(spans[0][0], spans[1][0]) < min(spans[0][1], spans[1][1]):
        raise ValueError("template patch ranges overlap")
    struct.pack_into("<I", output, 8, compute_checksum(output))
    errors = audit_bytes(bytes(output), icon, {})
    if errors:
        raise ValueError("filled bank failed audit: " + "; ".join(errors))
    # This check also covers relocations and every non-model byte of the ELF.
    patched_elf = parse_zd2_bytes(bytes(output)).data_chunk.data
    for section in elf.sections:
        if section.name != ".const" and patched_elf[section.offset:section.offset + section.size] != elf.data[section.offset:section.offset + section.size]:
            raise ValueError("template patch modified a non-constant section")
    build = manifest.parent / "build"
    build.mkdir(exist_ok=False)
    effect = build / "N2ZBANK.ZD2"
    effect.write_bytes(output)
    effect.with_suffix(".ZIC").write_bytes(icon)
    print(f"Filled precompiled {count}-model template; DSP code unchanged", flush=True)
    return effect
