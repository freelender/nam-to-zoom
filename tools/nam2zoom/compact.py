"""Strict offline shape and resource checks for the reduced A2 experiments."""

import math
import struct
from dataclasses import dataclass


KERNEL_SIZES = (3,) * 14
DILATIONS = (1, 3, 7, 17, 41, 101, 239) * 2
HEAD_KERNEL = 8
SAMPLE_RATE = 44100

# Lite matches the native A2 Lite geometry; its weights are retrained at 44.1 kHz.
PROFILES = {
    "compact": (KERNEL_SIZES, DILATIONS, HEAD_KERNEL),
    "lite": ((6,) * 14 + (15, 15) + (6,) * 7,
             (1, 3, 7, 17, 41, 101, 239) * 2 + (1, 13)
             + (1, 3, 7, 17, 41, 101, 239), 16),
}


def geometry(profile):
    if profile not in PROFILES:
        raise ValueError(f"unknown model profile: {profile}")
    return PROFILES[profile]


def pair_history_bytes(profile):
    kernels, dilations, head = geometry(profile)
    return 3 * (sum((k - 1) * d + 2 for k, d in zip(kernels, dilations)) + head + 1) * 4


def reserved_dsp_load(profile):
    """Conservative admission budget; not a measurement of execution time."""
    geometry(profile)
    return 270 if profile == "lite" else 150


@dataclass(frozen=True)
class CompactModel:
    channels: int
    weights: tuple[float, ...]
    profile: str = "compact"

    @property
    def receptive_field(self):
        kernels, dilations, head = geometry(self.profile)
        return 1 + sum((k - 1) * d for k, d in zip(kernels, dilations)) + head - 1

    @property
    def mirrored_history_bytes(self):
        kernels, dilations, head = geometry(self.profile)
        positions = sum((k - 1) * d + 1 for k, d in zip(kernels, dilations)) + head
        return 2 * positions * self.channels * 4

    @property
    def convolution_terms_per_sample(self):
        return sum(geometry(self.profile)[0]) * self.channels * self.channels

    def weight_bytes(self):
        payload = struct.pack(f"<{len(self.weights)}f", *self.weights)
        if any(not math.isfinite(w) for w in struct.unpack(f"<{len(self.weights)}f", payload)):
            raise ValueError("weight cannot be represented as finite float32")
        return payload


def expected_parameters(channels, profile="compact"):
    if channels not in (2, 3):
        raise ValueError("compact model supports only 2 or 3 channels")
    kernels, _, head = geometry(profile)
    return (channels + sum(k * channels * channels + 3 * channels
                           + channels * channels for k in kernels)
            + head * channels + 2)


def _inactive(value):
    return value is None or value is False or (
        isinstance(value, dict) and value.get("active") is False
    )


def inspect(data, profile=None):
    if not isinstance(data, dict) or data.get("architecture") != "SlimmableContainer":
        raise ValueError("expected a SlimmableContainer")
    if data.get("sample_rate") != SAMPLE_RATE or data.get("weights") != []:
        raise ValueError("expected an empty 44.1 kHz container")
    entries = data.get("config", {}).get("submodels")
    if not isinstance(entries, list) or len(entries) != 1 or entries[0].get("max_value") != 1.0:
        raise ValueError("expected exactly one full-range submodel")
    model = entries[0].get("model")
    if not isinstance(model, dict) or model.get("architecture") != "WaveNet":
        raise ValueError("expected a WaveNet submodel")
    if model.get("sample_rate") != SAMPLE_RATE:
        raise ValueError("submodel sample rate differs from 44.1 kHz")
    config = model.get("config")
    if not isinstance(config, dict) or config.get("head") is not None or config.get("condition_dsp") is not None:
        raise ValueError("unsupported WaveNet top-level features")
    if config.get("in_channels", 1) != 1 or not isinstance(config.get("head_scale"), (int, float)):
        raise ValueError("unsupported WaveNet input or head scale")
    if not math.isfinite(config["head_scale"]):
        raise ValueError("head scale must be finite")
    layers = config.get("layers")
    if not isinstance(layers, list) or len(layers) != 1 or not isinstance(layers[0], dict):
        raise ValueError("expected one layer array")
    layer = layers[0]
    channels = layer.get("channels")
    if channels not in (2, 3) or layer.get("bottleneck") != channels:
        raise ValueError("unsupported channel count or bottleneck")
    if layer.get("input_size") != 1 or layer.get("condition_size") != 1:
        raise ValueError("unsupported layer input")
    matches = [name for name, (ks, ds, _) in PROFILES.items()
               if layer.get("kernel_sizes") == list(ks) and layer.get("dilations") == list(ds)]
    if not matches or (profile is not None and profile != matches[0]):
        raise ValueError("unsupported compact layer geometry")
    profile = matches[0]
    kernels, _, head_kernel = geometry(profile)
    if profile == "lite" and channels != 3:
        raise ValueError("Lite requires 3 channels")
    activations = layer.get("activation")
    if (not isinstance(activations, list) or len(activations) != len(kernels)
            or any(not isinstance(a, dict) or a.get("type") != "LeakyReLU"
                   or not isinstance(a.get("negative_slope"), (int, float))
                   or not math.isclose(a["negative_slope"], 0.01, rel_tol=0, abs_tol=1e-6)
                   for a in activations)):
        raise ValueError("unsupported activations")
    if layer.get("gating_mode") not in (None, ["none"] * len(kernels)):
        raise ValueError("unsupported gating")
    if layer.get("gated") is True or layer.get("secondary_activation") not in (
            None, [None] * len(kernels)):
        raise ValueError("unsupported secondary activation")
    if layer.get("layer1x1") != {"active": True, "groups": 1}:
        raise ValueError("unsupported layer1x1")
    head = layer.get("head")
    if not isinstance(head, dict) or head.get("out_channels") != 1 or head.get("kernel_size") != head_kernel or head.get("bias") is not True:
        raise ValueError("unsupported head")
    if head.get("head_dilation", 1) != 1 or layer.get("groups_input", 1) != 1 or layer.get("groups_input_mixin", 1) != 1:
        raise ValueError("unsupported groups or head dilation")
    for key in ("head1x1", "conv_pre_film", "conv_post_film", "input_mixin_pre_film",
                "input_mixin_post_film", "activation_pre_film", "activation_post_film",
                "layer1x1_post_film", "head1x1_post_film"):
        if not _inactive(layer.get(key)):
            raise ValueError(f"unsupported {key}")
    if layer.get("slimmable") is not None:
        raise ValueError("unsupported slimmable layer")
    weights = model.get("weights")
    if not isinstance(weights, list) or len(weights) != expected_parameters(channels, profile):
        raise ValueError("incorrect compact weight count")
    if any(type(w) not in (int, float) or not math.isfinite(w) for w in weights):
        raise ValueError("weights must be finite")
    result = CompactModel(channels, tuple(weights), profile)
    result.weight_bytes()
    return result
