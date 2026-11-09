"""Exercise release build configuration and the final ZIP/checksum contract."""
import hashlib
import ast
import os
from pathlib import Path
import shutil
import subprocess
import sys
import json
import tarfile
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "release"))
from build_cross_platform import archive_payload, build_intel_torch, split_runtime


class ReleaseBuildTests(unittest.TestCase):
    def test_split_runtime_carries_licenses_in_both_downloads(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            payload = root / "full"
            output = root / "dist" / "nam2zoom-test"
            python = payload / "runtime/python"
            python.mkdir(parents=True)
            (python / "LICENSE.txt").write_text("Python license")
            (payload / "LICENSE").write_text("App license")
            notices = payload / "ThirdPartyLicenses"
            notices.mkdir()
            (notices / "README.md").write_text("Dependency notices")
            archive = split_runtime(payload, output, "win-x64", "2.0.0")
            self.assertFalse((output / "runtime/python").exists())
            manifest = json.loads((output / "runtime/download.json").read_text())
            self.assertEqual(manifest["sha256"], hashlib.sha256(archive.read_bytes()).hexdigest())
            self.assertEqual(manifest["size"], archive.stat().st_size)
            with tarfile.open(archive) as runtime:
                for name in ("LICENSE", "ThirdPartyLicenses/README.md"):
                    self.assertEqual(runtime.extractfile(name).read(), (output / name).read_bytes())
                self.assertEqual(runtime.extractfile("python/LICENSE.txt").read(), b"Python license")

    def test_pytorch_patch_pins_both_cmake_interpreter_names(self):
        if not shutil.which("git"):
            self.skipTest("Git unavailable")
        # Exact defines block from the pinned PyTorch v2.11.0 helper.
        original = """class CMake:
    def generate(self):
        CMake.defines(
            args,
            Python_EXECUTABLE=sys.executable,
            TORCH_BUILD_VERSION=version,
            **build_options,
        )
"""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            helper = root / "tools/setup_helpers/cmake.py"
            helper.parent.mkdir(parents=True)
            helper.write_text(original, encoding="utf-8", newline="\n")
            subprocess.run(["git", "init", "--quiet", str(root)], check=True)
            patch_path = ROOT / "patches/pytorch-build-python.patch"
            for args in (["--check", str(patch_path)], [str(patch_path)]):
                subprocess.run(["git", "apply", *args], cwd=root, check=True, capture_output=True)
            tree = ast.parse(helper.read_text())
            statement = tree.body[0].body[0].body[0]
            recorded = {}
            def defines(args, **kwargs):
                recorded.update(kwargs)
            interpreter = str(root / "bundled python with spaces")
            exec(compile(ast.Module(body=[statement], type_ignores=[]), str(helper), "exec"),
                 {"CMake": SimpleNamespace(defines=defines),
                  "sys": SimpleNamespace(executable=interpreter), "args": [],
                  "version": "2.11.0", "build_options": {}})
            self.assertEqual(recorded["Python_EXECUTABLE"], interpreter)
            self.assertEqual(recorded["PYTHON_EXECUTABLE"], interpreter)

    def test_generator_failure_stops_before_cpp_build(self):
        with tempfile.TemporaryDirectory() as temporary:
            calls = []
            failure = subprocess.CalledProcessError(1, ["python", "-m", "peachpy.x86_64"])
            def run(*command, **kwargs):
                calls.append(command)
                if command[1:3] == ("-m", "peachpy.x86_64"):
                    raise failure
            with patch("build_cross_platform.run", side_effect=run):
                with self.assertRaises(subprocess.CalledProcessError) as error:
                    build_intel_torch(Path("python"), Path(temporary))
            self.assertIs(error.exception, failure)
            self.assertFalse(any("bdist_wheel" in command for command in calls))

    def test_intel_torch_build_preserves_version_and_uses_supported_apple_blas(self):
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            python = work / "bundled python"
            calls = []

            def run(*command, **kwargs):
                calls.append((command, kwargs))
                if command[1:3] == ("setup.py", "bdist_wheel"):
                    wheel = kwargs["cwd"] / "dist/torch-2.11.0-cp312-cp312-macosx_14_0_x86_64.whl"
                    wheel.parent.mkdir(parents=True)
                    wheel.write_bytes(b"fixture")

            with patch("build_cross_platform.run", side_effect=run), \
                 patch.dict(os.environ, {"BLAS": "Accelerate", "USE_CUDA": "1", "USE_OPENMP": "1"}):
                build_intel_torch(python, work)
            clone, patch_check, patch_apply, requirements, generator, build, install = calls
            self.assertIn("v2.11.0", clone[0])
            self.assertIn("--recursive", clone[0])
            self.assertEqual(patch_check[0][:3], ("git", "apply", "--check"))
            self.assertEqual(patch_apply[0][:2], ("git", "apply"))
            self.assertEqual(patch_check[0][-1], ROOT / "patches/pytorch-build-python.patch")
            self.assertEqual(patch_apply[0][-1], patch_check[0][-1])
            self.assertEqual(generator[0], (python, "-m", "peachpy.x86_64", "--help"))
            self.assertEqual(generator[1]["env"]["PYTHONPATH"],
                             str(work / "pytorch/third_party/python-peachpy"))
            self.assertEqual(requirements[1]["env"]["PIP_CONSTRAINT"],
                             str(ROOT / "release/macos-intel-constraints.txt"))
            environment = build[1]["env"]
            # v2.11.0 cmake/Dependencies.cmake accepts vecLib, not Accelerate.
            self.assertEqual(environment["BLAS"], "vecLib")
            for feature in ("USE_CUDA", "USE_MPS", "USE_OPENMP", "USE_MKL", "USE_MKLDNN", "USE_DISTRIBUTED"):
                self.assertEqual(environment[feature], "0")
            self.assertEqual(environment["PYTORCH_BUILD_VERSION"], "2.11.0")
            self.assertEqual(install[0][:4], (python, "-m", "pip", "install"))
            self.assertTrue(install[0][-1].is_file())

    def test_intel_build_requires_exactly_one_wheel_before_installing(self):
        for count in (0, 2):
            with self.subTest(count=count), tempfile.TemporaryDirectory() as temporary:
                work = Path(temporary)
                wheels = work / "pytorch/dist"
                wheels.mkdir(parents=True)
                for index in range(count):
                    (wheels / f"torch-{index}.whl").write_bytes(b"fixture")
                with patch("build_cross_platform.run") as run:
                    with self.assertRaisesRegex(RuntimeError, "exactly one wheel"):
                        build_intel_torch(work / "python", work)
                self.assertEqual(run.call_count, 6)

    def test_windows_zip_layout_checksum_and_existing_output_guard(self):
        with tempfile.TemporaryDirectory() as temporary:
            payload = Path(temporary) / "app with spaces"
            payload.mkdir()
            (payload / "nam2zoom.exe").write_bytes(b"fixture executable")
            archive_payload(payload, "win-x64")
            archive = payload.with_suffix(".zip")
            with zipfile.ZipFile(archive) as zipped:
                self.assertIsNone(zipped.testzip())
                self.assertEqual(zipped.read("app with spaces/nam2zoom.exe"), b"fixture executable")
            expected = hashlib.sha256(archive.read_bytes()).hexdigest() + "  " + archive.name + "\n"
            self.assertEqual(Path(str(archive) + ".sha256").read_text(), expected)
            with self.assertRaises(FileExistsError):
                archive_payload(payload, "win-x64")
