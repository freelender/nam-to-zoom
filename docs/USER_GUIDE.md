# Using nam2zoom

## Start Here

Use the **Windows x64 portable ZIP** from the project's GitHub Releases, not the source-code ZIP. Extract the whole folder to a writable location such as Downloads, then run `nam2zoom-desktop.exe`. Keep all the files together. No developer tools, separate Python installation, or separate .NET installation are needed.

This package is a preview. Test the new Mix-control effect before saving a patch. Installation supports Zoom MS-50G+ firmware 1.40 and Zoom MS-70CDR+ firmware 1.20, and experimentally supports Zoom MS-60B+ firmware 1.20. No pedal firmware or NAM models are included.

The project EXE is not code-signed; Windows may warn about an unfamiliar app. Obtain the ZIP from the project's own release and verify it before approving a warning.

If the Microsoft Visual C++ x64 runtime is missing or too old, the app offers to download its installer directly from Microsoft, verifies its Microsoft signature, and requests Windows administrator approval to install it. Approve only a Microsoft Corporation publisher prompt. A restart may be required. This is a native-library prerequisite, not the Visual Studio developer toolchain.

## Add And Convert Models

1. Drop one to five `.nam` files into the app. Reorder them and give each a unique pedal label of at most five ASCII characters.
2. Optionally select a mono Cab IR WAV for a model. The app includes that cab response in the conversion target; the pedal does not run a separate IR convolver. Do not add a second cab if the NAM already includes one unless that is intentional.
3. Choose training epochs (100 by default, maximum 300) and **Build effect**. Compatible 44.1 kHz compact models go straight to packaging. Other supported models need conversion; incompatible/invalid architectures are refused, not silently accepted.
4. On the first conversion, approve the training-package download. Choose **No** for CPU or **Yes** for NVIDIA CUDA packages. CPU is broadly usable but slower; GPU acceleration needs a compatible installed NVIDIA driver. The app reports whether CUDA is available. It does not install drivers. Downloads can consume several GB and are kept under `.tooling` inside the extracted app folder. You can cancel setup/build; retrying resumes package setup. No pedal writes happen during this step.
5. Wait for conversion and preview the original/converted audio before installing. The app caches conversions under `%LOCALAPPDATA%\nam2zoom\adapt-cache`; changing training settings or IR contents produces a different cache entry. Quality gates can reject a poor match. **Best effort** allows a lower-fidelity supported conversion; it does not enlarge the pedal network or make unsupported models compatible.

Conversion trains a **44.1 kHz, 3-channel, 14-layer** student against the source model. A 48 kHz source is rendered at its native rate and its target audio resampled before training. This is model adaptation, not simply editing the NAM sample-rate field. The source files are never modified.

Each successful conversion is also saved in `Converted_NAM` beside `nam2zoom-desktop.exe`, using the original filename (for example, `Converted_NAM/Marshal_1982_Blabla.nam`). Cached conversions are exported there too. Identical exports are reused; different conversions with the same filename receive numbered suffixes, preserving earlier files. You can keep these NAMs, share them where the source model's license permits, or add them directly to a later bank without retraining. A conversion made with a Cab IR already includes that cab response. Best-effort conversions retain their lower-fidelity result, so compare the audio previews before sharing or using them.

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

Load 150 is declared scheduling metadata, not a measured DSP percentage. The earlier six-control binary passed a saved chain with N2Z, ZNR, RackComp, TS Drive, Hall REV, and LowPassFL. Substituting FD B-MAN led to PROCESS OVERFLOW on N2Z after reboot. Multiple N2Z instances are unsupported. Every new binary and chain needs its own audio, patch recall, and reboot test before being treated as working.

The default seven-control effect uses the two-sample kernel reported working on an MS-50G+ with firmware 1.40 on 2026-09-29. This leaves model weights and geometry unchanged. Users have also confirmed N2Z Bank working on MS-70CDR+, and portable conversions working with both CPU and NVIDIA GPU training. MS-60B+ support uses the shared MS Plus protocol but awaits N2Z Bank hardware testing. Treat MS-60B+ installation as experimental, start with N2Z as the only effect in an unsaved patch, and report the exact pedal firmware and result. On MS-60B+, N2Z Bank appears in PREAMP. Guarded installation reduces risk but does not eliminate the possibility of freezing or permanently disabling a pedal.

## Troubleshooting

- Run from an extracted, writable folder, not inside the ZIP or under Program Files. Do not copy only the EXE.
- A failed dependency download can be retried with **Build**. Check internet access and free disk space. Do not use `setup.ps1`; that script is for developers.
- If CUDA is unavailable, the downloaded GPU build can still run on CPU; update the NVIDIA driver separately if appropriate for your hardware.
- Close other programs using the Zoom MIDI port if connection checks fail. Confirm USB connection and supported firmware: 1.40 on MS-50G+, or 1.20 on MS-70CDR+ or MS-60B+.
- Audio conversion quality and GPU speed vary by model and PC. More epochs are not a guarantee of a closer match.
