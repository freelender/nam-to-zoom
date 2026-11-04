"""Verify a relocated portable payload. Never opens MIDI ports or writes to a pedal."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from macos_native import audit_macos_bundle

SOURCE = Path(__file__).resolve().parents[1]


def resource_root(payload, rid):
    return payload if rid == "win-x64" else payload / "nam2zoom.app/Contents/Resources"


def run(*args, env=None, cwd=None):
    subprocess.run(list(map(str, args)), env=env, cwd=cwd, check=True, timeout=600)


def inside(resources, work):
    sys.path.insert(0, str(resources / "tools"))
    sys.path.insert(0, str(SOURCE / "tests"))
    import nam.cli
    import torch
    import numpy as np
    import scipy
    import soundfile as sf
    import mido
    import rtmidi
    import construct
    from nam2zoom.bank import load_models, prepare_bank, build_bank
    from nam2zoom.hybrid import classify
    from nam2zoom.platforms import data_root, renderer
    from test_compact_shape import model
    from test_lite_profiles import lite_model
    from msplus_midi import choose_ports

    assert Path(nam.cli.__file__).is_relative_to(resources / "runtime/python")
    assert Path(torch.__file__).is_relative_to(resources / "runtime/python")
    assert not data_root().is_relative_to(resources)
    assert rtmidi.API_MACOSX_CORE in rtmidi.get_compiled_api() if sys.platform == "darwin" else rtmidi.API_WINDOWS_MM in rtmidi.get_compiled_api()
    ports = choose_ports(["ZOOM MS Plus Series input"], ["ZOOM MS Plus Series output"])
    assert ports.input_name.endswith("input")
    sys.path.insert(0, str(resources / ".tooling/stomphacks/tools-pedal"))
    import pedal_diy
    import file_session
    assert file_session.UPLOAD_MARGIN == 100 * 1024
    assert file_session.UPLOAD_MARGIN_FLOOR == 32 * 1024
    assert pedal_diy.check_resident_collisions(
        [(4, "OTHER.ZD2", "1.00", 0x04001787, 1)], "N2ZBANK.ZD2", 0x04001787)
    assert not Path(pedal_diy.LOGFILE).is_relative_to(resources)
    pedal_diy.log("mock", "fixture.ZD2", 0x04001787, "N2Z Bank", "DRY-RUN-OK")
    assert Path(pedal_diy.LOGFILE).is_file()
    golden = json.loads((SOURCE / "release/precompiled/golden.json").read_text())
    for profile, fixture in (("compact", model(3)), ("lite", lite_model())):
        fixture["version"] = "0.7.0"
        fixture["config"]["submodels"][0]["model"]["version"] = "0.7.0"
        fixture["config"]["submodels"][0]["model"]["config"]["layers"][0]["head1x1"].update(
            out_channels=1, groups=1)
        weights = fixture["config"]["submodels"][0]["model"]["weights"]
        weights[:] = [0.03125] * len(weights)
        path = work / f"{profile}.nam"
        path.write_text(json.dumps(fixture), encoding="utf-8")
        assert classify(path, profile)["status"] == "direct"
        # Export reuse keeps exactly the original .nam bytes and doesn't train.
        exported = work / "Converted_NAM" / ("Compact" if profile == "compact" else "Lite") / path.name
        exported.parent.mkdir(parents=True)
        shutil.copy2(path, exported)
        assert classify(exported, profile)["status"] == "direct"
        for count in (1, 5 if profile == "lite" else 10):
            models = load_models([exported] * count, [f"AMP{i + 1}" for i in range(count)], profile=profile)
            manifest = prepare_bank(models, work / f"{profile}-{count}", profile=profile)
            built = build_bank(manifest)
            for artifact in (built, built.with_suffix(".ZIC")):
                key = f"{profile}-{count}{artifact.suffix}"
                assert hashlib.sha256(artifact.read_bytes()).hexdigest() == golden[key], key
        # Real native renderer, deterministic fixture and finite float audio.
        dry = work / f"{profile}-input.wav"
        sf.write(dry, .1 * np.sin(np.arange(10000) * .03), 44100, subtype="FLOAT")
        output = work / f"{profile}-rendered.wav"
        run(renderer(), path, dry, output)
        samples, rate = sf.read(output)
        assert rate == 44100 and len(samples) == 10000 and np.isfinite(samples).all()
    print("Relocated Python, native rendering, direct conversion/reuse and golden ZD2 checks: PASS")
    invalid = work / "invalid.nam"
    invalid.write_text('{"architecture":"WaveNet"}')
    rejected = subprocess.run([str(renderer()), str(invalid), str(dry), str(work / "invalid.wav")], capture_output=True, text=True)
    assert rejected.returncode == 2 and "NAM rendering failed:" in rejected.stderr


def verify(payload, rid):
    # Keep the copy outside the source's resource lookup ancestry.
    with tempfile.TemporaryDirectory(prefix="nam2zoom relocated package ") as temporary:
        work = Path(temporary)
        relocated = work / "app with spaces"
        shutil.copytree(payload, relocated, symlinks=True)
        resources = resource_root(relocated, rid)
        app = relocated if rid == "win-x64" else relocated / "nam2zoom.app/Contents/MacOS"
        python = resources / ("runtime/python/python.exe" if rid == "win-x64" else "runtime/python/bin/python3")
        executable = app / ("nam2zoom.exe" if rid == "win-x64" else "nam2zoom")
        renderer = resources / "reference/nam_a2/build-core-ninja" / ("core_render.exe" if rid == "win-x64" else "core_render")
        for file in (python, executable, renderer, resources / "runtime/portable.marker", resources / "LICENSE"):
            if not file.is_file():
                raise FileNotFoundError(file)
        if rid == "win-x64":
            for directory in (python.parent, executable.parent, renderer.parent):
                assert (directory / "msvcp140.dll").is_file(), directory
        if rid.startswith("osx"):
            import plistlib
            plist = plistlib.loads((app.parent / "Info.plist").read_bytes())
            assert plist["CFBundleExecutable"] == "nam2zoom"
            assert plist["CFBundlePackageType"] == "APPL"
            for file in (python, executable, renderer):
                assert os.access(file, os.X_OK), file
            # Refuse absolute native dependencies on Homebrew, CI workspaces or
            # developer installs. RPATH/loader-relative wheel dependencies and
            # macOS system libraries are allowed; imports exercise resolution.
            audit_macos_bundle(relocated, rid)
        env = os.environ.copy()
        env.update(PYTHONPATH=str(resources / "tools"), PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1",
                   NAM2ZOOM_DATA_DIR=str(work / "user data"), MPLCONFIGDIR=str(work / "mpl-cache"),
                   MPLBACKEND="Agg", OMP_NUM_THREADS="2", MKL_NUM_THREADS="2", MIDO_BACKEND="mido.backends.rtmidi")
        env.pop("PYTHONHOME", None)
        logs = work / "user data/logs"
        logs.mkdir(parents=True, exist_ok=True)
        env["NAM2ZOOM_PEDAL_LOG"] = str(logs / "pedal_diy.log")
        # Remove developer runtime PATH entries. Native loading must use bundled
        # dependencies; the OS still supplies its standard system libraries.
        env["PATH"] = os.pathsep.join([str(app), str(python.parent),
            str(Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32") if os.name == "nt" else "/usr/bin", "/bin"])
        run(executable, "--smoke-test", env=env, cwd=work)
        run(python, "-B", Path(__file__).resolve(), resources, "--inside", work / "fixtures", env=env, cwd=work)
        # A stable non-silent model exercises the real fixed-point fidelity gate.
        sys.path.insert(0, str(SOURCE / "tests"))
        from test_waveformer_effect import stable_lite
        ready = work / "fixtures/ready-effect.nam"
        ready.write_text(json.dumps(stable_lite()))
        run(executable, "--export-smoke-test", ready, env=env, cwd=work)
        export = relocated / "Converted_NAM/ready-effect-441-resampled.nam"
        assert export.read_bytes() == ready.read_bytes(), "Export changed NAM weights or metadata"
        assert "https://sym.bios.is/?open=nam" in (export.parent / "README.txt").read_text()
        run(executable, "--effect-smoke-test", ready, env=env, cwd=work)
        built = list((work / "user data/effect-smoke").glob("*/build/N2ZBANK.ZD2"))
        assert len(built) == 1, "App effect build missing"
        report = json.loads(built[0].with_name("engine-report.json").read_text())
        assert report["engine"] == "nam2zoom-float-seven-v1"
        assert report["modelSync"] == "dedicated-coefficient-v1" and report["modelCoefficientSlot"] == 12
        assert report["convolutionHistoryPasses"] == 1
        assert report["convolutionGroupSamples"] == 2
        assert report["processingSamples"] == 16
        assert report["historyBytes"] == 81624
        assert report["declaredDspLoad"] == 260 and len(report["captures"]) == 5
        assert report["experimentalDspLoad"] is True and report["measuredDspPercent"] is None
        assert report["controls"] == ["Model", "Gain", "Volume", "Mix", "Bass", "Middle", "Treble"]
        assert report["controlPages"] == [["Model", "Gain", "Volume", "Mix"], ["Bass", "Middle", "Treble"]]
        assert report["weightsQuantized"] is False
        assert built[0].with_suffix(".ZIC").read_bytes() == (resources / "release/templates-lite/N2ZBANK.ZIC").read_bytes()
        assert report["labels"] == ["MODEL1", "MODEL2", "MODEL3", "MODEL4", "MODEL5"]
        run(executable, "--effect-compact-smoke-test", ready, env=env, cwd=work)
        compact_built = list((work / "user data/effect-compact-smoke").glob("*/build/N2ZBANK.ZD2"))
        assert len(compact_built) == 1
        compact_report = json.loads(compact_built[0].with_name("engine-report.json").read_text())
        assert compact_report["effectMode"] == "compact" and compact_report["declaredDspLoad"] == 190
        assert compact_report["modelSync"] == report["modelSync"] and compact_report["modelCoefficientSlot"] == 12
        assert compact_report["internalSampleRate"] == 33075 and compact_report["sampleRate"] == 44100
        assert compact_report["delayAdjustment"] == "round-each-tap-3-over-4-precomputed-v1"
        assert compact_report["addedLatencySamples"] == 64
        assert compact_report["captures"] == report["captures"], "Compact changed the input NAM weights"
        from nam2zoom.artwork import compact_icon
        assert compact_built[0].with_suffix(".ZIC").read_bytes() == compact_icon(built[0].with_suffix(".ZIC").read_bytes())
        run(executable, "--effect-slots-smoke-test", ready, env=env, cwd=work)
        slot_reports = list((work / "user data").glob("slots-smoke-*/*/build/engine-report.json"))
        assert len(slot_reports) == 6
        from nam2zoom.identity import effect_slot, identify
        from offline_effect_audit import audit_bytes
        for path in slot_reports:
            report = json.loads(path.read_text())
            slot = effect_slot(report["effectSlot"])
            effect = path.with_name(slot.filename)
            actual_slot, zd2 = identify(effect)
            assert actual_slot == slot and zd2.name == f"NAM AMP{slot.number}"
            assert report["nameOnArtwork"] and len(report["captures"]) == 5
            assert not audit_bytes(effect.read_bytes(), effect.with_suffix(".ZIC").read_bytes(), {})
        for profile in ("compact", "lite"):
            run(python, "-B", SOURCE / "tests/portable-runtime/train_smoke.py", resources,
                work / ("train-" + profile), "--profile", profile, env=env, cwd=work)
        # Opens/closes a real window. No model or device action is invoked.
        run(executable, "--gui-smoke-test", env=env, cwd=work)
        assert (work / "user data/training/TRAINING_DI.wav").is_file()
        assert not (resources / "Converted_NAM/Lite").exists()
        assert not (resources / "Backup").exists()
        print("Portable startup, CPU training, bundle structure and writable-data checks: PASS")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("payload", type=Path)
    parser.add_argument("--rid", choices=("win-x64", "osx-arm64", "osx-x64"))
    parser.add_argument("--inside", type=Path)
    args = parser.parse_args()
    if args.inside:
        args.inside.mkdir(parents=True)
        inside(args.payload, args.inside)
    else:
        if args.rid is None:
            parser.error("--rid is required")
        verify(args.payload.resolve(strict=True), args.rid)
