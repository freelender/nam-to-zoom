import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from nam2zoom import platforms, adapt
from msplus_midi import choose_ports, MidiUnavailable, ReadOnlyMSPlus
from msplus_protocol import IDENTITY_REQUEST


class PlatformTests(unittest.TestCase):
    def test_target_paths(self):
        with patch.object(sys, "platform", "darwin"), patch.dict(os.environ, {}, clear=True), \
                patch.object(Path, "home", return_value=Path("/mock/home")):
            self.assertEqual(platforms.executable("core_render"), "core_render")
            self.assertEqual(platforms.venv_python(Path("venv")), Path("venv/bin/python3"))
            self.assertEqual(platforms.data_root(), Path.home() / "Library/Application Support/nam2zoom")
        with patch.object(sys, "platform", "win32"):
            self.assertEqual(platforms.executable("core_render"), "core_render.exe")
            self.assertEqual(platforms.venv_python(Path("venv")), Path("venv/Scripts/python.exe"))

    def test_macos_never_selects_mps_implicitly(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(sys, "platform", "darwin"):
            work = Path(temporary)
            _, _, learning = adapt.prepare_configs(work / "dry.wav", work / "wet.wav", work, 100)
            self.assertEqual(json.loads(learning.read_text())["trainer"]["accelerator"], "cpu")

    def test_mock_ports_and_identity_require_no_midi_hardware(self):
        ports = choose_ports(["ZOOM MS Plus Series In"], ["ZOOM MS Plus Series Out"])
        self.assertTrue(ports.input_name.endswith("In"))
        with self.assertRaises(MidiUnavailable):
            choose_ports(["Other"], ["Other"])
        class Transport:
            def exchange(self, payload, accept):
                self.request = payload
                response = bytes.fromhex("7e 6e 06 02 52 6e 00 23 00 31 2e 34 30")
                assert accept(response)
                return response
        transport = Transport()
        with ReadOnlyMSPlus(transport) as pedal:
            identity = pedal.identify()
        self.assertEqual(transport.request, IDENTITY_REQUEST)
        self.assertEqual(identity.model_number, 0x23)
        self.assertEqual(identity.version, "1.40")
