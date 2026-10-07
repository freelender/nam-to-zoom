# Development

This guide is for contributors and release maintainers. Musicians using the
portable app should follow [User Guide](USER_GUIDE.md); they do not need the
developer prerequisites or `setup.ps1`.

Windows desktop source project for converting up to ten Neural Amp Modeler
(`.nam`) files into **one** Zoom MS Plus effect, `N2ZBANK`.
The ten model slots are selected with the effect's **Model** control. The
other controls are **Bass, Mid, Treble, Vol, Input, Mix**. Pedal labels are unique
ASCII strings of at most five characters.

Each selected model runs as a **44.1 kHz, 3-channel, 14-layer** NAM student
on the pedal. The builder uses the two-sample kernel and declares a raw DSP
load of **150**. The load declaration is patch-admission metadata, not a
measured CPU percentage. Check DSP headroom for each effect-chain configuration.

This is a source project, not a prebuilt portable release. Building and
converting NAM files require the tools below. Installation targets the device
and firmware profiles listed under Requirements. Custom
effects can freeze or permanently disable a pedal; guarded checks reduce
risk but do not remove it.

## Requirements (Windows)

- Windows 10/11 x64; Zoom MS-50G+ **firmware 1.40**, Zoom
  MS-70CDR+ **firmware 1.20**, or experimentally Zoom MS-60B+
  **firmware 1.20**, for pedal installation.
