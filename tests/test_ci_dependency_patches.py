"""Replay release patches against original pinned blobs with macOS Git settings."""
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "release"))
from build_cross_platform import normalize_patch_inputs


class DependencyPatchTests(unittest.TestCase):
    def test_all_stomphacks_patches_apply_to_original_crlf_blob_and_reapply_cleanly(self):
        if not shutil.which("git"):
            self.skipTest("Git unavailable")
        pins = json.loads((ROOT / "release/dependencies.json").read_text(encoding="utf-8"))
        parent = ROOT / ".tooling/stomphacks"
        child = parent / "zoom-zt2"
        if not (parent / ".git").exists() or not (child / ".git").exists():
            self.skipTest("CI provisions pinned dependencies before running this regression")

        def git(*args, cwd=parent, check=True):
            return subprocess.run(["git", "-c", "core.autocrlf=false", *args], cwd=cwd,
                                  capture_output=True, check=check)

        patches = [ROOT / "patches" / name for name in pins["stomphacks"]["patches"]]
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            git("init", cwd=work)
            # Materialize exact Git blobs, independent of this host's checkout
            # conversion and existing local patches. No network or reset needed.
            for patch in patches:
                names = re.findall(r"^\+\+\+ b/(.+)$", patch.read_text(encoding="utf-8"), re.M)
                for name in names:
                    target = work / name
                    if target.exists():
                        continue
                    target.parent.mkdir(parents=True, exist_ok=True)
                    is_child = name.startswith("zoom-zt2/")
                    key = "stomphacks/zoom-zt2" if is_child else "stomphacks"
                    source = name.removeprefix("zoom-zt2/") if is_child else name
                    target.write_bytes(git("show", pins[key]["revision"] + ":" + source,
                                           cwd=child if is_child else parent).stdout)
            target = work / "zoom-zt2/zoomzt2.py"
            self.assertIn(b"\r\n", target.read_bytes())
            # Same check fails on the unnormalized macOS/Linux worktree.
            git("apply", str(patches[0]), cwd=work)
            failed = git("apply", "--check", str(patches[1]), cwd=work, check=False)
            self.assertNotEqual(failed.returncode, 0)
            self.assertIn(b"zoomzt2.py", failed.stderr)
            normalize_patch_inputs(work / "zoom-zt2", pins["stomphacks/zoom-zt2"]["lf_patch_inputs"])
            for patch in patches[1:]:
                git("apply", "--check", str(patch), cwd=work)
                git("apply", str(patch), cwd=work)
            patched = target.read_bytes()
            self.assertIn(b'"catalog_flags" / Default(Byte, 0)', patched)
            self.assertIn(b"PREAMP = 4", patched)
            self.assertNotIn(b"\r\n", patched)
            normalize_patch_inputs(work / "zoom-zt2", ["zoomzt2.py"])
            self.assertEqual(target.read_bytes(), patched)
            for patch in patches:
                # This is the release script's already-applied detection.
                git("apply", "--reverse", "--check", str(patch), cwd=work)

    def test_normalization_preserves_other_bytes_and_rejects_escape(self):
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            source = work / "source.py"
            source.write_bytes(b"# \xc3\xa9\r\nkeep = b'\\r\\n'\nlast\rbyte\r\n")
            normalize_patch_inputs(work, ["source.py"])
            self.assertEqual(source.read_bytes(), b"# \xc3\xa9\nkeep = b'\\r\\n'\nlast\rbyte\n")
            with self.assertRaises(ValueError):
                normalize_patch_inputs(work, ["../outside.py"])


if __name__ == "__main__":
    unittest.main()
