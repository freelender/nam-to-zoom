# nam2zoom

Cross-platform migration preview: the new .NET 10 Avalonia frontend lives in
`apps/nam2zoom-avalonia`; the original WinForms app is preserved. See the
[repository audit and migration plan](docs/CROSS_PLATFORM.md) and
[portable Windows/macOS instructions](docs/PORTABLE.md). The
`Portable Windows and macOS` Actions workflow builds three target-native ZIPs
and publishes matching `vX.Y.Z` tags after all targets pass validation.
macOS builds and all macOS USB-MIDI operations require CI/manual validation;
they are not claimed hardware-tested.

## Supported Devices

| Zoom pedal    | Status                             |
| :------------ | :--------------------------------- |
| **MS-50G+**   | **Supported** - tested and working |
| **MS-70CDR+** | **Supported** - tested and working |
| **MS-60B+**   | **Experimental** - awaiting N2Z Bank hardware testing |

_More devices to come._

---

nam2zoom converts one to ten Neural Amp Modeler (`.nam`) files into a single
Zoom MS Plus custom effect named **N2Z Bank**. The pedal effect exposes
**Model, Bass, Mid, Treble, Vol, Input,** and **Mix** controls; only the
selected model runs at a time.

Choose **Compact** (the default) or **Lite (alone)** for the entire bank.
Both profiles run at 44.1 kHz with three channels and a two-sample kernel.
Compact uses the pedal-tested 14-layer network. The five-model, seven-control
build was reported working on MS-50G+ firmware 1.40 on 2026-09-29. N2Z Bank
has also been tested and confirmed working on MS-70CDR+. This is still a
preview release: new models, devices, saved patches,
and effect chains require their own checks before you trust them on hardware.

## Compact And Lite

| Profile | Network | Weights per model | Declared DSP load | Intended use |
| --- | --- | --- | --- | --- |
| **Compact** (default) | 14 layers, 3 channels, 44.1 kHz | 659 | 150 raw | Use with other pedal effects, subject to testing the exact chain |
| **Lite (alone)** | 23 layers, 3 channels, 44.1 kHz | 1,871 | 270 raw (full patch budget) | Use as the only active effect |

Lite follows the native NAM A2 Lite network geometry, retrained at 44.1 kHz.
Its name does not mean it uses less pedal DSP than Compact. The optimized
Lite kernel has been reported working alone with JCM800, Twin Reverb and
Mark IIC+ captures; adding even one other effect caused slowdown and
crackling. Lite remains experimental, and firmware admission, saved-patch
recall and reboot behavior still need hardware verification.

Select the profile beside Epochs before building. All one to ten models in
the bank use that profile; Compact and Lite cannot be mixed in one bank.
Each has separate conversion caches, templates and exported NAM folders.
Compatible 44.1 kHz NAMs for the selected profile package directly; other
supported models require adaptation. See the [User Guide](docs/USER_GUIDE.md)
for conversion and installation details.

#### N2Z Bank effect location

![n2z bank location in pedal](https://github.com/freelender/nam-to-zoom/blob/main/git-assets/n2z-location.gif?raw=true)

## Choose Your Path

| Goal              | Start here                                                                                        | Tools needed                                |
| ----------------- | ------------------------------------------------------------------------------------------------- | ------------------------------------------- |
| Use the app       | Download the Windows x64 portable ZIP from Releases and read the [User Guide](docs/USER_GUIDE.md) | None beyond the packaged app                |
| Develop or audit  | Clone this repository and read the [Development Guide](docs/DEVELOPMENT.md)                       | .NET SDK, Git, CMake, C++ tools, uv, TI CGT |
| Package a release | Complete developer setup, then run `.\release\build-portable.ps1`                                 | Full developer setup                        |

## User Workflow

Use the release ZIP, not GitHub's source-code ZIP. Extract the whole folder to
a writable location and run `nam2zoom-desktop.exe`; do not copy the EXE away
from its bundled files.

Drop in one to ten NAM files, choose their order, set unique five-character
pedal labels, choose Compact or Lite (alone), optionally add mono cab IR WAVs,
then build and preview. Direct
compatible NAMs package immediately. Other supported NAMs are adapted on the
PC into the fixed pedal network; the app asks before downloading training
packages and offers CPU or NVIDIA CUDA setup. The source NAM and IR files are
not modified.

When installing, the app replaces the complete N2Z Bank effect on the pedal.
It does not load separate model files at runtime. Read the full
[user workflow and safety checks](docs/USER_GUIDE.md) before writing anything
to hardware.

## Contributor Workflow

Run `setup.ps1` only from a source checkout after installing the prerequisites
listed in [Development](docs/DEVELOPMENT.md). Setup provisions ignored local
tooling under `.tooling`, builds the native renderer and desktop app, and runs
offline tests. It does not write to a pedal.

The repository intentionally does not include generated toolchains, backups,
portable ZIPs, generated release templates, user NAM models, or compiled pedal
artifacts. Local outputs live under ignored paths such as `.tooling`, `Backup`,
`dist`, `release/templates`, and `n2z-bank-*`.

Release packaging is maintainer-only:

```powershell
.\release\build-portable.ps1
```

The script generates zero-weight templates with the maintainer's TI compiler,
bundles the self-contained GUI, Python runtimes, renderer, backend tools, and
license notices, then writes a portable ZIP under `dist`. The TI compiler and
user model weights are never distributed.

## Compatibility And Safety

- Windows 10/11 x64.
- Pedal installation supports Zoom MS-50G+ firmware 1.40,
  Zoom MS-70CDR+ firmware 1.20, and experimentally Zoom MS-60B+
  firmware 1.20. N2Z Bank has not yet been hardware-tested on MS-60B+.
  Device identity is detected
  automatically; other models and firmware versions are refused.
- Compact declares load 150; Lite declares 270 and must run alone. These are
  patch-admission values, not measured DSP utilization.
- Custom effects can cause slowdown, crackling, overflow, freezing, or
  permanent device failure. Readback verification does not prove safe real-time
  behavior.
- Disable autosave, select a stock patch, and clear saved custom/N2Z patches
  before replacing or removing the effect.
- Keep USB and power connected during transfers. Preserve logs and backups
  after any failed write and do not blindly retry.
- The earlier six-control build passed one saved six-effect chain with
  LowPassFL; replacing LowPassFL with FD B-MAN caused PROCESS OVERFLOW on N2Z
  after reboot. New binaries and combinations need their own tests.

## Support

If you would like to support my work, you can leave an optional tip. Donations
will help fund additional pedals, audio gear, and other equipment needed to
test and improve nam2zoom. They are appreciated, but never required to use
the project.

[![Support my work](https://img.shields.io/badge/Support_my_work-Donate-22a06b?style=for-the-badge)](https://streamelements.com/fret_lex/tip)

## Acknowledgements

Special thanks to [Thomas Hammer](https://github.com/thammer) for his work on
[zoom-explorer](https://github.com/thammer/zoom-explorer) and
[stomphacks](https://github.com/thammer/stomphacks). His research into the
Zoom MS Plus pedal protocol and custom-effect tooling provided an important
foundation for this project.

## License

Project code is released under the [MIT License](LICENSE), copyright 2026
Aleksandar Vukasinovic. Third-party dependencies keep their own licenses, and
portable packages include notices. User-selected NAM models are not part of
this project or its releases.

Lite banks support at most **3 NAM models**; Compact banks support at most **10**. Only the selected model runs. This model-count limit does not resolve the reported Lite saved-patch/startup failure; keep Lite patches unsaved.
