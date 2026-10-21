# nam2zoom on Linux

This is the Linux port of nam2zoom. It runs from a source checkout that you
set up yourself. Everything below marked **unverified** has not been tested
yet; everything else was verified on real hardware or on the host machine.

## What works (verified)

- **CPU training** of `.nam` models with the **Compact** profile - verified
  with a real 10-epoch run (quality metrics: ESR 0.074, correlation 0.964).
- **Building a N2Z Bank** (`N2ZBANK.ZD2` + `N2ZBANK.ZIC`) from trained models -
  verified end to end.
- **Install and uninstall over USB-MIDI** on a **Zoom MS-60B+ firmware 1.20** -
  verified from the GUI.
- The most recent verified test: a **3-model bank with cabinet IRs, 10 training
  epochs per model** - built and installed from the GUI, readback verified,
  each of the three slots sounds distinct, the effect saves into a patch and
  still works after a pedal reboot.
- **100-epoch training**: verified on a Zoom MS-60B+ firmware 1.20. A 100-epoch
  bank was trained, built, installed from the GUI, readback verified, the effect
  saved into a patch, and still worked after a pedal reboot.
- The GUI footer shows the Linux-specific note on Linux ("USB-MIDI verified on
  Linux with a Zoom MS-60B+ (fw 1.20)."); Windows and macOS keep their existing
  text byte-for-byte.
- The app's two smoke tests (see below) - verified.

## What does not work (or is unverified)

- **CUDA (NVIDIA GPU) training**: not available on Linux. It is a
  Windows-only feature in this codebase; Linux trains on the CPU only.
- **A2 Lite profile**: disabled in the project. Compact is the only enabled
  profile.
- **Other pedals on Linux (MS-50G+, MS-70CDR+): unverified.** Only the
  MS-60B+ fw 1.20 has been verified on this port.

## Prerequisites

Install these yourself first. Package names below are Debian/Ubuntu style;
this project never runs `sudo` for you.

**All commands in this guide are run from the repository root** (the folder
that contains `setup-linux.sh`), except the install steps for uv, .NET and
cl6x.

You can check all of these with `./dev-setup-linux.sh`.

- `git`
- **.NET 10 SDK** - the app is written in C#. Download the installer script
  from https://dot.net/v1/dotnet-install.sh and run it with `--channel 10.0`:

  ```bash
  curl -LsSf https://dot.net/v1/dotnet-install.sh -o dotnet-install.sh
  bash dotnet-install.sh --channel 10.0
  ```

  It installs to `~/.dotnet`. Add it to your PATH (and set `DOTNET_ROOT`). An export PATH line only lasts for this terminal window. To make it permanent, add these lines to your `~/.bashrc` and open a new terminal:

  ```bash
  export PATH="$HOME/.dotnet:$PATH"
  export DOTNET_ROOT="$HOME/.dotnet"
  ```

- **uv** - installs Python and the two virtual environments. Install it before
  running `setup-linux.sh`:

  ```bash
  curl -LsSf https://astral.sh/uv/install.sh | sh
  ```

  It installs to `~/.local/bin`. An export PATH line only lasts for this terminal window. To make it permanent, add this line to your `~/.bashrc` and open a new terminal:

  ```bash
  export PATH="$HOME/.local/bin:$PATH"
  ```
- `cmake`, `ninja`, `gcc`, `g++`, `clang` - build the native audio renderer
- `libasound2` (ALSA, needed for USB-MIDI) and `libasound2-dev` - provides
  `/usr/include/alsa/asoundlib.h`, needed if python-rtmidi has to be compiled
  from source (see the `STOMP_PYTHON` option below)
- ALSA sequencer kernel support: the `snd_seq` module must be loaded
- **`audio` group**: your user must be in the `audio` group, because
  `/dev/snd/seq` is group `audio`. Without it the GUI shows "pedal detection
  unavailable". Add yourself with `sudo usermod -aG audio $USER`, then **log out
  and back in** (a new login is required for the change to take effect). To
  check: `id -nG | grep -w audio`.
- `libportaudio` (`libportaudio2`) - only a warning if missing; training does
  not need it, some audio helpers do
- **TI C6000 C-compiler (cl6x) version 8.3.1**, installed by hand once:
  - Get the installer from TI's code-generation tools download archive
    (https://software-dl.ti.com/codegen/non-esd/downloads/download_archive.htm);
    this link was verified on a clean account.
  - Put the downloaded `.bin` outside the repo (for example `~/Downloads`).
    Run the installer once from the repository root, with the shell in the repo
    root and the full path to the `.bin`, so the installer file itself never
    lands in the repo:

    ```bash
    chmod +x ~/Downloads/<installer>.bin
    ~/Downloads/<installer>.bin --mode unattended --prefix "$PWD/.tooling/cgt-8.3.1"
    ```

    `chmod +x ~/Downloads/<installer>.bin` = make the downloaded TI installer executable;
    `~/Downloads/<installer>.bin ...` = run the TI installer from the repo root;
    the `.bin` stays in `~/Downloads`, never in this repo;
    `--mode unattended` = silent install, no wizard clicks or user input;
    `--prefix "$PWD/.tooling/cgt-8.3.1"` = install location; the TI installer
    appends its own `ti-cgt-c6000_8.3.1` folder itself, giving
    `.tooling/cgt-8.3.1/ti-cgt-c6000_8.3.1/bin/cl6x`.
  - It is installed once, lives inside the repo folder, needs no PATH setup
    and survives every terminal restart: bank builds look for the compiler at
    the fixed path `.tooling/cgt-8.3.1/ti-cgt-c6000_8.3.1/bin/cl6x` and
    nowhere else (`tools/nam2zoom/bank.py`); `setup-linux.sh` does not
    install it or look anywhere else for you.
  - One-line check:

    ```bash
    ls -d .tooling/cgt-8.3.1/ti-cgt-c6000_8.3.1/bin/cl6x
    ```
  - Running `cl6x` by hand may print "no source files" - that is normal,
    it just means no source file was given on the command line.
  - The installer is a 32-bit program; `bin/cl6x` itself is a 64-bit static
    Linux program (used with `--silicon_version=6740`).
  - The compiler is **not redistributed**: never commit it to git and never
    bundle it with releases.

## Checking your setup (dev-setup-linux.sh)

`./dev-setup-linux.sh` checks the prerequisites above and prints, for each
missing item, the exact fix command and why it is needed. It installs
nothing and never uses `sudo`. It exits non-zero if a required item
(dotnet, uv, cl6x) is missing.

## Setting up (setup-linux.sh)

From the repository root:

```bash
./setup-linux.sh
```

The script never uses `sudo`. It checks the basic tools, clones the pinned
helper repositories, creates two Python environments
(`.tooling/stomphacks/.venv` and `.tooling/nam-train-venv`), installs CPU-only
PyTorch plus the NAM trainer into the training environment, and builds the
native renderer with CMake and Ninja.

**If it stops with a message about `/usr/include/alsa/asoundlib.h`:**
python-rtmidi has no prebuilt wheel for Python 3.13, so uv would compile it
from source, which needs the ALSA development headers. Either install your
distro's `libasound2-dev` package yourself, or build the environments on
Python 3.12, which has a prebuilt wheel:

```bash
STOMP_PYTHON=3.12 ./setup-linux.sh
```

## Building and running the app

```bash
dotnet build apps/nam2zoom-avalonia
dotnet run --project apps/nam2zoom-avalonia
```

If `dotnet` is not on your PATH, use its full path instead (for example
`~/.dotnet/dotnet run --project apps/nam2zoom-avalonia`).

## The two smoke tests

Run these from the repository root after setup. They start the app in a check
mode and never touch the pedal.

```bash
# Checks the Python imports in both environments (prints two OK lines):
dotnet run --project apps/nam2zoom-avalonia -- --smoke-test

# Opens and closes the main window (needs an X11 session):
dotnet run --project apps/nam2zoom-avalonia -- --gui-smoke-test
```

The first test must print, in order: `Backend runtime imports OK`, then
`Training runtime imports OK`. The GUI test opens the main window only briefly
and closes it on its own; this is normal. Both tests were verified on the
host.

## First use

1. Start the app (command above) and plug in the pedal. There is no detect
   button: the app checks for the pedal on its own every few seconds and shows
   the status in the window header ("Checking for pedal..." changes to a status
   line with a filled dot once the pedal is found).
2. Add one to ten `.nam` files with the **Add NAMs** button, or drop them onto
   the "Drop NAM files here" area.
3. Select a model and give it a **Pedal label** (its short name on the pedal).
   Optionally attach a mono cabinet IR with **Choose IR...**.
4. Set **Training epochs** (10 is what has been verified) and leave the profile
   on **Compact**.
5. Keep **Full backup before pedal changes** ticked (it is on by default).
6. Either:
   - **Build effect**: builds the bank on the computer only. The app asks for a
     build output folder, then builds. If a conversion needs review, a quality
     dialog asks whether to use the converted models; finally a "Build
     complete" dialog shows the output folder.
   - **Build & install...**: builds the same way, then shows an "Approve exact
     pedal install" dialog that displays the exact ZD2 and ZIC SHA-256 hashes
     and asks to install that pair. Click **Approve** to continue. A final
     dialog confirms "Installation complete" with readback verified.
7. **Uninstall bank...** asks "Approve bank removal" before removing the bank.

Your data (backups, sessions, logs, converted models) lives in
`~/.local/share/nam2zoom`.

## Safety rule: select a stock patch first

**Before you install or uninstall a bank, select a stock (built-in) patch on
the pedal.** Uninstall and install refuse to run while the current patch uses
the N2Z effect, because it is not a stock effect (non-stock effect ID check).

Also from the project's safety guidance: keep USB and power connected during
transfers, never disconnect or power off the pedal mid-transfer, and keep your
backups.

---

Verified facts in this document come from `docs/STATUS.md` and
`docs/plans/`. Anything not marked was left out on purpose; anything marked
**unverified** still needs a test.

