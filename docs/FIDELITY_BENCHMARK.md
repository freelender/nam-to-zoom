# Conversion fidelity benchmark

The benchmark uses the current training template and reports its network size.
The recorded experiments below used the previous pedal network: 44.1 kHz,
3 channels, 14 layers and 659 exported float32 weights. The production network has been restored to 14 layers and 659 weights.
The 16-layer, 749-weight experiment remains separate from production.
It neither builds an effect nor contacts a pedal.

Run with the developer training environment:

```powershell
& .\.tooling\nam-train-venv\Scripts\python.exe -B tools/benchmark_adaptation.py `
  'C:\models\clean.nam' 'C:\models\crunch.nam' 'C:\models\high-gain.nam' `
  --output .tooling/fidelity-benchmark --epochs 100 --seeds 0 1
```

The output directory must be new. All models, audio, training logs and
`results.json` stay local under that directory. Original models are never
modified.

Profiles:

- `legacy`: the previous training split and optimizer settings.
- `guarded`: the same optimizer with an experimental independent validation split.
- `cosine`: the guarded split, cosine learning-rate decay to 0.00002, and
  gradient clipping at 1.0. This is an experiment, not the app default.

All profiles use the same student geometry, training audio, initialization seed
and epoch budget. The existing NAM trainer exports its best validation checkpoint.
No new checkpoint-selection code is needed.

## Spectral-loss sweep

This developer-only benchmark retains spectral-weight sweeps for reproducibility.
The app and conversion CLI use standard loss only; the weaker-loss option was
removed after the 300-epoch comparison on 2026-10-07 showed small gains for clean
and crunch but a large regression for the Mark IIC+ heavy-distortion capture.

The app already trains with waveform MSE plus multi-resolution STFT loss,
weighted at 0.0005. The STFT term compares spectral convergence and log
magnitudes at multiple resolutions. Checkpoint selection remains validation
ESR. Changing this weight affects PC retraining, not the pedal's network.

Compare weaker, current and stronger spectral weighting at the supported
maximum training budget:

```powershell
& .\.tooling\nam-train-venv\Scripts\python.exe -B tools/benchmark_adaptation.py `
  'C:\models\clean.nam' 'C:\models\crunch.nam' 'C:\models\high-gain.nam' `
  --output .tooling/fidelity-loss-300 --epochs 300 --profiles legacy `
  --mrstft-weights 0.0005 0.0001 0.002
```

Loss sweeps require the legacy profile to keep the training split and optimizer
unchanged. Reports record the exact loss configuration and mean independent
spectral error alongside ESR. Probe audio is used to compare experimental
settings, never for gradients or checkpoint selection. `--probe-seed` produces
another deterministic diagnostic recording for follow-up comparisons.

Re-evaluate a complete report's existing exports without retraining:

```powershell
& .\.tooling\nam-train-venv\Scripts\python.exe -B tools/benchmark_adaptation.py `
  --evaluate-report .tooling/fidelity-loss-300/results.json `
  --output .tooling/fidelity-loss-followup --probe-seed 20261007
