# A2 Lite effect host

N2Z Bank runs full A2 Lite models: 23 layers, three channels and 1,871 float32
weights. A bank holds up to five models.

| Parameter page | Controls |
| --- | --- |
| 1 | Model, Gain, Volume, Mix |
| 2 | Bass, Middle, Treble |

Gain 50 is unity input drive; 100 doubles input. Changes are smoothed before
inference. Volume 50 is unity output, EQ 50 is flat, and Mix 100 is fully wet.
Model uses coefficient 12 and Gain uses 13. Coefficient 3 is overwritten across
tuner transitions and must not be used for the selector.

Full processes 16 neural samples per callback at 44.1 kHz. Compact processes
12 at 33.075 kHz with 193-tap polyphase FIR conversion to/from 44.1 kHz. Compact
adds 64 output samples of latency and aligns partial dry/wet mixes. `block4.c`
reuses history reads across all three convolution outputs.

Compact uses `compact_block.c`: every convolution and output-head tap reads
history at `round(original delay * 3/4)`, approximating the learned 44.1 kHz
timing at 33.075 kHz. Precomputed read increments avoid per-tap delay arithmetic.
Full retains `block4.c`. No separate weights or Compact retraining are needed.

Both modes retain the same network and weights. Their admission declarations
are 260 and 190, not measured CPU percentages. The Compact label is baked into
the icon and adds no audio processing work.

Runtime changes require new [templates](../../release/precompiled/README.md).
Retraining and shared NAM exports are independent of this host.
