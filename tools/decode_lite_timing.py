"""Decode a temporary Lite timing effect's line-output WAV recording."""
import argparse
import json
from pathlib import Path
import struct
import zlib

import numpy as np
import soundfile as sf

SYNC = 0x4E32545A
WORDS = 19
PROFILE_WORDS = 27
KEYS = ("sync", "version", "variant", "status", "blocks", "frames",
        "idle_period_mean", "idle_period_min", "idle_period_max", "timer_read_ticks",
        "callback_mean", "callback_min", "callback_max", "loaded_period_mean",
        "loaded_period_min", "loaded_period_max", "warmup_blocks", "model_tag", "crc32")
COMPONENTS = ("neural", "downsample", "upsample", "postprocess")
PROFILE_KEYS = KEYS[:-1] + tuple(f"{stage}_{stat}" for stage in COMPONENTS for stat in ("mean", "max")) + ("crc32",)
STATUSES = {0: "ok", 1: "timer unavailable", 2: "network reset/recovery during measurement",
            3: "warmup did not complete", 4: "controls changed: restore defaults and bypass/on"}


def packet_bytes(words):
    """Reference wire format: little-endian words, bits within each word MSB first."""
    count = PROFILE_WORDS if words[1] == 2 else WORDS
    if len(words) != count - 1:
        raise ValueError("wrong diagnostic packet length")
    prefix = struct.pack(f"<{len(words)}I", *words)
    return prefix + struct.pack("<I", zlib.crc32(prefix))


def valid_packets(bits):
    sync_bits = f"{SYNC:032b}"
    found = []
    start = bits.find(sync_bits)
    while start >= 0:
        header = bits[start:start+64]
        version = int(header[32:64],2) if len(header)==64 and 'x' not in header else 0
        count = PROFILE_WORDS if version == 2 else WORDS
        candidate = bits[start:start + count * 32]
        if version in (1,2) and len(candidate) == count * 32 and "x" not in candidate:
            words = [int(candidate[i:i + 32], 2) for i in range(0, len(candidate), 32)]
            raw = struct.pack(f"<{count}I", *words)
            if zlib.crc32(raw[:-4]) == words[-1]:
                found.append(tuple(words))
        start = bits.find(sync_bits, start + 1)
    return found


def channel_packets(samples, rate, packet_decoder=None):
    # 1 ms RMS windows locate 10 ms tones, with 10 ms gaps. Relative threshold
    # accepts interface gain changes; CRC rejects noise/music and missing bits.
    window = max(1, round(rate * .001))
    count = len(samples) // window
    if count < 30:
        return []
    rms = np.sqrt(np.mean(samples[:count * window].reshape(count, window) ** 2, axis=1))
    # Ignore the short, potentially louder NAM measurement preceding the tones.
    peak = float(np.quantile(rms, .80))
    if peak < 1e-7:
        return []
    active = rms > peak * .30
    changes = np.diff(np.r_[False, active, False].astype(np.int8))
    starts, ends = np.flatnonzero(changes == 1), np.flatnonzero(changes == -1)
    bits = []
    for start, end in zip(starts, ends):
        if not .006 <= (end - start) * window / rate <= .014:
            bits.append("x")
            continue
        tone = samples[start * window:end * window]
        tone = tone - tone.mean()
        t = np.arange(len(tone)) / rate
        energy = []
        for frequency in (44100 / 64, 44100 / 32):
            energy.append(max(abs(np.dot(tone, np.exp(-2j * np.pi * f * t))) ** 2
                              for f in frequency * np.array([.98, 1., 1.02])))
        low, high = sorted(energy)
        bits.append(str(int(energy[1] > energy[0])) if high > 4 * max(low, 1e-20) else "x")
    return (packet_decoder or valid_packets)("".join(bits))


