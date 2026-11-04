"""Render the Compact mode label into the pedal's two native bitmap frames.

The original amp asset is untouched. This small pixel-font overlay is baked
into the effect and its companion icon, with no audio/runtime rendering cost.
"""
import struct

from offline_effect_audit import check_zic, audit_bytes
from zd2 import parse_zd2_bytes, compute_checksum

COMPACT_ARTWORK = "amp-compact-v1"
NAME_FONT = dict(zip("0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ-_ ", (
    "3E5149453E", "00427F4000", "4261514946", "2141454B31", "1814127F10",
    "2745454539", "3C4A494930", "0171090503", "3649494936", "064949291E",
    "7E1111117E", "7F49494936", "3E41414122", "7F4141221C", "7F49494941",
    "7F09090901", "3E4149497A", "7F0808087F", "00417F4100", "2040413F01",
    "7F08142241", "7F40404040", "7F020C027F", "7F0408107F", "3E4141413E",
    "7F09090906", "3E4151215E", "7F09192946", "4649494931", "01017F0101",
    "3F4040403F", "1F2040201F", "3F4038403F", "6314081463", "0708700807",
    "6151494543", "0808080808", "4040404040", "0000000000",
)))


def named_icon(icon, name):
    """Replace the amp's title; leave its outline, speaker and Compact badge."""
    from .identity import validate_name
    validate_name(name)
    _, errors = check_zic(icon)
    if errors:
        raise ValueError("Invalid name artwork: " + "; ".join(errors))
    result = bytearray(icon)
    offset = 32
    for width, height in [struct.unpack_from("<HH", icon, i) for i in (8, 12)]:
        def pixel(x, y, on):
            index = offset + (y // 8) * width + x
            mask = 1 << (y % 8)
            result[index] = (result[index] | mask) if on else (result[index] & ~mask)
        top, bottom = height * 38 // 97, height * 67 // 97
        for y in range(top, bottom):
            for x in range(10, width - 10):
                pixel(x, y, False)
        # Fixed sizes avoid the old 1x/2x jump between library and patch views.
        glyph_width, glyph_height, gap = (7, 11, 2) if width == 97 else (9, 15, 3)
        span = len(name) * (glyph_width + gap) - gap
        left = (width - span) // 2
        y0 = (top + bottom - glyph_height) // 2
        for char in name.upper():
            columns = bytes.fromhex(NAME_FONT[char])
            for x in range(glyph_width):
                for y in range(glyph_height):
                    # A one-pixel horizontal emboldening stays inside each glyph.
                    on = any(columns[((2*(x-dx)+1)*5)//(2*(glyph_width-1))]
                             & (1 << (((2*y+1)*7)//(2*glyph_height)))
                             for dx in (0, 1) if 0 <= x-dx < glyph_width-1)
                    if on:
                        pixel(left + x, y0 + y, True)
            left += glyph_width + gap
        offset += width * ((height + 7) // 8)
    return bytes(result)

GLYPHS = {
    "c": ("000", "000", "011", "100", "100", "100", "011"),
    "o": ("000", "000", "010", "101", "101", "101", "010"),
    "m": ("00000", "00000", "11010", "10101", "10101", "10101", "10101"),
    "p": ("000", "000", "110", "101", "110", "100", "100"),
    "a": ("000", "000", "011", "001", "011", "101", "011"),
    "t": ("010", "010", "111", "010", "010", "010", "011"),
}


def compact_icon(icon: bytes) -> bytes:
    _, errors = check_zic(icon)
    if errors:
        raise ValueError("invalid mode artwork: " + "; ".join(errors))
    dimensions = [struct.unpack_from("<HH", icon, offset) for offset in (8, 12)]
    if dimensions != [(97, 97), (128, 128)]:
        raise ValueError("Compact artwork requires PREAMP frames")
    result = bytearray(icon)
    offset = 32
    label_width = sum(len(GLYPHS[c][0]) + 1 for c in "compact") - 1
    for width, height in dimensions:
        # Keep the label inside the cabinet, below and right of its speaker.
        margin = 8 if width == 97 else 10
        left = width - margin - label_width
        top = height - (8 if width == 97 else 11) - 7
        for char in "compact":
            glyph = GLYPHS[char]
            for y, row in enumerate(glyph):
                for x, pixel in enumerate(row):
                    if pixel == "1":
                        # Zoom bitmap bytes are columns of eight vertical pixels.
                        result[offset + ((top+y)//8)*width + left+x] |= 1 << ((top+y)%8)
            left += len(glyph[0]) + 1
        offset += width * ((height + 7) // 8)
    return bytes(result)


def stamp_compact_artwork(effect):
    """Keep the ZD2's embedded ICON and the companion ZIC synchronized."""
    raw = bytearray(effect.read_bytes())
    icon_path = effect.with_suffix(".ZIC")
    original = icon_path.read_bytes()
    errors = audit_bytes(bytes(raw), original, {})
    if errors:
        raise ValueError("effect failed audit before mode label: " + "; ".join(errors))
    icon = compact_icon(original)
    first, _ = check_zic(icon)
    chunk = next(c for c in parse_zd2_bytes(raw).chunks if c.tag == "ICON")
    if len(chunk.data) != len(first):
        raise ValueError("mode artwork frame size mismatch")
    raw[chunk.offset+8:chunk.offset+8+len(first)] = first
    struct.pack_into("<I", raw, 8, compute_checksum(raw))
    errors = audit_bytes(bytes(raw), icon, {})
    if errors:
        raise ValueError("mode artwork failed audit: " + "; ".join(errors))
    effect.write_bytes(raw)
    icon_path.write_bytes(icon)
