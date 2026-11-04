# Legacy kernel timing kit

This kit compares two kernel baselines using the same model weights. The
`original` and `optimized` directories contain the corresponding effects. Use
baselines with matching control layouts. Current Full/Compact comparisons use
`tools/build_component_timing.py` instead.

1. Close MIDI apps and select a stock-only pedal patch.
2. Run `Run.ps1 -Action original -PortableRoot <portable-app-folder>`.
3. Add N2Z Bank alone to an unsaved patch, leave controls at defaults and record
   40 seconds of direct line-output WAV, including report tones.
4. Remove it, select a stock patch, install `-Action optimized` and repeat.
5. Remove the diagnostic and reinstall a normal bank through Build effect.

Do not save a diagnostic patch or reboot into it. Keep the original recordings
unprocessed and unclipped. `-Action compare -Wav <original.wav> -CompareWav
<optimized.wav>` decodes the pair. Elapsed ticks include firmware interruptions
and probe overhead; they are not absolute DSP percentages. The network parks
while report tones play. Kits contain the supplied model weights.
