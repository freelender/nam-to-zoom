"""The three local NAM effect slots and their on-pedal identities."""
from dataclasses import dataclass
import re
import struct

from zd2 import parse_zd2_bytes, compute_checksum
from offline_effect_audit import audit_bytes, check_zic


@dataclass(frozen=True)
class EffectSlot:
    number: int
    effect_id: int
    stem: str
    name: str

    @property
    def filename(self):
        return self.stem + ".ZD2"

    @property
    def icon(self):
        return self.stem + ".ZIC"


SLOTS = (
    EffectSlot(1, 0x04001787, "N2ZBANK", "N2Z Bank"),
    EffectSlot(2, 0x04001387, "N2ZBNK2", "N2Z Bnk2"),
    EffectSlot(3, 0x04001397, "N2ZBNK3", "N2Z Bnk3"),
)


def effect_slot(number=1):
    if type(number) is not int or not 1 <= number <= len(SLOTS):
        raise ValueError("Choose NAM effect slot 1, 2 or 3")
    return SLOTS[number - 1]


def validate_name(name, *, max_length=8):
    if not isinstance(name, str) or not re.fullmatch(rf"[A-Za-z0-9 _-]{{1,{max_length}}}", name) or name != name.strip():
        raise ValueError(f"Effect name must be 1–{max_length} ASCII letters, digits, spaces, - or _, without surrounding spaces")
    return name


def identify(effect, *, legacy=False):
    slot = next((s for s in SLOTS if s.filename == effect.name.upper()), None)
    if slot is None:
        raise ValueError("Choose a nam2zoom slot file: N2ZBANK.ZD2, N2ZBNK2.ZD2 or N2ZBNK3.ZD2")
    z = parse_zd2_bytes(effect.read_bytes())
    old = legacy and slot.number == 1 and z.effect_id == 0x07000F87 and z.name == "N2Z Bank"
    if not old and z.effect_id != slot.effect_id:
        raise ValueError("Slot filename and effect ID do not match")
    validate_name(z.name, max_length=10)
    if not z.checksum_valid:
        raise ValueError("Effect checksum is invalid")
    return slot, z


def personalize(effect, number=1, name=None, *, name_artwork=True):
    slot = effect_slot(number)
    name = validate_name(name if name is not None else slot.name)
    raw = bytearray(effect.read_bytes())
    icon_path = effect.with_suffix(".ZIC")
    icon = icon_path.read_bytes()
    original = parse_zd2_bytes(raw)
    raw[100:111] = name.encode("ascii").ljust(11, b"\0")
    struct.pack_into("<I", raw, 96, slot.effect_id)
    if name_artwork:
        from .artwork import named_icon
        icon = named_icon(icon, name)
        first, _ = check_zic(icon)
        chunk = next(c for c in original.chunks if c.tag == "ICON")
        raw[chunk.offset+8:chunk.offset+8+chunk.length] = first
    struct.pack_into("<I", raw, 8, compute_checksum(raw))
    if parse_zd2_bytes(raw).data_chunk.data != original.data_chunk.data:
        raise ValueError("Identity change modified DSP data")
    errors = audit_bytes(bytes(raw), icon, {})
    if errors:
        raise ValueError("Named effect failed audit: " + "; ".join(errors))
    target = effect.with_name(slot.filename)
    target.write_bytes(raw)
    target.with_suffix(".ZIC").write_bytes(icon)
    if target != effect:
        effect.unlink()
        icon_path.unlink()
    return target
