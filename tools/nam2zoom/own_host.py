"""nam2zoom's full-Lite, floating-point host with seven functional controls."""
import hashlib
import json
from pathlib import Path

from .bank import load_models, prepare_bank, build_bank, own_host_dsp_load
from .hybrid import classify


def build_ready_effect(paths, labels, output, *, compact_effect=False, effect_slot=1, effect_name=None, name_artwork=True):
    from .identity import effect_slot as get_slot, validate_name, personalize
    slot = get_slot(effect_slot)
    if effect_name is not None:
        validate_name(effect_name)
    models = load_models(paths, labels, profile="lite")
    for path, *_ in models:
        if classify(path, "lite")["status"] != "direct":
            raise ValueError(f"{path.name}: full A2 Lite at 44.1 kHz is required; retrain first")
    manifest = prepare_bank(models, output, profile="lite", own_host=True, compact_effect=compact_effect)
    effect = build_bank(manifest)
    if effect_slot != 1 or effect_name is not None:
        effect = personalize(effect, effect_slot, effect_name, name_artwork=name_artwork)
    dsp_load = own_host_dsp_load(compact_effect)
    report = {"engine": "nam2zoom-float-seven-v1", "sampleRate": 44100,
              "effectSlot": effect_slot, "effectId": f"0x{slot.effect_id:08X}",
              "effectName": effect_name if effect_name is not None else slot.name,
              "effectFilename": slot.filename, "nameOnArtwork": name_artwork and (effect_slot != 1 or effect_name is not None),
              "modelSync": "dedicated-coefficient-v1", "modelCoefficientSlot": 12,
              "effectMode": "compact" if compact_effect else "full",
              "delayAdjustment": "round-each-tap-3-over-4-precomputed-v1" if compact_effect else "none",
              "internalSampleRate": 33075 if compact_effect else 44100,
              "addedLatencySamples": 64 if compact_effect else 0,
              "convolutionHistoryPasses": 1,
              "processingSamples": 12 if compact_effect else 16, "convolutionGroupSamples": 2,
              "resamplerAccumulatorCount": 4 if compact_effect else 0,
              "historyBytes": (20474 if compact_effect else 20406) * 4,
              "modelProfile": "lite", "arithmetic": "float32", "weightsQuantized": False,
              "declaredDspLoad": dsp_load, "patchBudget": 270, "measuredDspPercent": None,
              "experimentalDspLoad": True,
              "controlPages": [["Model", "Gain", "Volume", "Mix"], ["Bass", "Middle", "Treble"]],
              "gainUnityValue": 50, "controls": ["Model", "Gain", "Volume", "Mix", "Bass", "Middle", "Treble"],
              "labels": [label for _, label, *_ in models],
              "captures": [{"name": path.name, "sha256": digest, "weightsSha256": hashlib.sha256(weights).hexdigest()}
                           for path, _, weights, digest in models]}
    effect.with_name("engine-report.json").write_text(json.dumps(report, indent=2) + "\n")
    print("Built nam2zoom's full A2 Lite 44.1 kHz float host: Model, Gain, Volume, Mix; Bass, Middle, Treble.", flush=True)
    artwork = "amp artwork with compact label" if compact_effect else "original artwork"
    print(f"{'Compact' if compact_effect else 'Full'} effect: {artwork}; float32 NAM weights retained. Test DSP reservation {dsp_load}/270; actual DSP percent is unmeasured.", flush=True)
    if compact_effect:
        print("Compact runs the network at 33.075 kHz with filtered 44.1 kHz I/O and adds 64 samples latency. Tone/dynamics may change; the source NAM is unchanged.", flush=True)
    return effect
