# Using nam2zoom

## Start Here

Use the **Windows x64 portable ZIP** from the project's GitHub Releases, not the source-code ZIP. Extract the whole folder to a writable location such as Downloads, then run `nam2zoom-desktop.exe`. Keep all the files together. No developer tools, separate Python installation, or separate .NET installation are needed.

This package offers **Compact** (the default 14-layer network) and **Lite (alone)** (an experimental 23-layer network). Both run at 44.1 kHz with three channels; Lite must be the only active effect. Installation supports Zoom MS-50G+ firmware 1.40 and Zoom MS-70CDR+ firmware 1.20, and experimentally supports Zoom MS-60B+ firmware 1.20. No pedal firmware or NAM models are included.

The project EXE is not code-signed; Windows may warn about an unfamiliar app. Obtain the ZIP from the project's own release and verify it before approving a warning.

If the Microsoft Visual C++ x64 runtime is missing or too old, the app offers to download its installer directly from Microsoft, verifies its Microsoft signature, and requests Windows administrator approval to install it. Approve only a Microsoft Corporation publisher prompt. A restart may be required. This is a native-library prerequisite, not the Visual Studio developer toolchain.

## Add And Convert Models

1. Drop one to ten `.nam` files into the app. Reorder them and give each a unique pedal label of at most five ASCII characters.
2. Optionally select a mono Cab IR WAV for a model. The app includes that cab response in the conversion target; the pedal does not run a separate IR convolver. Do not add a second cab if the NAM already includes one unless that is intentional.
3. Choose **Compact** or **Lite (alone)**, training epochs (100 by default, maximum 300), and **Build effect**. Compatible 44.1 kHz models matching the selected profile go straight to packaging. Other supported models need conversion; incompatible/invalid architectures are refused, not silently accepted.
4. On the first conversion, approve the training-package download. Choose **No** for CPU or **Yes** for NVIDIA CUDA packages. CPU is broadly usable but slower; GPU acceleration needs a compatible installed NVIDIA driver. The app reports whether CUDA is available. It does not install drivers. Downloads can consume several GB and are kept under `.tooling` inside the extracted app folder. You can cancel setup/build; retrying resumes package setup. No pedal writes happen during this step.
5. Wait for conversion and preview the original/converted audio before installing. The app caches conversions under `%LOCALAPPDATA%\nam2zoom\adapt-cache`; changing training settings or IR contents produces a different cache entry. If any converted NAM exceeds the ESR limit of 0.05 (or has correlation below 0.95), one dialog after all conversions lists the affected filenames and scores. The A/B preview folder opens for comparison. Choose **Yes** to use those conversions and finish building, or **No** to stop while keeping the previews and cached results. Passing models need no quality approval. Unsupported models and invalid audio still stop the build.

Conversion trains a **44.1 kHz, 3-channel** student against the source model: 14 layers for Compact or 23 layers for Lite. A 48 kHz source is rendered at its native rate and its target audio resampled before training. This is model adaptation, not simply editing the NAM sample-rate field. The source files are never modified.

The 14-layer network exports 659 weights. Compatible previous 14-layer
conversions can be packaged directly. For models converted with the experimental
16-layer preview, add the original NAM to convert again. Existing compatible
14-layer adaptation caches can be reused when their training settings match.

Choose **Compact** or **Lite (alone)** beside Epochs before building. The choice
applies to the entire bank and is saved with the model list.

- **Compact** is the established 14-layer, 3-channel network (659 weights),
  with a declared load of 150 raw. Choose it for patches with other effects,
  and test the exact chain before saving it.
- **Lite (alone)** uses the full native A2 Lite geometry: 23 layers, 3 channels,
  convolution kernels of 6/15 and a 16-sample output head (1,871 weights).
  It retrains at 44.1 kHz. For packed A2 imports, the teacher is the original
  Lite submodel; other supported NAM architectures are rendered as usual.

All models in one bank use the selected architecture; Compact and Lite cannot
be mixed in the same bank. Lite's name refers to NAM's A2 architecture, not
lower pedal DSP use than Compact.

Lite is a retrained model, not an unchanged native 48 kHz model. The optimized
kernel has been reported working alone with JCM800, Twin Reverb and Mark IIC+
captures. Adding even one other effect caused pedal slowdown and intermittent
crackling. Treat Lite as a standalone effect and choose Compact when you need
other pedal effects in the same patch.

Lite now reserves the full DSP budget (270 raw). This is conservative scheduling
metadata, not a measured CPU percentage; it does not speed up the kernel.
Firmware admission and saved-patch/reboot behavior still need testing. Avoid
library-preview combinations with other active effects even if the firmware
allows them. Lite needs 76,728 bytes of history versus Compact's 20,076 bytes.
Existing Lite conversions can be rebuilt without retraining or changing ESR.

Each architecture has its own conversion cache and templates. Switching the
choice rechecks every imported NAM; an export of the other architecture needs
adaptation. Prefer adding the original NAM when comparing architectures.
New converted models are saved under `Converted_NAM/Compact` or
`Converted_NAM/Lite`, with existing exports preserved.