```

Use `--test-di` instead for a separate guitar recording. Source and student
hashes are checked against the original report before rendering.

Do not infer audible improvement from spectral error alone: inspect both error
metrics and listen to independent guitar recordings before adopting a setting.

Three input levels (0.25, 0.5 and 1.0) are evaluated on separate audio that is
never used for training or checkpoint selection. Metrics include ESR,
correlation, RMSE and spectral magnitude error. Comparisons use original
levels and timing; there is no gain fitting or waveform alignment.

By default, this audio is deterministic synthetic plucks, harmonics, noise and
a sweep. It tests generalization, but does not establish perceptual guitar
quality. Use `--test-di 'C:\audio\independent-guitar.wav'` for independent mono
44.1 kHz guitar DI, at least four seconds. It must be separate recording
material, not a renamed/cropped copy of the training recording. Exact duplicate
files are rejected; the tool cannot determine provenance of arbitrary audio.

## Validation leakage experiment

The bundled 190-second DI repeats its opening nine seconds exactly at the end.
The app uses the opening copy for fitting and the final copy for validation,
so this is not an independent fidelity measurement. The experimental guarded
profile excludes the repeated intro and leaves 250 ms before the validation
tail for history separation. Detection compares decoded float32 samples
exactly; nonrepeated DI retains its intro.

The guarded split was not adopted as the app default because the full-budget
comparison degraded independent-probe fidelity on two of three teachers.
The app's existing training split, optimizer and quality thresholds remain.
Quality reports now disclose whether the validation input was repeated in
training. Independent evaluation remains necessary when tuning conversions.

Pipeline `teacher-student-full-v2` (or `teacher-student-ir-v3` with a cab IR)
includes model and learning configuration hashes in cache keys, so future
training changes trigger fresh conversions. Existing caches are preserved but
use different keys; converted models imported directly are unaffected.

The investigation was informed by the independent ReTrainer's duplicate-aware
split and training controls, reviewed at commit
`0ff67608df50476ddfa748e5c4eb424e62c4ae8e`:
[audio split](https://github.com/Leemuzhko/ZOOM_development/blob/0ff67608df50476ddfa748e5c4eb424e62c4ae8e/NAM/retrainer/nam_retrainer/audio.py),
[training engine](https://github.com/Leemuzhko/ZOOM_development/blob/0ff67608df50476ddfa748e5c4eb424e62c4ae8e/NAM/retrainer/nam_retrainer/engine.py).
The benchmark is implemented here independently; no private reference code or
model weights are included.

## Measured experiments (2026-10-06)

Three local 48 kHz SlimmableContainer teachers were tested with seed 0 on an
RTX 3060, PyTorch 2.11.0+cu128, and the bundled 190-second DI. The table reports
mean ESR across the three independent synthetic probe levels; lower is better.

| Teacher | Epochs | Legacy | Corrected split | Cosine experiment |
| --- | ---: | ---: | ---: | ---: |
| 73 Twin Reverb V 555 DI | 20 | 0.15616 | 0.09380 | 0.16898 |
| JCM800 2203 Crunch | 20 | 0.15098 | 0.18310 | 0.28600 |
| Mark IIC+ Hetfield Rhythm V2 | 20 | 0.35670 | 0.39557 | 0.41604 |
| 73 Twin Reverb V 555 DI | 100 | 0.02913 | 0.03318 | — |
| JCM800 2203 Crunch | 100 | 0.12433 | 0.08316 | — |
| Mark IIC+ Hetfield Rhythm V2 | 100 | 0.16696 | 0.24296 | — |

The cosine experiment was worse on all three teachers at 20 epochs and was
not adopted. The guarded split improves the independence of validation, but
its independent-probe results are mixed, so it also remains an experiment.
These are diagnostic results from three teachers and one seed, not a listening
test or a pedal A/B comparison. Independent real guitar recordings and more
seeds should be used before adopting further optimizer changes.

Local logs, generated models/audio and raw metrics are in the ignored folders
`.tooling/fidelity-benchmark-20261006-screening` and
`.tooling/fidelity-benchmark-20261006-default`.

## Loss-weight experiments at 300 epochs (2026-10-06 to 2026-10-07)

The spectral-loss sweep uses the established training split and optimizer,
seed 0, the same bundled DI and independent diagnostic probes as above.
Both columns are mean errors across the three input levels; lower is better.

| Teacher | MRSTFT weight | Independent ESR | Spectral error |
| --- | ---: | ---: | ---: |
| 73 Twin Reverb V 555 DI | 0.0005 (current) | 0.02917 | 0.12619 |
| 73 Twin Reverb V 555 DI | 0.0001 | 0.00870 | 0.07829 |
| 73 Twin Reverb V 555 DI | 0.002 | 0.08427 | 0.14464 |
| JCM800 2203 Crunch | 0.0005 (current) | 0.05631 | 0.16916 |
| JCM800 2203 Crunch | 0.0001 | 0.05109 | 0.16833 |
| Mark IIC+ Hetfield Rhythm V2 | 0.0005 (current) | 0.08848 | 0.19309 |
| Mark IIC+ Hetfield Rhythm V2 | 0.0001 | 0.07948 | 0.17926 |
| Mark IIC+ Hetfield Rhythm V2 | 0.0002 | 0.16713 | 0.20971 |

The stronger weight was rejected as a general default after degrading both
independent metrics on the clean teacher, even though its validation-tail ESR
improved to 0.01674. Follow-up training compares the weaker candidate with the
current weight on crunch and high gain.

Raw metrics and exports are local in
`.tooling/fidelity-loss-300-20261006-clean` and
`.tooling/fidelity-loss-300-20261006-distorted`. Initial concurrent crunch and
high-gain jobs were interrupted and rerun serially because GPU contention
reduced throughput; those partial runs are excluded from the comparison.

A fresh diagnostic recording (`--probe-seed 20261007`) reproduced the clean
result: current weight ESR 0.02858 / spectral error 0.12336, weaker weight
0.00896 / 0.07791, stronger weight 0.07884 / 0.14220. That report is in
`.tooling/fidelity-loss-300-20261006-clean-followup`. This checks another input
recording, not another training initialization seed or perceptual guitar quality.

The fresh-recording crunch comparison also retained the waveform improvement:
current weight ESR 0.05971 / spectral error 0.17031, weaker weight 0.05408 /
0.17028. Spectral error is effectively unchanged for this teacher. Its report
is in `.tooling/fidelity-loss-300-20261006-crunch-followup`.

The fresh-recording high-gain comparison retained both improvements: current
weight ESR 0.08404 / spectral error 0.18885, weaker weight 0.07389 / 0.17326.
The complete distorted-teacher follow-up report is in
`.tooling/fidelity-loss-300-20261006-distorted-followup`.

Despite these independent improvements, weight 0.0001 was not adopted as the
default: the high-gain export's validation-tail ESR was 0.05384, above the
app's unchanged 0.05 acceptance limit (current weight: 0.02626). The intermediate
weight of 0.0002 passed that gate (validation ESR 0.03876) but worsened both
independent metrics, so it was also rejected as a default. Its report and
exports are in `.tooling/fidelity-loss-300-20261007-intermediate-high-gain`.
Fresh-recording evaluation confirmed that regression (ESR 0.15625 / spectral
error 0.20217); its report is in
`.tooling/fidelity-loss-300-20261007-intermediate-high-gain-followup`.

The app's default weight remains 0.0005. The tested 0.0001 setting is a useful
candidate for individual models, not an established general improvement.
All eight completed 300-epoch conversions used training seed 0; the fresh
recording checks vary diagnostic inputs, not training initialization.

Listening clips and named candidate NAM exports for clean and crunch are in
`.tooling/fidelity-loss-listening-20261007`. They use seconds 60..72 of the
training recording, with one shared playback gain per teacher. They are
listening aids, not independent test recordings.