def decode(path):
    data, rate = sf.read(str(path), dtype="float64", always_2d=True)
    if not 8000 <= rate <= 192000 or not np.all(np.isfinite(data)):
        raise ValueError("unsupported sample rate or non-finite audio")
    reports = []
    for index in range(data.shape[1]):
        packets = channel_packets(data[:, index], rate)
        if packets:
            reports.append((index, packets))
    if not reports:
        raise ValueError("no complete CRC-valid report; record 40 seconds of direct pedal output, with no effects or processing")
    unique = {packet for _, packets in reports for packet in packets}
    if len(unique) != 1:
        raise ValueError("recording contains conflicting reports; use a separate recording for each run")
    packet = unique.pop()
    result = dict(zip(PROFILE_KEYS if packet[1] == 2 else KEYS, packet))
    result.update(variant_name=({0: "full", 1: "compact"} if packet[1]==2 else {0: "original", 1: "optimized"}).get(packet[2], "unknown"),
                  status_text=STATUSES.get(packet[3], "unknown status"),
                  recording=str(Path(path).resolve()), sample_rate=rate,
                  channels_decoded=[i + 1 for i, _ in reports],
                  repetitions=max(len(packets) for _, packets in reports),
                  clipped=bool(np.max(np.abs(data)) >= .999))
    if result["variant"] not in (0, 1) or result["status"] not in STATUSES or result["frames"] != 16:
        raise ValueError("unsupported diagnostic report")
    if result["status"] == 0:
        if result["blocks"] != 4096 or not (0 < result["callback_min"] <= result["callback_mean"] <= result["callback_max"]):
            raise ValueError("invalid timing statistics")
        if not (0 < result["idle_period_min"] <= result["idle_period_mean"] <= result["idle_period_max"]):
            raise ValueError("invalid idle cadence")
        result["mean_to_idle_period_ratio"] = result["callback_mean"] / result["idle_period_mean"]
        result["worst_to_idle_period_ratio"] = result["callback_max"] / result["idle_period_mean"]
        if packet[1] == 2:
            for component in COMPONENTS:
                if not 0 <= result[component+"_mean"] <= result[component+"_max"]:
                    raise ValueError("invalid component timing")
            measured = sum(result[component+"_mean"] for component in COMPONENTS)
            if measured > result['callback_mean']:
                raise ValueError("component means exceed callback time")
            result['unattributed_mean_ticks'] = result['callback_mean']-measured
            result['component_share_of_callback_percent'] = {
                component:100*result[component+'_mean']/result['callback_mean'] for component in COMPONENTS}
    return result


def compare(first, second):
    if any(r["status"] != 0 or r["clipped"] for r in (first, second)):
        raise ValueError("comparison needs successful, unclipped recordings")
    if first["variant"] == second["variant"] or any(first[k] != second[k] for k in ("version", "model_tag", "frames", "blocks")):
        raise ValueError("comparison needs original and optimized variants with the same model and geometry")
    original, optimized = sorted((first, second), key=lambda r: r["variant"])
    cadence_ratio = optimized["idle_period_mean"] / original["idle_period_mean"]
    if not .95 <= cadence_ratio <= 1.05:
        raise ValueError("idle timer cadence differs by more than 5%; repeat with the same pedal/settings")
    return {"mean_change_percent": 100 * (optimized["callback_mean"] / original["callback_mean"] - 1),
            "worst_observed_change_percent": 100 * (optimized["callback_max"] / original["callback_max"] - 1),
            "note": "Negative is less time. Includes interrupts and timer/call overhead. Observed maxima are not guaranteed worst-case bounds."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wav", type=Path)
    parser.add_argument("--compare", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        result = decode(args.wav)
        output = {"report": result}
        print(f'{result["variant_name"]}: {result["status_text"]}; {result["repetitions"]} CRC-valid report(s)')
        if result["status"] == 0:
            print(f'Callback clock ticks: mean {result["callback_mean"]:,}; min {result["callback_min"]:,}; observed max {result["callback_max"]:,}')
            print(f'Idle callback period: {result["idle_period_mean"]:,} ticks; loaded: {result["loaded_period_mean"]:,} ticks')
            print("These are diagnostic elapsed times, not a firmware DSP-load percentage or saved-patch safety result.")
            if result['version']==2:
                for stage in COMPONENTS:
                    print(f"{stage}: mean {result[stage+'_mean']:,} ticks; observed max {result[stage+'_max']:,}")
        if result["clipped"]:
            print("Recording clipped; reduce interface gain and repeat before comparing.")
        if args.compare:
            other = decode(args.compare)
            output["other_report"] = other
            output["comparison"] = compare(result, other)
            print(json.dumps(output["comparison"], indent=2))
        target = args.output or args.wav.with_suffix(".timing.json")
        target.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
        print(f"Saved {target}")
        return 0 if result["status"] == 0 else 2
    except (ValueError, RuntimeError, OSError) as error:
        parser.exit(2, f"Timing decode failed: {error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