Conversions use standard spectral loss (weight 0.0005). The weaker spectral
loss experiment has been removed after mixed results across clean, crunch and
heavy-distortion models. Existing standard conversion caches can still be
reused. Previously exported Ready NAMs are not retrained when imported;
add the original NAM to replace a weaker-loss conversion with standard training.

The bundled training audio repeats its opening nine seconds at the end, so the conversion's tail-validation score is not an independent fidelity test. Compare the audio previews when assessing a conversion. Training configuration changes now trigger fresh cache entries; existing converted files are preserved.

Accepted conversions are also saved under the selected architecture in `Converted_NAM` beside `nam2zoom-desktop.exe`, using the original filename (for example, `Converted_NAM/Compact/Marshal_1982_Blabla.nam`). Cached conversions are exported there too. Identical exports are reused; different conversions with the same filename receive numbered suffixes, preserving earlier files. You can keep these NAMs, share them where the source model's license permits, or add them directly to a later bank without retraining. A conversion made with a Cab IR already includes that cab response. Accepting a result outside the quality limits does not change its accuracy, so compare the audio previews before sharing or using it.

## Install Or Remove

Before replacing/removing N2Z Bank, disable autosave, select a stock patch, and remove custom effects from saved patches. The safety path checks the current patch and all 100 saved patches and refuses unsafe replacement. It accepts only MS-50G+ firmware 1.40, MS-70CDR+ firmware 1.20, or MS-60B+ firmware 1.20 and detects the model automatically.

**Build + Install** asks for separate approval of the exact effect/icon hashes. If the effect already exists, the app replaces it instead of adding a duplicate. The app validates the effect, identity, autosave, patches, effect list, and readback. **Uninstall effect** removes the existing N2Z Bank using the same guarded checks; it does not reset the pedal or delete stock effects.

Banks installed by the previous portable version (`0x07000F87`) are recognized for replacement and uninstall. New banks use `0x04001787` in PREAMP. You do not need to uninstall with the old app first. Before upgrading, remove N2Z Bank from saved patches and select a stock patch as described above; saved patches referencing the old ID are not automatically migrated.

Keep the **Backup** checkbox checked for a full device backup in `Backup` beside the EXE. With it unchecked, the app retains a smaller operation session but does not create a full-device backup. Keep USB and power connected until the operation completes. On a transfer failure, preserve the log/session and keep the device connected; consult the included `.tooling/stomphacks/SAFETY.md` instead of repeatedly reconnecting, writing, or power-cycling.

## Pedal Controls

| Control | Behavior | Default |
| --- | --- | --- |
| Model | Select the active bank model | First model |
| Bass, Mid, Treble | Tone shaping after NAM | 50 (flat) |
| Vol | Modeled output level | 50 (unity) |
| Input | Level entering NAM | 50 (unity) |
| Mix | Dry/wet blend after tone and Vol | 100 (fully wet) |

The amp receives the average of the left and right channels and sends its mono output to both outputs. Identical signals on both channels keep their level; a signal on only one channel enters the amp 6 dB lower. The dry path stays stereo and is not changed by Input, tone, or Vol. Mix 0 is dry; Mix 100 is fully modeled. Only one model runs at a time. Model weights remain inside the effect file; changing the bank replaces the entire effect, not separate files on the pedal.

## Known Limits

Compact declares load 150; Lite reserves the full patch budget of 270 and must run alone. These values are scheduling metadata, not measured DSP percentages. The earlier six-control Compact binary passed a saved chain with N2Z, ZNR, RackComp, TS Drive, Hall REV, and LowPassFL. Substituting FD B-MAN led to PROCESS OVERFLOW on N2Z after reboot. The user reported two active 14-layer N2Z effects running cleanly; saving that combination was blocked by the declared load. That observation does not validate saved-patch behavior. Every new binary and chain needs its own audio, patch recall, and reboot test before being treated as working.

The default seven-control effect uses the two-sample kernel reported working on an MS-50G+ with firmware 1.40 on 2026-09-29. This leaves model weights and geometry unchanged. Users have also confirmed N2Z Bank working on MS-70CDR+, and portable conversions working with both CPU and NVIDIA GPU training. MS-60B+ support uses the shared MS Plus protocol but awaits N2Z Bank hardware testing. Treat MS-60B+ installation as experimental, start with N2Z as the only effect in an unsaved patch, and report the exact pedal firmware and result. On MS-60B+, N2Z Bank appears in PREAMP. Guarded installation reduces risk but does not eliminate the possibility of freezing or permanently disabling a pedal.

## Troubleshooting

- Run from an extracted, writable folder, not inside the ZIP or under Program Files. Do not copy only the EXE.
- A failed dependency download can be retried with **Build**. Check internet access and free disk space. Do not use `setup.ps1`; that script is for developers.
- If CUDA is unavailable, the downloaded GPU build can still run on CPU; update the NVIDIA driver separately if appropriate for your hardware.
- Close other programs using the Zoom MIDI port if connection checks fail. Confirm USB connection and supported firmware: 1.40 on MS-50G+, or 1.20 on MS-70CDR+ or MS-60B+.
- Audio conversion quality and GPU speed vary by model and PC. More epochs are not a guarantee of a closer match.
