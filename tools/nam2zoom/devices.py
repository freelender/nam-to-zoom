"""Supported Zoom MS Plus device identities."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DeviceProfile:
    key: str
    name: str
    family_code: int
    model_number: int
    firmware: str
    patch_count: int
    bank_hardware_tested: bool

    @property
    def identity(self) -> tuple[int, int, str]:
        return self.family_code, self.model_number, self.firmware


SUPPORTED_DEVICES = (
    DeviceProfile(
        key="ms50g-plus",
        name="Zoom MS-50G+",
        family_code=0x006E,
        model_number=0x0023,
        firmware="1.40",
        patch_count=100,
        bank_hardware_tested=True,
    ),
    DeviceProfile(
        key="ms70cdr-plus",
        name="Zoom MS-70CDR+",
        family_code=0x006E,
        model_number=0x0026,
        firmware="1.20",
        patch_count=100,
        bank_hardware_tested=True,
    ),
    DeviceProfile(
        key="ms60b-plus",
        name="Zoom MS-60B+",
        family_code=0x006E,
        model_number=0x0027,
        firmware="1.20",
        patch_count=100,
        bank_hardware_tested=False,
    ),
)


def identify_profile(
    family_code: int, model_number: int, firmware: str
) -> DeviceProfile | None:
    identity = family_code, model_number, firmware
    return next((profile for profile in SUPPORTED_DEVICES if profile.identity == identity), None)


def require_supported_device(
    family_code: int, model_number: int, firmware: str
) -> DeviceProfile:
    profile = identify_profile(family_code, model_number, firmware)
    if profile is not None:
        return profile
    expected = ", ".join(
        f"{item.name} firmware {item.firmware}" for item in SUPPORTED_DEVICES
    )
    raise ValueError(
        "unsupported pedal identity "
        f"(family 0x{family_code:04x}, model 0x{model_number:04x}, "
        f"firmware {firmware!r}); expected {expected}"
    )
