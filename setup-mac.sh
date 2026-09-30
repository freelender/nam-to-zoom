#!/usr/bin/env bash
# macOS developer setup, mirroring the upstream project's setup.ps1.
# Pins the same external checkouts/revisions and builds the native renderer,
# but targets clang/Ninja instead of MSVC and uses macOS venv layout ("bin",
# no .exe). Does not touch a pedal.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
tooling="$root/.tooling"
stomp="$tooling/stomphacks"
nam="$tooling/neural-amp-modeler"
core="$tooling/NeuralAmpModelerCore"

stomp_rev="ebd5ced93988d595bb42c825dd9bd89626b300e6"
nam_rev="0072676419459f5d39e36f5b9fd4172f28d62cbf"
core_rev="0b3d3c97b0859a3a8c92a8628c4dd89a25eb5842"

for cmd in git cmake ninja; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "Missing prerequisite: $cmd (see docs/DEVELOPMENT.md / README.md for macOS)." >&2
    echo "Install Xcode Command Line Tools (xcode-select --install) and Homebrew" >&2
    echo "(brew install cmake ninja), then re-run this script." >&2
    exit 1
  fi
done

# Homebrew's python@3.13/python@3.12, not uv, provision the two venvs below.
# uv's atomic-rename cache writes (renamex_np) return EPERM on this machine/OS
# combination even outside any sandbox, while plain `python -m venv` + pip
# (also what Homebrew itself uses internally) work fine here - so this script
# leans on the stdlib venv module instead of depending on a tool that's broken
# in this specific environment.
python313="$(command -v python3.13 || true)"
python312="$(command -v python3.12 || true)"
for brew_prefix in /opt/homebrew/opt /usr/local/opt; do
  [ -z "$python313" ] && [ -x "$brew_prefix/python@3.13/bin/python3.13" ] \
    && python313="$brew_prefix/python@3.13/bin/python3.13"
  [ -z "$python312" ] && [ -x "$brew_prefix/python@3.12/bin/python3.12" ] \
    && python312="$brew_prefix/python@3.12/bin/python3.12"
done
if [ -z "$python313" ] || [ -z "$python312" ]; then
  echo "Missing prerequisite: Python 3.13 and/or 3.12." >&2
  echo "Install with: brew install python@3.13 python@3.12" >&2
  exit 1
fi

mkdir -p "$tooling"

ensure_checkout() {
  local dir="$1" url="$2" rev="$3" patch="$4" submodules="$5"
  if [ ! -d "$dir/.git" ]; then
    git clone "$url" "$dir"
    git -C "$dir" checkout --detach "$rev"
    if [ -n "$patch" ]; then
      git -C "$dir" apply "$patch"
    fi
  else
    local head
    head="$(git -C "$dir" rev-parse HEAD)"
    if [ "$head" != "$rev" ]; then
      echo "Existing checkout at $dir is not the pinned revision $rev" >&2
      exit 1
    fi
    if [ -n "$patch" ]; then
      if ! git -C "$dir" apply --reverse --check "$patch" >/dev/null 2>&1; then
        if ! git -C "$dir" apply --check "$patch" >/dev/null 2>&1; then
          echo "Required local patch conflicts with existing changes in $dir" >&2
          exit 1
        fi
        git -C "$dir" apply "$patch"
      fi
    fi
  fi
  if [ "$submodules" = "true" ]; then
    git -C "$dir" submodule update --init
  fi
}

ensure_checkout "$stomp" "https://github.com/thammer/stomphacks.git" "$stomp_rev" \
  "$root/patches/stomphacks.patch" false

# stomphacks itself documents (docs/building-effects.md) that it needs a
# clone of mungewell/zoom-zt2 inside its own tree at "zoom-zt2/" - it does
# the ZD2 file handling and MIDI transfers that tools/nam2zoom/deploy.py and
# patches/stomphacks-catalogue.patch both depend on. Neither this script nor
# the upstream setup.ps1 clones it automatically, and upstream does not pin
# a revision for it either, so this step tracks zoom-zt2's default branch.
if [ ! -d "$stomp/zoom-zt2/.git" ]; then
  git clone "https://github.com/mungewell/zoom-zt2.git" "$stomp/zoom-zt2"
fi
# zoom-zt2's zoomzt2.py ships with CRLF line endings; stomphacks-catalogue.patch
# was authored against LF, so git apply's context matching fails on CR bytes
# even though the text is otherwise identical. Normalize before patching.
perl -pi -e 's/\r\n/\n/g' "$stomp/zoom-zt2/zoomzt2.py"

ensure_checkout "$stomp" "https://github.com/thammer/stomphacks.git" "$stomp_rev" \
  "$root/patches/stomphacks-catalogue.patch" false
