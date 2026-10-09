"""Use the built package's Python for offline source regression tests."""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument("--rid", required=True)
args = parser.parse_args()
version = ET.parse(ROOT / "Directory.Build.props").findtext("PropertyGroup/Version")
label = {"win-x64": "windows-x64", "osx-x64": "macos-x64", "osx-arm64": "macos-arm64"}[args.rid]
payload = ROOT / "dist/cross-platform" / f"nam2zoom-v{version}-{label}"
resources = payload if args.rid == "win-x64" else payload / "nam2zoom.app/Contents/Resources"
python = resources / ("runtime/python/python.exe" if args.rid == "win-x64" else "runtime/python/bin/python3")
env = os.environ.copy()
env.update(NAM2ZOOM_TEMPLATE_DIR=str(resources / "release/templates"),
           NAM2ZOOM_LITE_TEMPLATE_DIR=str(resources / "release/templates-lite"),
           NAM2ZOOM_DATA_DIR=str(ROOT / ".tooling/ci-data"),
           PYTHONDONTWRITEBYTECODE="1", PYTHONPATH=str(ROOT / "tools"))
assert subprocess.check_output([str(python), "-c", "import platform; print(platform.machine().lower())"], text=True).strip() == {
    "win-x64": "amd64", "osx-arm64": "arm64", "osx-x64": "x86_64"}[args.rid]
def run(*command):
    subprocess.run(list(map(str, command)), cwd=ROOT, env=env, check=True, timeout=600)

run(python, "-B", "-m", "unittest", "discover", "-s", ROOT / "tests", "-p", "test_*.py")
stomp = ROOT / ".tooling/stomphacks"
run(python, "-B", stomp / "tools-pedal/pedal_common.py", "--selftest")
run(python, "-B", stomp / "tools-pedal/install_selftest.py")
for test in ("converted-nam", "conversion-quality", "cross-platform"):
    run("dotnet", "run", "--project", ROOT / "tests" / test, "-c", "Release")
if args.rid == "win-x64":
    run("dotnet", "build", ROOT / "apps/nam2zoom-desktop", "-c", "Release")
