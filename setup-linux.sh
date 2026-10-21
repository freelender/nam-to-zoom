#!/usr/bin/env bash
# setup-linux.sh - Linux CPU-only (Compact) counterpart of setup.ps1.
# Creates .tooling/stomphacks/.venv and .tooling/nam-train-venv with uv,
# installs the pinned Python packages (CPU-only PyTorch), and builds
# core_render with gcc/g++ and ninja. Skips all CUDA steps and never
# touches the TI cl6x toolchain (tools/nam2zoom/bank.py still needs it
# for source-checkout bank builds - that is a later stage).
#
# KNOWN ISSUE: python-rtmidi (pinned ==1.5.8 in release/backend-requirements.txt
# and also the latest release on PyPI) ships wheels only for CPython 3.8-3.12.
# The stomphacks venv defaults to Python 3.13 (what setup.ps1 pins), so uv
# compiles python-rtmidi from its sdist, which needs the ALSA development
# headers (/usr/include/alsa/asoundlib.h; Debian/Ubuntu package libasound2-dev).
# This script checks for that header before creating the venv and stops with a
# clear message if it is missing while STOMP_PYTHON >= 3.13. Either install the
# headers yourself, or build the venv on Python 3.12 (prebuilt manylinux wheel):
#   STOMP_PYTHON=3.12 ./setup-linux.sh
# This script never uses sudo and never installs system packages.

set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"
root="$PWD"
tooling="$root/.tooling"
stomp="$tooling/stomphacks"
nam="$tooling/neural-amp-modeler"
core="$tooling/NeuralAmpModelerCore"
stompRev='ebd5ced93988d595bb42c825dd9bd89626b300e6'
namRev='0072676419459f5d39e36f5b9fd4172f28d62cbf'
coreRev='0b3d3c97b0859a3a8c92a8628c4dd89a25eb5842'
zoomZt2Rev='b1f63b0bee6d2d1bc9755958fc8cf15887efbdcf'

# Override without editing, e.g.: STOMP_PYTHON=3.12 ./setup-linux.sh
STOMP_PYTHON="${STOMP_PYTHON:-3.13}"
TORCH_INDEX_URL="${TORCH_INDEX_URL:-https://download.pytorch.org/whl/cpu}"

for command in git uv cmake gcc g++ ninja; do
    if ! command -v "$command" >/dev/null 2>&1; then
        echo "Missing prerequisite: $command. See README.md." >&2
        exit 1
    fi
done

mkdir -p "$tooling"
export UV_CACHE_DIR="$tooling/uv-cache"
export UV_PYTHON_INSTALL_DIR="$tooling/python"

checked() {
    echo "Running: $*"
    local status=0
    "$@" || status=$?
    if [[ $status -ne 0 ]]; then
        echo "ERROR: $* failed with exit code $status" >&2
        exit "$status"
    fi
}

# Upstream zoom-zt2 is committed with CRLF line endings while our patches are
# LF; plain git apply rejects the hunks, so all applies use --ignore-whitespace.
ensure_checkout() {
    local directory="$1" url="$2" revision="$3" patch="$4" submodules="$5"
    if [[ ! -d "$directory/.git" ]]; then
        checked git clone "$url" "$directory"
        checked git -C "$directory" checkout --detach "$revision"
        if [[ -n "$patch" ]]; then
            checked git -C "$directory" apply --ignore-whitespace "$patch"
        fi
    else
        local head
        head="$(git -C "$directory" rev-parse HEAD)"
        if [[ "$head" != "$revision" ]]; then
            echo "Existing checkout at $directory is not the pinned revision $revision" >&2
            exit 1
        fi
        if [[ -n "$patch" ]]; then
            if ! git -C "$directory" apply --reverse --check --ignore-whitespace "$patch" >/dev/null 2>&1; then
                if ! git -C "$directory" apply --check --ignore-whitespace "$patch" >/dev/null 2>&1; then
                    echo "Required local patch conflicts with existing changes in $directory" >&2
                    exit 1
                fi
                checked git -C "$directory" apply --ignore-whitespace "$patch"
            fi
        fi
    fi
    if [[ "$submodules" == "true" ]]; then
        checked git -C "$directory" submodule update --init
    fi
}

ensure_checkout "$stomp" 'https://github.com/thammer/stomphacks.git' "$stompRev" \
    "$root/patches/stomphacks.patch" false
ensure_checkout "$stomp/zoom-zt2" 'https://github.com/mungewell/zoom-zt2.git' "$zoomZt2Rev" '' false
ensure_checkout "$stomp" 'https://github.com/thammer/stomphacks.git' "$stompRev" \
    "$root/patches/stomphacks-catalogue.patch" false
ensure_checkout "$stomp" 'https://github.com/thammer/stomphacks.git' "$stompRev" \
    "$root/patches/stomphacks-ten-models.patch" false
ensure_checkout "$stomp" 'https://github.com/thammer/stomphacks.git' "$stompRev" \
    "$root/patches/stomphacks-user-data.patch" false
