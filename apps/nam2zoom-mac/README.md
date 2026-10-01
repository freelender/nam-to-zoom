# nam2zoom (macOS)

A native macOS app for nam2zoom, mirroring `apps/nam2zoom-desktop` (the
Windows/WinForms app): same Python backend (`tools/`), same DSP sources
(`dsp/`), same guarded install/uninstall safety flow. Only the GUI differs -
this one is SwiftUI instead of WinForms.

## Why `release/templates/*.ZD2`/`*.ZIC` are checked in

The TI C6000 compiler this project normally uses to build the DSP templates
has no macOS build. `tools/nam2zoom/bank.py::build_bank()` already prefers
`release/templates/index.json` when present and only falls back to invoking
the compiler otherwise, so checking in the already-built templates (extracted
from a published Windows portable release, and verified byte-for-byte against
`dsp/`'s current source hashes via the same check `fill_template()` does)
lets `build-bank` work on macOS with zero compiler dependency. Editing the
DSP kernel source itself still needs the TI toolchain somewhere, same as on
Windows - this only unblocks the common case of packaging NAM models.

## Setup

Prerequisite: Xcode Command Line Tools and Homebrew (`cmake`, `ninja`,
`python@3.13`, `python@3.12`).

```bash
xcode-select --install
brew install cmake ninja python@3.13 python@3.12
./setup-mac.sh
```

(`setup-mac.sh` lives at the repository root, next to `setup.ps1`.) It
provisions `.tooling/` with the same pinned external checkouts and patches
as the Windows setup (stomphacks, neural-amp-modeler, NeuralAmpModelerCore,
and the `mungewell/zoom-zt2` clone stomphacks itself requires), builds two
Python venvs with the stdlib `venv` module, and builds `core_render` with
CMake + Ninja + clang. It never writes to a pedal.

`.tooling/` is shared with the Windows setup path in source form only - the
two platforms' venvs live under the same `.tooling/stomphacks/.venv` and
`.tooling/nam-train-venv` paths but with platform-specific internal layouts
(`bin/python3` vs `Scripts/python.exe`), so a given checkout only ever
populates the layout for the OS it was set up on; nothing is shared or
overwritten between platforms.

## Building and running the app

```bash
cd apps/nam2zoom-mac
./build-app.sh
open nam2zoom.app
```

`build-app.sh` builds a release binary and wraps it into a double-clickable
`nam2zoom.app` (ad-hoc signed; not notarized). Plain `swift run` also works
for development, but SPM's raw executable isn't registered as an app with
the Dock/Window Server, so its window may not reliably appear - prefer
`build-app.sh` + `open`.

Re-run `build-app.sh` after any source change; it overwrites `nam2zoom.app`
in place.

## Notes

- The bundled training DI audio is not duplicated here - it's read directly
  from `apps/nam2zoom-desktop/Assets/TRAINING_DI.wav` (see
  `AppViewModel.ensureBundledTrainingDi()`), verified against the same
  SHA-256 the Windows app checks.
- Pedal installation follows the exact same guarded flow as the Windows app
  (build, hash-approve, install, full backup, read-back verification). See
  the repository root [README](../../README.md) and
  [docs/DEVELOPMENT.md](../../docs/DEVELOPMENT.md) for the safety checklist
  before writing to real hardware.
