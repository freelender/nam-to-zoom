"""Compatibility checks for banks installed by the previous portable release."""

import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / ".tooling/stomphacks/tools-pedal"))

from nam2zoom import deploy
from nam2zoom.devices import require_supported_device
import offline_effect_audit
import zd2
import pedal_diy


class BankCompatibilityTests(unittest.TestCase):
    def test_installer_recognizes_new_and_previous_bank_ids(self):
        for effect_id in (deploy.BANK_ID, 0x07000F87):
            with self.subTest(effect_id=effect_id), \
                 patch.object(pedal_diy, "read_zd2", return_value=(effect_id, "N2Z Bank")):
                self.assertTrue(pedal_diy.classify(deploy.BANK_NAME)[0])
        self.assertFalse(pedal_diy.is_diy_id(0x04001788))
        self.assertFalse(pedal_diy.is_diy_id(0x04011787))

    def test_installer_still_refuses_stock_collisions(self):
        for ids, names, filenames in (({deploy.BANK_ID}, set(), set()),
                                     (set(), {"N2Z Bank"}, set()),
                                     (set(), set(), {deploy.BANK_NAME})):
            with self.subTest(ids=ids, names=names, filenames=filenames), \
                 patch.object(pedal_diy, "read_zd2", return_value=(deploy.BANK_ID, "N2Z Bank")), \
                 patch.object(pedal_diy, "stock_index", return_value=(ids, names, filenames)):
                self.assertFalse(pedal_diy.classify(deploy.BANK_NAME)[0])
        with patch.object(pedal_diy, "read_zd2", return_value=(deploy.BANK_ID, "N2Z Bank")), \
             patch.object(pedal_diy, "stock_zic_bases", return_value={deploy.BANK_ICON}):
            self.assertFalse(pedal_diy.classify(deploy.BANK_NAME)[0])

    def check_existing(self, mode, effect_id, name="N2Z Bank", device=None):
        with tempfile.TemporaryDirectory() as temporary:
            session = Path(temporary)
            backup = session / "backup"
            files = backup / "files"
            files.mkdir(parents=True)
            for filename in (deploy.BANK_NAME, deploy.BANK_ICON, "FLST_SEQ.ZT2"):
                (files / filename).write_bytes(b"fixture")
            family, model, firmware = device.identity if device else (1, 1, "1.40")
            (backup / "manifest.json").write_text(json.dumps({"identity": {
                "family_code": family, "model_number": model, "version": firmware}}))
            profile = device or SimpleNamespace(name="MS-50G+", firmware="1.40", patch_count=1)
            entries = [(effect_id >> 24, deploy.BANK_NAME, "0.01", effect_id, 1)]
            flst = Mock()
            flst.validate_flst.return_value = (True, [], entries)
            flst.parse_entries.return_value = entries
            outputs = [f"Family: 0x{family:04x}\nModel: 0x{model:04x}\nVersion: {firmware}\n",
                       f"Patches: {profile.patch_count}\n"]
            outputs.extend([""] * profile.patch_count)
            outputs.append("\n".join((deploy.BANK_NAME, deploy.BANK_ICON, "FLST_SEQ.ZT2")))

            def download(filename, destination):
                destination.write_bytes((files / filename).read_bytes())

            with patch.object(deploy, "_profile", side_effect=(
                     deploy._profile if device else lambda *_: profile)), \
                 patch.object(deploy, "require_stock_patches") as stock_patches, \
                 patch.object(deploy, "require_stock_patch") as stock_patch, \
                 patch.object(deploy, "_flst", return_value=flst), \
                 patch.object(deploy, "_run", side_effect=outputs), \
                 patch.object(deploy, "_download", side_effect=download), \
                 patch.object(offline_effect_audit, "load_backup", return_value=(
                     {deploy.BANK_NAME: effect_id}, {"n2z bank"}, files / "FLST_SEQ.ZT2")), \
                 patch.object(zd2, "parse_zd2_bytes", return_value=SimpleNamespace(
                     effect_id=effect_id, name=name)):
                if mode == "backup":
                    result = deploy.plan_backup(None, None, backup, session / "current")
                    stock_patches.assert_called_once_with(session / "current", backup, profile.patch_count)
                    return result
                result = deploy.plan_live(None, None, session, session / "current")[0]
                self.assertEqual(stock_patch.call_count, profile.patch_count + 1)
                return result

    def test_ms60b_plus_both_preflights_accept_previous_and_current_banks(self):
        device = require_supported_device(0x006E, 0x0027, "1.20")
        for mode in ("backup", "live"):
            for effect_id in (0x07000F87, deploy.BANK_ID):
                with self.subTest(mode=mode, effect_id=hex(effect_id)):
                    self.assertTrue(self.check_existing(mode, effect_id, device=device))

    def test_both_preflights_accept_previous_and_current_banks(self):
        for mode in ("backup", "live"):
            for effect_id in (0x07000F87, deploy.BANK_ID):
                with self.subTest(mode=mode, effect_id=hex(effect_id)):
                    self.assertTrue(self.check_existing(mode, effect_id))

    def test_both_preflights_reject_unrelated_identity(self):
        for mode in ("backup", "live"):
            for effect_id, name in ((0x07000F88, "N2Z Bank"),
                                    (0x07000F87, "Other effect")):
                with self.subTest(mode=mode, effect_id=effect_id, name=name):
                    with self.assertRaisesRegex(deploy.DeployError, "unexpected identity"):
                        self.check_existing(mode, effect_id, name)

    def test_new_candidate_still_requires_current_id(self):
        with tempfile.TemporaryDirectory() as temporary:
            effect = Path(temporary) / deploy.BANK_NAME
            effect.write_bytes(b"fixture")
            with patch.object(zd2, "parse_zd2_bytes", return_value=SimpleNamespace(
                    effect_id=0x07000F87, name="N2Z Bank")):
                for preflight, args in (
                    (deploy.plan_backup, (effect, None, Path(temporary), effect)),
                    (deploy.plan_live, (effect, None, Path(temporary), effect)),
                ):
                    with self.assertRaisesRegex(deploy.DeployError, "new N2ZBANK"):
                        preflight(*args)


if __name__ == "__main__":
    unittest.main()