ensure_checkout "$nam" 'https://github.com/sdatkinson/neural-amp-modeler.git' "$namRev" \
    "$root/patches/neural-amp-modeler.patch" false
ensure_checkout "$core" 'https://github.com/sdatkinson/NeuralAmpModelerCore.git' "$coreRev" '' true

stompPython="$stomp/.venv/bin/python3"
trainPython="$tooling/nam-train-venv/bin/python3"
newStompVenv=false
newTrainVenv=false
[[ -x "$stompPython" ]] || newStompVenv=true
[[ -x "$trainPython" ]] || newTrainVenv=true

if [[ "$newStompVenv" == true ]]; then
    stompMajor="${STOMP_PYTHON%%.*}"
    stompMinor="${STOMP_PYTHON#*.}"
    stompMinor="${stompMinor%%.*}"
    if (( stompMajor > 3 || (stompMajor == 3 && stompMinor >= 13) )) \
        && [[ ! -f /usr/include/alsa/asoundlib.h ]]; then
        echo "ERROR: /usr/include/alsa/asoundlib.h is missing." >&2
        echo "python-rtmidi has no prebuilt wheel for CPython ${STOMP_PYTHON}, so uv must" >&2
        echo "compile it from source, which needs the ALSA development headers. Install" >&2
        echo "the Debian/Ubuntu package libasound2-dev yourself, then rerun this script," >&2
        echo "or run with STOMP_PYTHON=3.12 to install from a prebuilt wheel:" >&2
        echo "  STOMP_PYTHON=3.12 $0" >&2
        exit 1
    fi
fi

if [[ "$newStompVenv" == true || "$newTrainVenv" == true ]]; then
    echo "uv manages Python ${STOMP_PYTHON} and 3.12 under $tooling/python (UV_PYTHON_INSTALL_DIR)."
    pythonVersions=("$STOMP_PYTHON")
    if [[ "$STOMP_PYTHON" != "3.12" ]]; then
        pythonVersions+=("3.12")
    fi
    checked uv python install "${pythonVersions[@]}"
fi
if [[ "$newStompVenv" == true ]]; then
    checked uv venv "$stomp/.venv" --python "$STOMP_PYTHON"
fi
if [[ "$newTrainVenv" == true ]]; then
    checked uv venv "$tooling/nam-train-venv" --python 3.12
fi

if [[ "$newStompVenv" == true ]]; then
    checked uv pip install --python "$stompPython" \
        -r "$root/release/backend-requirements.txt" \
        -r "$stomp/requirements.txt"
else
    checked "$stompPython" -c 'import PIL, mido, rtmidi, elftools'
fi

# sounddevice (a NAM dependency) needs libportaudio at import time on Linux.
# Training itself does not use it, so this is a warning, not an error.
if ! ldconfig -p 2>/dev/null | grep libportaudio >/dev/null 2>&1; then
    echo "WARNING: libportaudio not found via ldconfig; 'import sounddevice' in the" >&2
    echo "WARNING: training venv may fail. Training does not require it." >&2
fi
if [[ "$newTrainVenv" == true ]]; then
    checked uv pip install --python "$trainPython" torch==2.11.0 --index-url "$TORCH_INDEX_URL"
    checked uv pip install --python "$trainPython" -e "$nam" soundfile==0.14.0
else
    checked "$trainPython" -c 'import nam, torch, scipy, soundfile'
fi

renderBuild="$root/reference/nam_a2/build-core-ninja"
export CC=gcc CXX=g++
checked cmake -G Ninja -S "$root/reference/nam_a2" -B "$renderBuild" \
    -DCORE_ROOT="$core" -DCMAKE_BUILD_TYPE=Release
checked cmake --build "$renderBuild" --target core_render
if [[ ! -x "$renderBuild/core_render" ]]; then
    echo "ERROR: core_render was not built at $renderBuild/core_render" >&2
    exit 1
fi

echo "Setup complete (Linux, CPU-only, Compact)."
echo "Build and run the Avalonia GUI:"
echo "  dotnet build $root/apps/nam2zoom-avalonia"
echo "  dotnet run --project $root/apps/nam2zoom-avalonia -- --smoke-test"
echo "Note: building a N2Z bank from this source checkout still requires the TI"
echo "cl6x toolchain (tools/nam2zoom/bank.py); this script does not install it."

if ! command -v dotnet >/dev/null 2>&1; then
    if [[ -x "$HOME/.dotnet/dotnet" ]]; then
        echo "Note: dotnet is installed at $HOME/.dotnet/dotnet but is not on this"
        echo "shell's PATH. Open a new terminal (see docs/LINUX.md) or use the full"
        echo "path, for example:"
        echo "  $HOME/.dotnet/dotnet build $root/apps/nam2zoom-avalonia"
    else
        echo "Note: dotnet was not found. Install the .NET 10 SDK as described in"
        echo "docs/LINUX.md, then build and run the GUI."
    fi
fi