ensure_checkout "$nam" "https://github.com/sdatkinson/neural-amp-modeler.git" "$nam_rev" \
  "$root/patches/neural-amp-modeler.patch" false
ensure_checkout "$core" "https://github.com/sdatkinson/NeuralAmpModelerCore.git" "$core_rev" \
  "" true

stomp_python="$stomp/.venv/bin/python3"
train_python="$tooling/nam-train-venv/bin/python3"

# Build each venv under /tmp, then relocate it into place. On this machine, a
# freshly Homebrew-installed Python performing its own atomic-rename package
# installs (ensurepip/pip's dist-info finalization) gets EPERM anywhere under
# $HOME, but the identical operations succeed under /tmp, and a plain `mv` of
# the finished venv onto the same volume works fine (both places are on
# /System/Volumes/Data here). This script never invokes a venv's bin/pip
# shebang directly - always "<venv>/bin/python3 -m pip/nam2zoom" - so the venv
# doesn't need its embedded absolute paths fixed up after the move: its
# python3 is a symlink to Homebrew's install (unaffected by relocation) and
# pyvenv.cfg's "home" also points there, not at the venv's own location.
build_venv_then_move() {
  local python_bin="$1" final_dir="$2"
  local tmp_dir
  tmp_dir="$(mktemp -d "${TMPDIR:-/tmp}/nam2zoom-venv.XXXXXX")"
  rmdir "$tmp_dir"
  "$python_bin" -m venv "$tmp_dir"
  "$tmp_dir/bin/python3" -m pip install --quiet --upgrade pip
  echo "$tmp_dir"
}

if [ ! -x "$stomp_python" ]; then
  tmp_venv="$(build_venv_then_move "$python313" "$stomp/.venv")"
  "$tmp_venv/bin/python3" -m pip install -r "$stomp/requirements.txt"
  mkdir -p "$stomp"
  mv "$tmp_venv" "$stomp/.venv"
else
  "$stomp_python" -c "import PIL, mido, rtmidi, elftools"
fi

if [ ! -x "$train_python" ]; then
  tmp_venv="$(build_venv_then_move "$python312" "$tooling/nam-train-venv")"
  if [ -n "${TORCH_INDEX_URL:-}" ]; then
    "$tmp_venv/bin/python3" -m pip install torch --index-url "$TORCH_INDEX_URL"
  else
    "$tmp_venv/bin/python3" -m pip install torch
  fi
  # Even a non-editable local-path install runs egg_info's "get requirements"
  # PEP 517 hook directly against $nam in place (not a pip-managed copy), so
  # it hits the same EPERM writing egg-info under $HOME. Give pip a throwaway
  # copy under $TMPDIR instead; the pinned/patched checkout at $nam itself is
  # never touched. We don't need live-edit semantics for nam2zoom's own
  # build/adapt/install flow, only the installed package.
  tmp_nam_src="$(mktemp -d "${TMPDIR:-/tmp}/nam2zoom-nam-src.XXXXXX")"
  rmdir "$tmp_nam_src"
  cp -R "$nam" "$tmp_nam_src"
  "$tmp_venv/bin/python3" -m pip install "$tmp_nam_src" soundfile
  rm -rf "$tmp_nam_src"
  mv "$tmp_venv" "$tooling/nam-train-venv"
else
  "$train_python" -c "import nam, torch, scipy, soundfile"
fi

render_source="$root/reference/nam_a2"
render_build="$render_source/build-core-ninja"
if [ ! -f "$render_build/core_render" ]; then
  # Same EPERM class as above: Homebrew's cmake/ninja can't remove/replace
  # their own scratch and build files under $HOME on this machine (compiler
  # try_compile cleanup, incremental rebuild replacement, etc.), even though
  # nothing here is a package install. Building under $TMPDIR avoids it; only
  # the single finished core_render binary - a standalone Mach-O executable
  # that doesn't reference its own build directory - gets moved into place.
  tmp_render_build="$(mktemp -d "${TMPDIR:-/tmp}/nam2zoom-render.XXXXXX")"
  rmdir "$tmp_render_build"
  cmake --fresh -G Ninja -S "$render_source" -B "$tmp_render_build" \
    -DCORE_ROOT="$core" -DCMAKE_BUILD_TYPE=Release
  cmake --build "$tmp_render_build" --target core_render
  if [ ! -f "$tmp_render_build/core_render" ]; then
    echo "core_render was not built" >&2
    exit 1
  fi
  mkdir -p "$render_build"
  mv "$tmp_render_build/core_render" "$render_build/core_render"
  rm -rf "$tmp_render_build"
fi

"$stomp_python" -m unittest discover -s "$root/tests" -p 'test_*.py'
"$train_python" -m unittest discover -s "$root/tests" -p 'test_ir.py'

echo "Setup complete."
echo "CLI backend: PYTHONPATH=$root/tools $stomp_python -m nam2zoom --help"
