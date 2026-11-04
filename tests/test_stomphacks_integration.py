"""Keep existing banks buildable under the updated upstream identity rules."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
STOMP = ROOT / ".tooling/stomphacks"
sys.path.insert(0, str(ROOT / "tools"))
from nam2zoom.bank import prepare_bank, OWN_HOST_COEFFICIENT_SLOTS
from nam2zoom.identity import SLOTS


@unittest.skipUnless((STOMP / "tools/zd2_make_effect.py").is_file(), "Stomphacks checkout required")
class StomphacksIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("stomphacks_builder", STOMP / "tools/zd2_make_effect.py")
        cls.builder = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.builder)

    def manifest(self, root, **updates):
        data = json.loads((STOMP / "effects/gain/manifest.json").read_text())
        data.update(updates)
        path = root / "manifest.json"
        path.write_text(json.dumps(data))
        return path

    def test_existing_bank_pairs_build_without_relaxing_other_prefixes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for slot in SLOTS:
                with self.subTest(slot=slot.number):
                    manifest = self.manifest(root, name="N2Z Bank", filename=slot.stem,
                                             id=f"{slot.effect_id:08x}", allow_any_id=True)
                    self.assertEqual(self.builder.load_manifest(manifest)["filename"], slot.stem)
            for name, eid in (("N2ZOTHER", "04001787"), ("N2ZBANK", "04001788")):
                with self.subTest(name=name, eid=eid):
                    manifest = self.manifest(root, filename=name, id=eid, allow_any_id=True)
                    with self.assertRaises(SystemExit):
                        self.builder.load_manifest(manifest)

    def test_legacy_bank_exception_keeps_stock_name_check(self):
        with tempfile.TemporaryDirectory() as temporary:
            manifest = self.manifest(Path(temporary), name="Hall REV", filename="N2ZBANK",
                                     id="04001787", allow_any_id=True)
            with self.assertRaises(SystemExit):
                self.builder.load_manifest(manifest)

    def test_own_host_explicit_control_slots_survive_new_default_order(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            model = (root / "model.nam", "MODEL", bytes(1871 * 4), "fixture")
            for compact in (False, True):
                manifest = prepare_bank([model], root / str(compact), profile="lite",
                                        own_host=True, compact_effect=compact)
                parsed = self.builder.load_manifest(manifest)
                self.assertEqual({p["name"]: p["slot"] for p in parsed["params"]}, OWN_HOST_COEFFICIENT_SLOTS)
                self.assertNotIn(3, [p["slot"] for p in parsed["params"]])


if __name__ == "__main__":
    unittest.main()
