# Development

## Repository layout

| Directory | Purpose |
| --- | --- |
| `apps/nam2zoom-avalonia` | Current .NET 10 desktop app |
| `apps/nam2zoom-core` | Shared conversion and deployment services |
| `apps/nam2zoom-desktop` | Legacy Windows frontend |
| `tools/nam2zoom` | Python conversion and effect-building backend |
| `dsp/nam_a2_own_host` | Full and Compact effect runtime |
| `training` | Training configurations and audio |
| `reference/nam_a2` | Native NAM renderer |
| `release` | Packaging, dependency pins and DSP templates |
| `tests` | Python, native DSP and .NET checks |
| `third_party` | Vendored dependencies and their notices |

Generated dependencies, build products, captures and pedal backups are ignored.
`.tooling` contains local toolchains, Python environments and dependency checkouts.
Do not commit those directories or user model weights.

## Prerequisites

- .NET 10 SDK, Git, CMake and a C++ build toolchain.
- Relocatable Python 3.12, such as the managed runtime provided by `uv`.
- On Windows, Visual Studio's Desktop development with C++ workload and Git Bash.
- For DSP compilation, a separately installed TI C6000 Code Generation Tools
  8.3.1 toolchain. It is not redistributed with the project.

The portable build script provisions dependencies from `release/dependencies.json`
and applies `patches`. Portable builds use precompiled DSP templates and do not
need the TI compiler. macOS packages require a native macOS runner.

## Stomphacks integration

Stomphacks is pinned to `26470497e7de90497fba7528386b8029b84f8939` in
`setup.ps1` and `release/dependencies.json`. Its installer checks the resident
catalogue for ID/filename collisions and reserves 100 KB of free space before
an install. nam2zoom uses that default; it does not lower the margin.
Existing-slot replacement still uninstalls first, then installs and verifies.

Local patches retain PREAMP artwork, catalogue flags, weight capacity and the
user-data log path. The builder preserves only the three existing N2Z
filename/ID pairs as exceptions to the new filename-prefix convention; stock
name checks and resident collision checks still apply. Existing IDs and files
are retained pending a separate author-range migration. Updating this dependency
does not validate another pedal model or regenerate the shipped DSP templates.

After changing patches, run `tests/test_ci_dependency_patches.py`, the bank and
slot tests, and Stomphacks `tools-pedal/install_selftest.py`. Build the upstream
`effects/gain/manifest.json` fixture first for the complete mock suite. These
checks must not contact a pedal.

## Source setup

For the full Windows toolchain, run:

```powershell
.\setup.ps1 -TiCgt 'C:\ti\ti-cgt-c6000_8.3.1'
dotnet run --project apps/nam2zoom-avalonia -c Release
```

Setup provisions the ignored tool directories, builds the renderer and legacy
frontend, and runs offline checks. It requires the prerequisites above.
`-TorchIndexUrl` selects an alternate PyTorch wheel index for training.

The current app uses `ConversionService` to inspect captures, retrain with the
Lite profile, review quality and export individual NAMs. `ReadyEffectService`
packages ready models separately. Effect modes must not alter retraining.

## Portable packages

```text
python release/build_cross_platform.py --rid win-x64 --python <managed-python-3.12>
```

Supported RIDs are `win-x64`, `osx-arm64` and `osx-x64`. Intel macOS requires a
source build of PyTorch; its CI job is currently disabled. On Windows, `--cuda`
bundles CUDA instead of the default CPU runtime.

Packages go into `dist/cross-platform`. Before creating a ZIP and SHA-256 file,
the build checks relocation, startup, training, rendering, export and both effect
modes. The packaged README comes from the [user guide](USER_GUIDE.md).

Set the release version in `Directory.Build.props` and document changes in
[CHANGELOG.md](../CHANGELOG.md). CI publishes tagged Windows and Apple Silicon
packages. Retain all bundled dependency licenses and notices.

## Tests

Use a training environment containing the project dependencies:

```text
python -m unittest discover -s tests -p "test_*.py"
dotnet run --project tests/retraining -c Release
dotnet run --project tests/effect-workflow -c Release
```

After a portable build, run the CI checks with:

```text
python release/run_ci_tests.py --rid win-x64
```

Native callback tests require Clang and a 32-bit host ABI. macOS skips those
replays. Deployment tests use mocked devices and must not write to a pedal.

## DSP and templates

The host accepts full A2 Lite 44.1 kHz models: 23 layers, three channels and 1,871
float32 weights. Full and Compact share the same exported models. See the
[host README](../dsp/nam_a2_own_host/README.md) and
[template README](../release/precompiled/README.md).

Model uses coefficient 12; word 3 is overwritten during tuner transitions on
supported firmware. Gain uses 13. Keep the mapping explicit and regenerate
both template sets after DSP changes. Source hashes include exact line endings.

## Benchmarks and diagnostics

`tools/benchmark_adaptation.py` compares retraining configurations and writes
local reports. Its `--help` lists available sweeps and evaluation options.
Experiments do not change app defaults.

Offline diagnostic kit builders:

- `tools/build_component_timing.py`: Full/Compact component timing.
- `tools/build_model_probe.py`: model selection across tuner changes.
- `tools/build_lite_timing.py`: legacy comparisons using matching baselines.

Each kit includes operating instructions and a decoder. Use an unsaved patch
and restore the normal bank afterward. Kits contain the supplied model weights.
Elapsed timing includes firmware interruptions and instrumentation; it is not
an absolute DSP percentage.

## Legacy code

The WinForms frontend, earlier model profiles and regression fixtures remain for
compatibility. `release/build-portable.ps1` packages that frontend. Current
releases use Avalonia and full Lite retraining. The older 14-layer Compact
architecture is separate from the current Compact effect-runtime option.
