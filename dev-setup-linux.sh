#!/usr/bin/env bash
# dev-setup-linux.sh - check-only developer setup check for the Linux port.
#
# Prints one aligned status line per prerequisite. For every non-OK item it
# prints indented Why/Fix lines with the exact commands for the user to run,
# then one closing Result line. This script installs nothing, makes no network
# calls and never runs sudo: it never executes any printed fix command, and
# sudo appears only inside printed text for the user (precedent:
# docs/LINUX.md:36-37 "this project never runs sudo for you").
#
# Required (exit 1 when missing): dotnet, uv, cl6x. Everything else warns:
# ALSA header, clang, 32-bit libs, libportaudio, audio group, snd_seq.
# git, cmake, gcc, g++ and ninja are NOT checked here because
# setup-linux.sh:37-42 already hard-fails on them.
#
# Exit codes: 0 = all required items present (warnings allowed);
#             1 = at least one required item missing. No other codes.
# Contract: docs/plans/08-dev-setup-linux.md (owner-approved).

# set -u only - deliberately NO set -e: failing probes (command -v, gcc -m32,
# ldconfig | grep) are expected data for a checker, not fatal errors. Compare
# setup-linux.sh:20 (set -euo pipefail), which suits an action script.
set -u

# Resolve the repository root exactly like setup-linux.sh:22-23, so the cl6x
# path below resolves against the repository root.
cd "$(dirname "${BASH_SOURCE[0]}")"
root="$PWD"

missing=0
warnings=0

# One aligned status line per item: [ OK ] / [WARNING] / [MISSING] (plain ASCII).
status() {
    case "$1" in
        OK)      printf '[ OK ]      %s\n' "$2" ;;
        WARNING) printf '[WARNING]   %s\n' "$2" ;;
        *)       printf '[MISSING]   %s\n' "$2" ;;
    esac
}

# Indented Why:/Fix: block. The first line follows the label; the remaining
# lines align under it (10 columns). Pass continuation lines pre-padded with
# two spaces when a command should be indented deeper (12 columns).
detail() {
    local label="$1"
    shift
    printf '    %s:  %s\n' "$label" "$1"
    shift
    local extra
    for extra in "$@"; do
        printf '          %s\n' "$extra"
    done
}

# Informational version string for an OK line when the tool is on PATH.
# First line only: clang --version prints several lines and every OK line
# must stay on one line.
version_of() {
    local name="$1" v
    v="$("$name" --version 2>/dev/null | head -n 1)"
    v="${v#"$name "}"
    if [[ -n "$v" ]]; then printf '%s' "$v"; else printf 'version unknown'; fi
}

printf '%s\n\n' 'dev-setup-linux.sh - developer setup check (check-only; installs nothing)'

# 1. dotnet - REQUIRED. Install steps: docs/LINUX.md:44-57; needed by
# dotnet build/run and both smoke tests: docs/LINUX.md:124-145.
if command -v dotnet >/dev/null 2>&1; then
    status OK "dotnet ($(version_of dotnet))"
elif [[ -x "$HOME/.dotnet/dotnet" ]]; then
    # Installed but not on this shell's PATH: counts as present, but warn.
    warnings=$((warnings + 1))
    status WARNING "dotnet (installed at $HOME/.dotnet/dotnet, not on PATH)"
    detail Why \
        "dotnet is installed at $HOME/.dotnet/dotnet but is not on this shell's" \
        "PATH, so 'dotnet build', 'dotnet run' and both smoke tests will not" \
        "find it (docs/LINUX.md:124-145)."
    detail Fix \
        "open a new terminal (see docs/LINUX.md) or run:" \
        '  export PATH="$HOME/.dotnet:$PATH"' \
        '  export DOTNET_ROOT="$HOME/.dotnet"' \
        "An export PATH line only lasts for this terminal window." \
        "To make it permanent, add the same lines to your ~/.bashrc and open a new terminal." \
        "or use the full path, for example:" \
        "  $HOME/.dotnet/dotnet build $root/apps/nam2zoom-avalonia"
else
    missing=$((missing + 1))
    status MISSING "dotnet"
    detail Why \
        "the app is C#; 'dotnet build', 'dotnet run' and both smoke tests need" \
        "the .NET 10 SDK (docs/LINUX.md:124-145)."
    detail Fix \
        "from the repository root:" \
        '  curl -LsSf https://dot.net/v1/dotnet-install.sh -o dotnet-install.sh' \
        '  bash dotnet-install.sh --channel 10.0' \
        '  export PATH="$HOME/.dotnet:$PATH"' \
        '  export DOTNET_ROOT="$HOME/.dotnet"' \
        "An export PATH line only lasts for this terminal window." \
        "To make it permanent, add the same lines to your ~/.bashrc and open a new terminal."
