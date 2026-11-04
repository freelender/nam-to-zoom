# Full/Compact component timing kit

Both variants use the supplied NAM weights. `original` is Full (Model FULL);
`optimized` is Compact (Model CMP). The probe measures neural processing,
resampling and final tone/mix processing over 4,096 callbacks. Remaining callback
overhead is reported separately.

1. Close MIDI apps and select a stock-only pedal patch.
2. Run `Run.ps1 -Action original -PortableRoot <portable-app-folder>`.
3. Add N2Z Bank alone to an unsaved patch with all controls at defaults. Record
   60 seconds of direct line-output WAV, including report tones, as `full.wav`.
4. Remove it, select a stock patch and repeat with `-Action optimized`, saving
   `compact.wav`.
5. Remove the diagnostic and reinstall a normal bank through Build effect.

Do not save a diagnostic patch or reboot into it. Keep recordings unprocessed
and unclipped. Run `Run.ps1 -Action compare -Wav <full.wav> -CompareWav
<compact.wav> -PortableRoot <portable-app-folder>` to decode the pair.

CRC and model/engine tags identify matching reports. Component percentages are
shares of callback time, not absolute DSP usage. Timings include interruptions
and probe overhead. Separate component maxima must not be added. The network
parks during report tones. Kits contain the supplied model weights.
