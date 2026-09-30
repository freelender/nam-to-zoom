# nam2zoom

nam2zoom converts one to five Neural Amp Modeler (`.nam`) files into a single
Zoom MS Plus custom effect named **N2Z Bank**. The pedal effect exposes
**Model, Bass, Mid, Treble, Vol, Input,** and **Mix** controls; only the
selected model runs at a time.

The current build targets fixed 44.1 kHz, 3-channel, 14-layer student models
and uses the pedal-tested two-sample kernel. The five-model, seven-control
build was reported working on MS-50G+ firmware 1.40 on 2026-09-29. Installation
also recognizes MS-70CDR+ firmware 1.20, based on its shared MS Plus protocol
and upstream custom-effect testing, but N2Z Bank itself has not been tested on
that pedal. This is still a preview release: new models, devices, saved patches,
and effect chains require their own checks before you trust them on hardware.

## Choose Your Path

| Goal | Start here | Tools needed |
| --- | --- | --- |
| Use the app | Download the Windows x64 portable ZIP from Releases and read the [User Guide](docs/USER_GUIDE.md) | None beyond the packaged app |
| Develop or audit | Clone this repository and read the [Development Guide](docs/DEVELOPMENT.md) | .NET SDK, Git, CMake, C++ tools, uv, TI CGT |
| Package a release | Complete developer setup, then run `.\release\build-portable.ps1` | Full developer setup |

## User Workflow

Use the release ZIP, not GitHub's source-code ZIP. Extract the whole folder to
a writable location and run `nam2zoom-desktop.exe`; do not copy the EXE away
from its bundled files.

Drop in one to five NAM files, choose their order, set unique five-character
pedal labels, optionally add mono cab IR WAVs, then build and preview. Direct
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
- Pedal installation supports Zoom MS-50G+ firmware 1.40 and experimentally
  supports Zoom MS-70CDR+ firmware 1.20. Device identity is detected
  automatically; other models and firmware versions are refused.
- The effect declares load 150; this is patch-admission metadata, not measured
  DSP utilization.
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
- MS-70CDR+ support is based on the shared protocol and hardware-tested custom
  ZD2 work in Stomphacks. N2Z Bank has not yet been run on an MS-70CDR+.

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