fi

# 2. uv - REQUIRED. uv creates the two Python environments
# (setup-linux.sh:132-139); setup-linux.sh:38 checks `command -v uv` only.
if command -v uv >/dev/null 2>&1; then
    status OK "uv ($(version_of uv))"
else
    missing=$((missing + 1))
    if [[ -x "$HOME/.local/bin/uv" ]]; then
        # Installed but not on PATH: still MISSING - setup-linux.sh:38 would fail.
        status MISSING "uv (installed at $HOME/.local/bin/uv, not on PATH)"
        detail Why \
            "setup-linux.sh:38 uses 'command -v uv' only, so setup would fail" \
            "even though uv is installed (docs/LINUX.md:66-70)."
        detail Fix \
            "add uv to this terminal's PATH:" \
            '  export PATH="$HOME/.local/bin:$PATH"' \
            "An export PATH line only lasts for this terminal window." \
            "To make it permanent, add this line to your ~/.bashrc and open a new terminal:" \
            '  export PATH="$HOME/.local/bin:$PATH"'
    else
        status MISSING "uv"
        detail Why \
            "uv creates the two Python environments (setup-linux.sh:132-139)."
        detail Fix \
            "from the repository root:" \
            '  curl -LsSf https://astral.sh/uv/install.sh | sh' \
            "then open a new terminal, or run:" \
            '  export PATH="$HOME/.local/bin:$PATH"' \
            "An export PATH line only lasts for this terminal window." \
            "To make it permanent, add this line to your ~/.bashrc and open a new terminal:" \
            '  export PATH="$HOME/.local/bin:$PATH"'
    fi
fi

# 3. clang - warning. setup-linux.sh:163 builds core_render with gcc/g++;
# clang is for upstream NeuralAmpModelerCore kernel tests (docs/SPEC.md:38).
if command -v clang >/dev/null 2>&1; then
    status OK "clang ($(version_of clang))"
else
    warnings=$((warnings + 1))
    status WARNING "clang"
    detail Why \
        "upstream NeuralAmpModelerCore kernel tests / NAM_USE_LIBCXX_LINUX use" \
        "clang (docs/SPEC.md:38); setup-linux.sh:163 builds with gcc/g++, so" \
        "only those tests need clang."
    detail Fix "sudo apt install clang"
fi

# 4. 32-bit libs - warning. The probe compiles only to /dev/null.
if echo 'int main(void){return 0;}' | gcc -m32 -x c - -o /dev/null >/dev/null 2>&1; then
    status OK "32-bit libraries (gcc -m32 probe)"
else
    warnings=$((warnings + 1))
    status WARNING "32-bit libraries (gcc -m32 probe failed)"
    detail Why \
        "the TI cl6x installer is a 32-bit program; bin/cl6x itself is a 64-bit" \
        "static Linux program, so 32-bit libs are needed only to run the" \
        "installer (docs/LINUX.md:95-96)."
    detail Fix "sudo apt install gcc-multilib g++-multilib"
fi

# 5. cl6x - REQUIRED. Bank builds look for the compiler at exactly
# <repo>/.tooling/cgt-8.3.1/ti-cgt-c6000_8.3.1/bin/cl6x and nowhere else
# (tools/nam2zoom/bank.py:21 TOOLCHAIN, :176 bin/cl6x); setup-linux.sh never
# installs it.
cl6x="$root/.tooling/cgt-8.3.1/ti-cgt-c6000_8.3.1/bin/cl6x"
if [[ -x "$cl6x" ]]; then
    status OK "cl6x"
else
    missing=$((missing + 1))
    status MISSING "cl6x"
    detail Why \
        "bank builds invoke it (tools/nam2zoom/bank.py:21, :176);" \
        "setup-linux.sh does not install it."
    detail Fix \
        "download TI C6000 CGT 8.3.1 from the archive in docs/LINUX.md:" \
        "  https://software-dl.ti.com/codegen/non-esd/downloads/download_archive.htm" \
        "then from the repository root run once (the .bin stays in ~/Downloads, never in this repo):" \
        '  chmod +x ~/Downloads/<installer>.bin' \
        '  ~/Downloads/<installer>.bin --mode unattended --prefix "$PWD/.tooling/cgt-8.3.1"' \
        "  chmod +x ~/Downloads/<installer>.bin = make the downloaded TI installer executable" \
        "  ~/Downloads/<installer>.bin ...      = run the TI installer from the repo root;" \
        "    the .bin stays in ~/Downloads, never in the repo" \
        "  --mode unattended        = silent install: no wizard, no clicks" \
        '  --prefix "$PWD/.tooling/cgt-8.3.1" = install location; the TI installer' \
        "    appends its own ti-cgt-c6000_8.3.1 folder itself, giving" \
        "    .tooling/cgt-8.3.1/ti-cgt-c6000_8.3.1/bin/cl6x" \
        "Installed once inside the repo folder; it needs no PATH setup and" \
        "the same install survives every terminal restart. Bank builds look" \
        "for cl6x at the fixed path .tooling/cgt-8.3.1/ti-cgt-c6000_8.3.1/bin/cl6x" \
        "(tools/nam2zoom/bank.py); setup-linux.sh does not install it or look" \
        "anywhere else for you." \
        "One-line check: ls -d .tooling/cgt-8.3.1/ti-cgt-c6000_8.3.1/bin/cl6x" \
        "If you run cl6x by hand and it prints \"no source files\", that is normal."