- Install the [.NET 10 SDK](https://learn.microsoft.com/en-us/dotnet/core/install/windows)
  (the SDK includes the runtime),
  [Git for Windows](https://git-scm.com/install/windows) (including Git Bash),
  [CMake 3.24+](https://cmake.org/download/), and
  [uv](https://docs.astral.sh/uv/getting-started/installation/). Put their
  commands on `PATH`; reopen PowerShell after installing them.
- Install [Visual Studio](https://visualstudio.microsoft.com/downloads/) with
  the **Desktop development with C++** workload. The setup script locates its
  MSVC compiler and Ninja through `vswhere`.
- Download TI **C6000 Code Generation Tools 8.3.1 for Windows** from the
  [TI compiler archive](https://software-dl.ti.com/codegen/non-esd/downloads/download_archive.htm).
  Install it separately under TI's terms. Locate the install root containing
  `bin/cl6x.exe`; pass that path to setup.
- Internet access for the one-time pinned source checkouts and Python packages.
  `uv` installs Python 3.12 for training and 3.13 for the effect builder into
  ignored `.tooling/python` on a clean clone. No separate Python installation
  is needed.
- For installation: USB-MIDI connection, pedal power, and a writable location
  for the app EXE, since `Backup` is created **beside the EXE** when enabled.

An NVIDIA GPU with a suitable CUDA-enabled PyTorch build is recommended for
training. CPU training is possible but may be very slow. `setup.ps1` accepts
`-TorchIndexUrl` if you have chosen a compatible PyTorch wheel index from
[PyTorch's Windows installation guide](https://pytorch.org/get-started/locally/).
Setup does not include or install any Zoom firmware or TI compiler files.

## Setup and launch

1. Install the prerequisites above. On Windows with WinGet, .NET and uv can
   be installed with these commands; install Git, CMake, Visual Studio C++
   tools, and TI CGT from their linked installers above:

   ```powershell
   winget install --id Microsoft.DotNet.SDK.10 -e
   winget install --id astral-sh.uv -e
   ```

2. Open a **new** PowerShell window and verify the commands are visible:

   ```powershell
   git --version
   uv --version
   cmake --version
   dotnet --version
   ```

3. Clone and run setup. Replace the TI example path with the directory that
   contains `bin/cl6x.exe` on your PC:

   ```powershell
   git clone https://github.com/freelender/nam-to-zoom.git
   cd nam-to-zoom
   .\setup.ps1 -TiCgt 'C:\ti\ti-cgt-c6000_8.3.1'
   ```

   If PowerShell blocks the local script, review it and run
   `Set-ExecutionPolicy -Scope Process Bypass` in that window, then rerun
   setup. Setup validates the manual toolchain before network-heavy work;
   it provisions Python and builds the renderer/app without touching the
   pedal. Expect substantial downloads and disk use on the first run.

4. Launch the app from its build output directory:

   ```powershell
   .\apps\nam2zoom-desktop\bin\Release\net10.0-windows\nam2zoom-desktop.exe
   ```

   Keep the output inside this clone; copying the EXE alone elsewhere breaks
   its lookup of source and `.tooling`. For UI-only edits, rebuild with:

   ```powershell
   dotnet build .\apps\nam2zoom-desktop\nam2zoom-desktop.csproj -c Release
   ```

`setup.ps1` pins and patches three external checkouts under ignored
`.tooling/`: Stomphacks, neural-amp-modeler, and NeuralAmpModelerCore. It
creates their Python environments, builds `core_render.exe`, builds the
desktop app, and runs the offline tests. The `-TiCgt` argument points to the
directory containing `bin/cl6x.exe`; setup creates a junction at the path
expected by the effect builder. You may rerun setup. It refuses an existing
checkout at a different revision or with conflicting changes instead of
silently replacing it.

On an existing development PC, setup verifies installed environments and
reuses them instead of downloading/reinstalling Python packages. A fresh
checkout provisions its own ignored `.tooling` directory. It is generated,
can be large, and must not be committed.

## Normal workflow

1. Drop in one to ten `.nam` files. Reorder them and edit each pedal label.
   The app classifies each as direct, adaptable, or unsupported. A direct NAM
   already has the exact 44.1 kHz, 14-layer, three-channel compact shape.
2. Optionally choose a **Cab IR** WAV for any selected model. The IR belongs
   only to that model and is saved in the model list by path. Choose **Clear**
   to return to the original no-IR path. Use a mono WAV at 44.1, 48, 88.2, or
   96 kHz, at most 500 ms and 10 MiB. The app resamples it to 44.1 kHz,
   removes up to 10 ms of leading silence, and retains up to 1,536 taps
   (about 35 ms). It refuses an IR with more than 1% of its energy beyond
   that span rather than silently losing a significant tail. An IR also
   forces PC adaptation for an otherwise direct-ready NAM. The source `.nam`
   and IR are never modified.
3. Set **Epochs** (100 by default, up to 300) for models needing PC adaptation. The app
   renders each original NAM on its embedded, fixed 44.1 kHz mono training DI.
   A 48 kHz teacher is rendered at 48 kHz and resampled for training. Its
   original file is never modified. With a Cab IR, the app convolves it into
   the teacher audio *after* NAM rendering and before training, so the pedal
   runs only the resulting compact student, not a separate convolution effect.
   Adaptation trains a compact student and
   validates its last nine seconds (ESR <= 0.05 and correlation >= 0.95).
   The bundled DI repeats its intro at the tail, so this score is not an
   independent fidelity measurement. See [Fidelity benchmark](FIDELITY_BENCHMARK.md)
   for comparisons on independent audio and the experimental guarded split.
   Configuration hashes now participate in cache keys.
   Changing epochs or IR content produces a separate cache entry. Training can take a long
   time, particularly without GPU acceleration.
   The A/B preview's `original.wav` is the NAM-plus-IR target when an IR is
   selected. The fixed pedal network has limited history, so a longer or
   complex IR may fail the quality gate or sound less accurate; review the
   preview before installation. If the NAM already contains a cabinet,
   selecting another IR stacks the two cabinet responses.
   If the IR boosts the teacher above the trainer's safe level, the app
   attenuates the baked target to a 0.95 peak and reports the dB reduction
   in the log and build result. This preserves the IR's frequency response
   but makes that model quieter; the effect's Vol control has limited makeup
   range, so audition its level before installation.
4. After all conversions, a quality-review dialog lists each NAM outside the
   ESR/correlation limits and opens the A/B preview folder. Accept to export
   the conversions and finish building; decline to keep only previews and
   cached conversions. The desktop passes `--review-quality` to collect
   valid results; CLI adaptation without it still enforces the quality gate.
   File, structural, audio and installation checks remain required. The A/B
   preview is a PC rendering, not a pedal recording.
5. **Build effect** creates `N2ZBANK.ZD2` and `N2ZBANK.ZIC` in a new output
   folder; it does not write to a pedal. The app includes the supplied
   monochrome artwork in both artifacts. All models become one bank effect,
   with only the selected model processed at a time. Every build uses the
   optimized 3-channel kernel and the 150 load declaration.
6. **Build + Install** builds first, then separately asks for approval of the
   exact SHA-256 hashes. It accepts only MS-50G+ firmware 1.40, MS-70CDR+
   firmware 1.20, or MS-60B+ firmware 1.20 and selects the profile from the
   identity response. MS-60B+ support awaits N2Z Bank hardware testing. Read the
   safety section below before using it.

The Compact student has **659 float32 weights per model**. Ten slots therefore store
6,590 weights, with only the selected network running. The effect shares
one 20,076-byte history buffer across selected models; switching
briefly mutes while that history clears and warms. The seven controls are
Model, Bass/Mid/Treble (neutral at 50), Vol (unity at 50), Input (unity at 50),
and Mix (dry/wet, default 100). Mix 0 passes the unprocessed dry signal;
Mix 100 gives the fully modeled signal after tone and volume processing.
The app's training epochs affect PC conversion, not pedal processing cost.

## Pedal installation and recovery

To install from the desktop app:

1. Connect and power a supported MS-50G+, MS-70CDR+, or MS-60B+ with a USB data cable.
   Confirm Windows sees its MIDI port. On the pedal, turn autosave **OFF**, select a stock patch,
   and make sure no saved patch contains any custom effect. In particular,
   erase a saved N2Z Bank patch before replacing or uninstalling the bank.
   Do not run another pedal editor or MIDI application at the same time.
2. In the app, add/reorder up to ten NAM files, set their five-character
   pedal labels and training options, then use **Build effect** first. Inspect
   the generated A/B previews and build log. This step is offline.
3. Leave **Full backup** checked unless you have a deliberate reason not to.
   Choose **Build + Install**, review the exact artifact hashes and risk
   prompt, and approve only if you accept the device risk. The app tests the
   connection and device state before writing. Keep pedal power and USB
   connected until readback verification finishes.
4. Audition one model on the pedal, then switch Model slots and check both
   audio and menu responsiveness. Keep autosave off and do not save a patch
   with a newly built experimental effect until that exact build has been
   tested for saved-patch behavior. Later builds replace `N2ZBANK` rather
   than adding another copy.

**Uninstall from pedal** removes the installed `N2ZBANK` without building a
new effect or clearing the app's model list. It uses the same backup checkbox:
with backup enabled, the complete device backup is saved in `Backup` beside
the EXE; otherwise the previous effect list and bank files are retained in a
local session. Before removal it requires autosave OFF, a stock current patch,
all 100 saved patches stock-only, and a matching N2Z Bank binary/icon pair.
It dry-runs the operation and verifies both file removal and the effect-list
change afterward. If N2Z Bank is absent, it performs no pedal write. Keep the
pedal connected until verification finishes.

The installer uses Stomphacks' guarded DIY transfer tools. Before a write it
verifies the exact approved ZD2/ZIC hashes, pedal identity/firmware, autosave
OFF, current and all 100 saved patches being stock-only, the device effect
list, and the candidate effect structure. It refuses legacy N2Z effects and
uninstalls an existing `N2ZBANK` before installing its replacement, so it does
not intentionally accumulate bank copies. It reads back both files and
checks the effect-list change after installation.

**Full backup is checked by default.** With it, a timestamped complete device
backup goes into `Backup` beside the app EXE. Without it, the installer still
retains the prior effect list and old bank files in a session under local app
data and scans all saved patches, but has **no full-device recovery backup**.
Do not disconnect or cancel a transfer. Keep a stock patch selected and erase
all saved N2Z Bank patches before replacing the bank.
If any transfer fails, keep the pedal powered, preserve the app log/session,
and follow the Stomphacks `SAFETY.md` rescue procedure. Do not blindly retry.

Validate new banks and effect combinations, including saved-patch behavior
after a power cycle. Avoid multiple N2Z instances in a saved patch. Lowering
the load declaration changes patch admission, not DSP work; never lower it
solely to force more effects into a patch.

## Troubleshooting

- `git`, `uv`, `cmake`, or `dotnet` missing: install the linked prerequisite
  and open a new PowerShell window. `git --version`, `uv --version`,
  `cmake --version`, and `dotnet --version` should all work.
- `-TiCgt` rejected: point to the extracted **8.3.1** compiler root, not its
  parent or `bin` directory. Check `Test-Path 'C:\your-path\bin\cl6x.exe'`.
- `vswhere.exe`, C++ workload, or Ninja missing: modify Visual Studio/Build
  Tools and install **Desktop development with C++**, including MSVC and
  CMake/Ninja. Reopen PowerShell afterward.
- No MIDI ports found: confirm the unit is powered and connected by a data
  cable, close other MIDI applications, and reconnect. Do not retry an
  interrupted write blindly; first read the app log and recovery procedure.
- Training is very slow or fails on GPU: the default PyTorch wheel may be
  CPU-only. Select the CUDA wheel index compatible with your driver from the
  PyTorch guide and pass it via `-TorchIndexUrl` during setup on a fresh
  training environment. CPU training still works but takes much longer.
- A NAM is unsupported or misses the quality gate: not every Tone3000 model
  is structurally compatible or accurately compressible to this fixed student.
  The quality-review dialog can accept a supported conversion outside the
  fidelity limits; it cannot make unsupported models or unsafe pedal installs valid.

## Project layout

| Path                                                  | Purpose                                                               |
| ----------------------------------------------------- | --------------------------------------------------------------------- |
| `apps/nam2zoom-desktop`                               | WinForms UI; embedded `TRAINING_DI.wav`                               |
| `tools/nam2zoom`                                      | NAM classification, adaptation, bank preparation, guarded replacement |
| `tools/msplus*.py`                                    | Read-only USB-MIDI identification, patch/file downloads, backup       |
| `tools/offline_effect_audit.py`, `zd2.py`, `elf32.py` | Independent artifact and device-list checks                           |
| `dsp/nam_a2_compact`                                  | Fixed compact DSP inference kernel                                    |
| `dsp/nam_a2_bank_zd2`                                 | Bank wrapper, controls, pedal artwork                                 |
| `training`                                            | Student architecture and trainer templates                            |
| `reference/nam_a2`                                    | CMake source for the PC NAM Core renderer                             |
| `patches`                                             | Explicit changes required on the two pinned external projects         |
| `tests`                                               | Offline shape and bank packaging tests                                |

The app's backend CLI runs from the `tools` directory as
`python -m nam2zoom`. Its supported commands are `inspect-hybrid`, `adapt`,
`build-bank`, `install-bank`, and `uninstall-bank`; use `--help` for arguments.
`build-bank` does not contact the pedal. Both pedal commands require
`--ack-risk`; installation additionally requires artifact hashes. The desktop
UI supplies these only after its separate approval dialog.
The MS-60B+ profile uses family `0x006E`, model `0x0027`, firmware `1.20`,
and 100 saved patches. Its identity is recorded in upstream
[zoom-explorer](https://github.com/thammer/zoom-explorer/blob/master/src/miditools.ts);
firmware 1.20 is listed on [Zoom's support page](https://zoomcorp.com/en/gb/multi-effects/multistomp-pedals/ms-60b-plus/ms-60b-support/).
It uses the same bank artifacts and guarded install/uninstall paths; group
`0x04` places N2Z Bank in PREAMP on MS-60B+. Other firmware versions remain
refused. N2Z Bank has not yet been auditioned on this pedal.
`build-bank` always produces the 3-channel, 14-layer optimized bank with the
150 load declaration. The desktop app uses the same backend.

## Build A Portable Release

Set `<Version>` in the root `Directory.Build.props` before building a release.
Use `major.minor.patch` for a stable version, or a prerelease suffix such as
`1.0.0-preview.1`. The desktop window title, executable version metadata, and
portable ZIP name all use this value. Use `nam2zoom-v<version>` as the GitHub
release title and `v<version>` as its tag. Bump the version for a new release;
the packaging script refuses to overwrite existing output for the same version.

The user path is a separate self-contained Windows ZIP. Users never run
`setup.ps1`. First complete the developer setup, then run from the clone root:

```powershell
.\release\build-portable.ps1
```

Python 3.12/3.13 runtimes are discovered under `.tooling/python`. The script
also checks the usual Python 3.13 install directory. Use `-Python312` and
`-Python313` to override discovery. A runtime must be a full x64 CPython distribution containing
`python.exe`, its matching `python312.dll` or `python313.dll`, `DLLs`, `Lib`, and `LICENSE.txt`. Setup's Python
3.12 runtime is suitable for this purpose. The script compiles zero-weight templates for one through ten
models using the maintainer's TI toolchain. It bundles the static-CRT native
renderer, self-contained .NET GUI, portable Python runtimes, minimal MIDI
backend, patched NAM trainer wheel, training constraints, and notices.
Compiler binaries and user model weights are not included. Generated files
remain in ignored `.tooling` and `dist`.

For repeat local packaging, `-Templates <previous template folder>` and
`-TrainingWheel <pinned trainer wheel>` reuse generated inputs. Only reuse
templates built from the current DSP/control sources; regenerate them after
any such change. Normal developer bank builds still compile from source.
After an intentional DSP change, `-HardwareTestCandidate` packages a ZIP labelled
`hardware-test` for pedal audition. It skips only the comparison against the
previously auditioned DSP image; structural template checks still run. Regular
preview builds retain the hardware-baseline check. Update that baseline only
after the new DSP has been auditioned on the pedal.
Portable builds find `release/templates/index.json` and fill only the
validated constant-table weight/label ranges, update CRC, and audit the
result. No DSP instruction or relocation is patched. The complete effect
file is still replaced on the pedal. Saved-patch guards are not bypassed.

On the first adaptation, the app asks before downloading CPU or NVIDIA
PyTorch packages into a local venv. The NAM wheel and resolved CPU training
dependency versions are pinned in `release/training-constraints.txt`.
Training runs with `python -m nam.cli`
instead of an absolute-path console launcher, and portable venv home paths
are updated after moving the extracted folder.

PyTorch also needs Microsoft's native C++ runtime. The GUI checks it before
calling portable Python, offers a Microsoft-hosted download if needed,
verifies the Authenticode status and publisher with Windows PowerShell,
and runs the installer only after user consent/UAC approval. Native renderer
builds use the static CRT, but this does not remove PyTorch's runtime dependency.

Before publishing: test ZIP extraction on a clean Windows account with no
developer tools, direct-model packaging, initial CPU/GPU setup, at least one
conversion/preview, and guarded install/uninstall. Confirm every bundled
license notice, compare filled templates against compiler-built artifacts,
and audition the generated bank on the pedal before saving a patch. Use a
GitHub **prerelease** until these checks pass. Do not publish personal NAM
weights or backups.

## Two-Sample Kernel

The default build uses `dsp/nam_a2_compact/compact_pair.c` with the same
659 weights, 3 channels and 14 layers. It evaluates two consecutive samples;
it does not skip, average or resample them. History uses 20,076 bytes instead
of the scalar reference's 39,792 bytes. The instance initialization tag is
different so the two history layouts cannot be reused interchangeably.

Kernel tests compare scalar and pair output, causal delays, history wrapping
and memory guards. Full-callback replay uses the production wrapper, all ten
models, controls, Mix, initialization and invalid inputs under a 32-bit host
ABI. The previous scalar callback lives only in `tests/fixtures`.
Generated portable templates use the same production sources and reject
source-hash mismatches. `release/templates/` is a generated cache for local
packaging and is intentionally ignored.

```powershell
& .\.tooling\stomphacks\.venv\Scripts\python.exe -B -m unittest discover -s tests -p test_kernel_pair.py -v
& .\.tooling\stomphacks\.venv\Scripts\python.exe -B -m unittest discover -s tests -p test_pair_bank.py -v
```

## Catalogue Compatibility

Developer setup and portable releases preserve the per-entry catalogue byte
that Zoom's official tool can set to nonzero values. It is modeled as opaque
metadata, not discarded or interpreted as DSP load. Regression tests verify
byte-identical rebuilds and add/remove restoration. Catalogue length, zero
padding, group IDs, corruption rejection, saved-patch checks and independent
upload readback remain enforced. This does not bypass custom-effect checks
or establish compatibility with arbitrary catalogue formats.

## License

Project code is available under the [MIT License](../LICENSE), copyright 2026
Aleksandar Vukasinovic. The downloaded Stomphacks, NAM, NAM Core, and TI tools
have their own terms; `.tooling` and compiler binaries are not part of the Git
repository.

## Compact and Lite builds

The desktop Model selector and CLI `--profile compact|lite` select one architecture
for the entire bank. Compact remains the default and retains its existing cache
keys. Lite uses the native A2 Lite layer/kernel/head geometry, retrained at
44.1 kHz with the standard loss/optimizer. Packed teachers select slim 0 for Lite
and slim 1 for Compact. Lite conversions have distinct cache keys and profile
metadata; imports and build validation reject mismatched shapes.

`training/a2-lite-44100/model.json` defines the 23-layer, 3-channel student.
`dsp/nam_a2_lite` implements causal two-sample inference, with 76,728 bytes of
history and 1,871 weights per model. The shared bank wrapper rounds Lite's
6,347-sample warmup to 6,348 samples and uses distinct initialization/recovery
markers. RAM needs and DSP timing must be tested on hardware; Compact reserves 150 raw; Lite now reserves the full 270 raw after combined-effect
overload was reported. These are conservative scheduling values, not measured CPU load.

`release/build-portable.ps1` builds both template sets by default in one command.
Existing caches can be supplied with `-Templates` and `-LiteTemplates`.
The portable payload contains `release/templates` and `release/templates-lite`;
both sets are source-hash checked and only model data is patched at runtime.

Local numerical parity is tested against NAM Core with `tests/test_nam_core_parity.py`;
set `NAM2ZOOM_PARITY_MODEL` to a real Compact or Lite trained export.
The Lite test build does not establish real-time pedal performance or saved-patch
compatibility. Compact templates must retain their pedal-tested instruction image.

### Lite overload follow-up (2026-10-07)

The initial generic Lite kernel caused slowdown and noise in a library preview
with an empty patch behind it. This is consistent with missed audio deadlines;
no measured pedal cycle count is available. The generic tap loop had a C674x
initiation interval of four cycles. Its replacement specializes 6- and 15-tap
convolutions, unrolls the products and splits each output into independent sums.
The six-tap output-channel loop schedules at 34 cycles per channel; these
different loop intervals are not directly comparable as speedup figures.

Model geometry, weights and training/cache settings are unchanged. Existing
Lite exports can be repackaged without retraining. Numerical parity, callback
guards/recovery and all 72 offline tests pass. The revised kernel still needs
hardware timing and audio testing. Compact's pedal-tested code is unchanged.
The next test must use one Lite effect in an actual empty unsaved patch, with
all other effects disabled, to distinguish library-preview behavior from overload.

### Lite standalone reservation

The user reported the optimized Lite kernel running JCM800, Twin Reverb and Mark
IIC+ alone, but slowdown/crackling with even one additional effect. Lite's manifest
and bank lock now reserve 270 raw (the full declared patch budget), while Compact
retains 150. The UI calls it Lite (alone). This changes effect admission metadata,
not inference performance, model weights or training/cache settings. Firmware
admission, saved-patch and reboot behavior still need hardware verification.
Template filling verifies the actual INFO reservation before patching weights;
old Lite templates with 150 are rejected. Existing generated Lite templates can
be restamped by the maintainer with CRC/hash updates and byte-identical ELF data,
or regenerated normally using release/create_templates.py --profile lite.
