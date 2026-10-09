"""Target-native portable packaging. Requires uv, git, CMake and .NET 10 on CI.

No TI tools, Apple secrets, local venvs or end-user downloads are used.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]


def run(*args, cwd=ROOT, env=None):
    print("Running:", *map(str, args), flush=True)
    subprocess.run(list(map(str, args)), cwd=cwd, env=env, check=True)


def python_at(home):
    return home / ("python.exe" if os.name == "nt" else "bin/python3")


def checkout_dependencies():
    pins = json.loads((ROOT / "release/dependencies.json").read_text())
    for name, pin in pins.items():
        target = ROOT / ".tooling" / name
        if target.exists():
            head = subprocess.check_output(["git", "-C", str(target), "rev-parse", "HEAD"], text=True).strip()
            if head != pin["revision"]:
                raise RuntimeError(f"{name}: expected pinned revision {pin['revision']}, got {head}")
        else:
            run("git", "clone", pin["url"], target)
            run("git", "checkout", "--detach", pin["revision"], cwd=target)
        if pin.get("submodules"):
            # Match setup.ps1: only the direct Core dependencies are used.
            # AudioDSPTools' nested duplicate Eigen checkout is not needed.
            run("git", "submodule", "update", "--init", cwd=target)
    # Catalogue patches touch the separately cloned zoom-zt2 child, so every
    # checkout must exist before any cross-checkout patch is applied.
    for name, pin in pins.items():
        target = ROOT / ".tooling" / name
        for patch in pin["patches"]:
            patch_path = ROOT / "patches" / patch
            applied = subprocess.run(["git", "apply", "--reverse", "--check", str(patch_path)], cwd=target, capture_output=True)
            if applied.returncode:
                run("git", "apply", "--check", patch_path, cwd=target)
                run("git", "apply", patch_path, cwd=target)


def build_intel_torch(python, work):
    # Official macOS x64 wheels stop at 2.2.x. Build the existing trainer version
    # rather than introducing an old trainer with different behavior.
    torch_source = work / "pytorch"
    run("git", "clone", "--branch", "v2.11.0", "--depth", "1", "--recursive",
        "--shallow-submodules", "https://github.com/pytorch/pytorch.git", torch_source)
    env = os.environ.copy()
    env["PIP_CONSTRAINT"] = str(ROOT / "release/macos-intel-constraints.txt")
    run(python, "-m", "pip", "install", "-r", torch_source / "requirements.txt", env=env)
    env.update(USE_CUDA="0", USE_MPS="0", USE_DISTRIBUTED="0", BUILD_TEST="0",
               USE_KINETO="0", USE_OPENMP="0", USE_MKL="0", USE_MKLDNN="0",
               BLAS="Accelerate", MAX_JOBS="3", PYTORCH_BUILD_VERSION="2.11.0", PYTORCH_BUILD_NUMBER="1")
    run(python, "setup.py", "bdist_wheel", cwd=torch_source, env=env)
    wheels = list((torch_source / "dist").glob("torch-*.whl"))
    if len(wheels) != 1:
        raise RuntimeError("Intel PyTorch did not produce exactly one wheel")
    run(python, "-m", "pip", "install", wheels[0])


def collect_licenses(resources, app, python_home):
    target = resources / "ThirdPartyLicenses"
    target.mkdir()
    dotnet = Path(shutil.which("dotnet")).resolve().parent
    for name in ("LICENSE.txt", "ThirdPartyNotices.txt"):
        shutil.copy2(dotnet / name, target / ("dotnet-" + name))
    for name in ("stomphacks", "neural-amp-modeler", "NeuralAmpModelerCore"):
        shutil.copy2(ROOT / ".tooling" / name / "LICENSE", target / (name + ".txt"))
    for base, prefix in ((python_home, "python"), (ROOT / ".tooling/NeuralAmpModelerCore/Dependencies", "core")):
        for source in base.rglob("*"):
            if source.is_file() and source.name.upper().startswith(("LICENSE", "COPYING", "NOTICE", "AUTHORS")):
                destination = target / prefix / source.relative_to(base)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
    # Include package metadata and available license/readme files for every
    # shipped NuGet package (Avalonia, Skia, HarfBuzz and their dependencies).
    assets = json.loads((ROOT / "apps/nam2zoom-avalonia/obj/project.assets.json").read_text())
    packages = [Path(folder) for folder in assets["packageFolders"]]
    for name, library in assets["libraries"].items():
        if library["type"] != "package":
            continue
        package = next((p / library["path"] for p in packages if (p / library["path"]).is_dir()), None)
        if package is None:
            raise RuntimeError(f"Missing NuGet notices: {name}")
        for source in package.rglob("*"):
            if source.is_file() and (source.name.lower().startswith(("license", "copying", "notice", "readme")) or source.suffix == ".nuspec"):
                destination = target / "nuget" / library["path"] / source.relative_to(package)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
    # Native libraries' upstream notices are included in the NuGet packages;
    # keep the resolved package inventory to make license auditing reproducible.
    (target / "nuget-packages.json").write_text(json.dumps(assets["libraries"], indent=2))


def build(rid, python, cuda=False, adhoc_sign=False):
    expected = {"win-x64": ("Windows", "amd64"), "osx-arm64": ("Darwin", "arm64"), "osx-x64": ("Darwin", "x86_64")}
    system, machine = expected[rid]
    if platform.system() != system or platform.machine().lower() != machine:
        raise RuntimeError(f"Build {rid} on its native runner, not {platform.system()}/{platform.machine()}")
    version = ET.parse(ROOT / "Directory.Build.props").findtext("PropertyGroup/Version")
    tag = os.environ.get("GITHUB_REF", "")
    if tag.startswith("refs/tags/") and tag != f"refs/tags/v{version}":
        raise RuntimeError("Version tag must match Directory.Build.props")
    label = {"win-x64": "windows-x64", "osx-arm64": "macos-arm64", "osx-x64": "macos-x64"}[rid]
    name = f"nam2zoom-v{version}-{label}"
    work = ROOT / ".tooling" / ("cross-build-" + rid)
    payload = ROOT / "dist/cross-platform" / name
    if payload.exists() or (payload.parent / (name + ".zip")).exists():
        raise FileExistsError(f"Output exists: {payload}; preserve it or choose a new version")
    work.mkdir(parents=True, exist_ok=True)
    payload.mkdir(parents=True)
    checkout_dependencies()
    if rid.startswith("osx"):
        app = payload / "nam2zoom.app/Contents/MacOS"
        resources = payload / "nam2zoom.app/Contents/Resources"
    else:
        app = resources = payload
    app.mkdir(parents=True, exist_ok=True)
    resources.mkdir(parents=True, exist_ok=True)
    for directory in ("tools", "dsp", "training"):
        shutil.copytree(ROOT / directory, resources / directory,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for profile, folder in (("compact", "templates"), ("lite", "templates-lite")):
        shutil.copytree(ROOT / "release/precompiled" / profile, resources / "release" / folder)
    stomp = resources / ".tooling/stomphacks"
    for folder in ("tools-pedal", "tools", "zoom-zt2"):
        (stomp / folder).mkdir(parents=True)
    for file in ("safe_connect.py", "pedal_diy.py", "readback.py", "pedal_common.py", "file_session.py", "stock_catalog.py"):
        shutil.copy2(ROOT / ".tooling/stomphacks/tools-pedal" / file, stomp / "tools-pedal" / file)
    shutil.copy2(ROOT / ".tooling/stomphacks/tools/flst_check.py", stomp / "tools/flst_check.py")
    for file in ("zoomzt2.py", "decode_preset.py", "LICENSE"):
        shutil.copy2(ROOT / ".tooling/stomphacks/zoom-zt2" / file, stomp / "zoom-zt2" / file)
    shutil.copy2(ROOT / ".tooling/stomphacks/SAFETY.md", stomp / "SAFETY.md")
    # Python-build-standalone from uv is relocatable, unlike copied venvs or the
    # runner's setup-python installation. Install packages directly into it.
    original_home = python.parent if os.name == "nt" else python.parent.parent
    python_home = resources / "runtime/python"
    shutil.copytree(original_home, python_home, symlinks=True,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    # This copy belongs to the app, not uv. Leave the managed source untouched.
    standard_library = python_home / ("Lib" if os.name == "nt" else "lib/python3.12")
    (standard_library / "EXTERNALLY-MANAGED").unlink(missing_ok=True)
    bundled = python_at(python_home)
    run(bundled, "-m", "ensurepip", "--upgrade")
    run(bundled, "-m", "pip", "install", "--upgrade", "pip", "wheel", "setuptools==78.1.0")
    run(bundled, "-m", "pip", "install", "--only-binary=:all:", "-r", ROOT / "release/backend-requirements.txt")
    if rid == "osx-x64":
        run(bundled, "-m", "pip", "install", "numpy==1.26.4")
        build_intel_torch(bundled, work)
    elif rid == "win-x64":
        run(bundled, "-m", "pip", "install", "torch==2.11.0", "--index-url",
            "https://download.pytorch.org/whl/" + ("cu128" if cuda else "cpu"),
            "-c", ROOT / "release/training-constraints.txt")
    else:
        run(bundled, "-m", "pip", "install", "--only-binary=:all:", "torch==2.11.0")
    env = os.environ.copy()
    env["SETUPTOOLS_SCM_PRETEND_VERSION_FOR_NEURAL_AMP_MODELER"] = "0.1.dev1"
    run(bundled, "-m", "pip", "wheel", "--no-deps", "--wheel-dir", work,
        ROOT / ".tooling/neural-amp-modeler", env=env)
    wheels = list(work.glob("neural_amp_modeler-*.whl"))
    if len(wheels) != 1:
        raise RuntimeError("Expected one patched NAM wheel")
    constraints = (ROOT / "release/training-constraints.txt" if rid == "win-x64" else
                   ROOT / "release/macos-intel-constraints.txt" if rid == "osx-x64" else None)
    run(bundled, "-m", "pip", "install", "--only-binary=:all:",
        *(["-c", constraints] if constraints else []), wheels[0], "soundfile==0.14.0")
    run(bundled, "-m", "pip", "check")
    (resources / "runtime/portable.marker").write_text("nam2zoom.cross-platform.v1\n")
    inventory = subprocess.check_output([str(bundled), "-m", "pip", "freeze"], text=True)
    (resources / "runtime/installed-packages.txt").write_text(inventory)
    run("cmake", "-S", ROOT / "reference/nam_a2", "-B", work / "renderer",
        f"-DCORE_ROOT={ROOT / '.tooling/NeuralAmpModelerCore'}", "-DCMAKE_BUILD_TYPE=Release")
    run("cmake", "--build", work / "renderer", "--config", "Release", "--target", "core_render", "--parallel", "3")
    renderer = next((work / "renderer").rglob("core_render.exe" if os.name == "nt" else "core_render"))
    destination = resources / "reference/nam_a2/build-core-ninja" / renderer.name
    destination.parent.mkdir(parents=True)
    shutil.copy2(renderer, destination)
    if rid == "win-x64":
        # App-local redistributable CRT: no administrator installer on user PCs.
        vswhere = Path(os.environ["ProgramFiles(x86)"]) / "Microsoft Visual Studio/Installer/vswhere.exe"
        visual_studio = Path(subprocess.check_output([str(vswhere), "-latest", "-products", "*",
            "-requires", "Microsoft.VisualStudio.Component.VC.Tools.x86.x64", "-property", "installationPath"], text=True).strip())
        crt_sets = sorted((visual_studio / "VC/Redist/MSVC").glob("*/x64/Microsoft.VC*.CRT"))
        if not crt_sets:
            raise RuntimeError("Redistributable app-local MSVC CRT missing on build runner")
        crt_files = list(crt_sets[-1].glob("*.dll"))
        if not any(file.name == "msvcp140.dll" for file in crt_files):
            raise RuntimeError("MSVC CRT incomplete")
        for directory in (python_home, destination.parent, app):
            for file in crt_files:
                shutil.copy2(file, directory / file.name)
    run("dotnet", "publish", ROOT / "apps/nam2zoom-avalonia", "-c", "Release", "-r", rid,
        "--self-contained", "true", "-p:PublishSingleFile=false", "-p:PublishTrimmed=false", "-o", app)
    collect_licenses(resources, app, python_home)
    if rid == "win-x64":
        (resources / "ThirdPartyLicenses/MSVC-Redistributable.txt").write_text(
            "Microsoft Visual C++ Runtime redistributable DLLs, supplied app-local from the build runner's licensed Visual Studio installation.\n"
            "Copyright Microsoft Corporation. Terms: https://visualstudio.microsoft.com/license-terms/\n")
    shutil.copy2(ROOT / "LICENSE", resources)
    shutil.copy2(ROOT / "docs/PORTABLE.md", payload / "README.md")
    if rid.startswith("osx"):
        import plistlib
        (app.parent / "Info.plist").write_bytes(plistlib.dumps({
            "CFBundleName": "nam2zoom", "CFBundleDisplayName": "nam2zoom",
            "CFBundleIdentifier": "com.freelender.nam2zoom", "CFBundleExecutable": "nam2zoom",
            "CFBundlePackageType": "APPL", "CFBundleShortVersionString": version.split("-")[0],
            "CFBundleVersion": version.split("-")[0], "LSMinimumSystemVersion": "14.0",
            "NSHighResolutionCapable": True, "NSPrincipalClass": "NSApplication"}))
        for file in (app / "nam2zoom", destination, bundled.resolve()):
            file.chmod(file.stat().st_mode | 0o111)
        # Native tools may supply their own ad-hoc signatures. Packaging never
        # rewrites Mach-O load paths. Bundle signing is optional and needs no
        # certificates for this explicit local ad-hoc mode.
        if adhoc_sign:
            for file in sorted(resources.rglob("*")):
                if file.is_file() and not file.is_symlink() and file.suffix in (".so", ".dylib"):
                    run("codesign", "--force", "--sign", "-", file)
            run("codesign", "--force", "--deep", "--sign", "-", payload / "nam2zoom.app")
    # The verifier runs from a copied payload with spaces, using its own Python,
    # and rejects any runtime dependency on the original checkout.
    run(sys.executable, ROOT / "release/verify_portable.py", payload, "--rid", rid)
    archive_payload(payload, rid)


def archive_payload(payload, rid):
    name = payload.name
    archive = payload.parent / (name + ".zip")
    if archive.exists():
        raise FileExistsError(f"Archive already exists: {archive}")
    if rid.startswith("osx"):
        run("ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", payload, archive)
    else:
        shutil.make_archive(str(archive)[:-4], "zip", payload.parent, payload.name)
    import zipfile
    with zipfile.ZipFile(archive) as zipped:
        assert zipped.testzip() is None
        main = name + ("/nam2zoom.exe" if rid == "win-x64" else "/nam2zoom.app/Contents/MacOS/nam2zoom")
        info = zipped.getinfo(main)
        if rid.startswith("osx"):
            assert (info.external_attr >> 16) & 0o111, "ZIP lost executable permissions"
    checksum = hashlib.sha256()
    with archive.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            checksum.update(block)
    (archive.parent / (archive.name + ".sha256")).write_text(checksum.hexdigest() + "  " + archive.name + "\n")
    print(f"Portable package: {archive}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rid", required=True, choices=("win-x64", "osx-arm64", "osx-x64"))
    parser.add_argument("--python", required=True, type=Path, help="uv managed Python 3.12 executable")
    parser.add_argument("--cuda", action="store_true", help="bundle Windows CUDA instead of CPU wheels")
    parser.add_argument("--adhoc-sign", action="store_true", help="optional macOS local ad-hoc bundle signature; no identity/account")
    args = parser.parse_args()
    build(args.rid, args.python.resolve(strict=True), args.cuda, args.adhoc_sign)