fi

# 6. ALSA header - warning. Same path as setup-linux.sh:115; print both
# owner-approved fixes (install the header OR build on Python 3.12).
if [[ -f /usr/include/alsa/asoundlib.h ]]; then
    status OK "ALSA header (/usr/include/alsa/asoundlib.h)"
else
    warnings=$((warnings + 1))
    status WARNING "ALSA header (/usr/include/alsa/asoundlib.h missing)"
    detail Why \
        "the default STOMP_PYTHON=3.13 has no prebuilt python-rtmidi wheel, so" \
        "uv would compile the sdist, which needs this header" \
        "(setup-linux.sh:114-123)."
    detail Fix \
        "either install the headers:" \
        "  sudo apt install libasound2-dev" \
        "or build the environments on Python 3.12 (prebuilt wheel, no header" \
        "needed):" \
        "  STOMP_PYTHON=3.12 ./setup-linux.sh"
fi

# 7. libportaudio - warning. Same idiom as setup-linux.sh:151.
if ldconfig -p 2>/dev/null | grep -q libportaudio; then
    status OK "libportaudio"
else
    warnings=$((warnings + 1))
    status WARNING "libportaudio"
    detail Why \
        "'import sounddevice' in the training venv needs it; training itself" \
        "does not (setup-linux.sh:149-153)."
    detail Fix "sudo apt install libportaudio2"
fi

# 8. audio group - warning. Same command as docs/LINUX.md:80.
if id -nG | grep -w audio >/dev/null 2>&1; then
    status OK "audio group"
else
    warnings=$((warnings + 1))
    status WARNING "audio group"
    detail Why \
        "/dev/snd/seq is group audio; without it the GUI shows" \
        '"pedal detection unavailable" (docs/LINUX.md:76-80).'
    detail Fix \
        'sudo usermod -aG audio $USER' \
        "then log out and back in (a new login is required for the change to" \
        "take effect)."
fi

# 9. snd_seq - warning. docs/LINUX.md:75. If /dev/snd itself is absent (the
# Flatpak-sandbox case), say so explicitly instead of implying a host problem.
if [[ -c /dev/snd/seq ]]; then
    status OK "snd_seq (/dev/snd/seq)"
elif [[ ! -d /dev/snd ]]; then
    warnings=$((warnings + 1))
    status WARNING "snd_seq (/dev/snd not present in this environment)"
    detail Why \
        "/dev/snd does not exist here, so the sequencer device cannot be" \
        "checked (the Flatpak sandbox does not see the host). The ALSA" \
        "sequencer kernel module must be loaded for USB-MIDI (docs/LINUX.md:75)."
    detail Fix \
        "run this check on the host; if snd_seq is not loaded there:" \
        "  sudo modprobe snd_seq"
else
    warnings=$((warnings + 1))
    status WARNING "snd_seq (/dev/snd/seq missing)"
    detail Why \
        "the ALSA sequencer kernel module must be loaded for USB-MIDI" \
        "(docs/LINUX.md:75)."
    detail Fix "sudo modprobe snd_seq"
fi

# Closing Result line and exit code: 0 = all required present (warnings
# allowed), 1 = at least one required item missing.
if (( missing > 0 )); then
    item_word="items"
    (( missing == 1 )) && item_word="item"
    warn_word="warnings"
    (( warnings == 1 )) && warn_word="warning"
    printf 'Result: FAIL (%d required %s missing, %d %s)\n' \
        "$missing" "$item_word" "$warnings" "$warn_word"
    exit 1
fi
warn_word="warnings"
(( warnings == 1 )) && warn_word="warning"
printf 'Result: PASS (%d %s)\n' "$warnings" "$warn_word"
exit 0

