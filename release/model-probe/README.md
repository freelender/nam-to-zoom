# Tuner model-state probe

The probe reports the host's Model value when available, the model coefficient,
active audio model, initialization progress and history-arena identity. Report
tones replace guitar output while normal processing runs. The labels and model
order are listed in `probe-kit.json`.

1. Extract the kit. Close MIDI apps and select a stock-only pedal patch.
2. Run `Run.cmd` and choose Full or Compact. Supply the complete portable app
   folder if prompted. The guarded installer backs up the pedal.
3. Add N2Z Bank alone to an unsaved patch. Enable it, leave other knobs at
   defaults and select a model other than the first.
4. Record 35 seconds of direct line-output WAV at 44.1 or 48 kHz. No guitar
   playing is needed.
5. Turn the tuner on for five seconds, then off. Without touching any knobs,
   record another 35 seconds.
6. Move Model away and back to the selected model, then record 35 more seconds.
7. Remove the probe and reinstall a normal bank through Build effect.

Do not save or reboot into the diagnostic patch. Keep the complete recording,
including gaps, without effects or clipping. `Run.cmd` option 3 writes decoded
snapshots to `.model-probe.json` beside the WAV. Indices are zero-based; -2 means
the parameter service was unavailable, not a model selection. Sequence numbers
can restart after state reinitialization. CRC rejects incomplete reports.

Kits contain the supplied model weights. The probe uses 188 bytes of scratch
plus the guard word, within the builder's 192-byte limit. It does not measure
DSP load or audio fidelity.
