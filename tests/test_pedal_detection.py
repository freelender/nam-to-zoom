"""Automatic detection must remain read-only and never guess between pedals."""
from pathlib import Path
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import msplus
from msplus_protocol import IDENTITY_REQUEST
from msplus_midi import MidiTimeout


class DetectionTests(unittest.TestCase):
    ports = (["ZOOM MS Plus Series In"], ["ZOOM MS Plus Series Out"])

    def test_absent_and_unrelated_ports_never_open_a_device(self):
        for ports in (([], []), (["Keyboard In"], ["Keyboard Out"])):
            with patch.object(msplus, "list_ports", return_value=ports), \
                    patch.object(msplus, "open_default_device") as opened:
                self.assertEqual(msplus.probe_device()["status"], "absent")
                opened.assert_not_called()

    def test_multiple_pedals_are_not_guessed(self):
        with patch.object(msplus, "list_ports", return_value=(self.ports[0] * 2, self.ports[1] * 2)), \
                patch.object(msplus, "open_default_device") as opened:
            self.assertEqual(msplus.probe_device()["status"], "ambiguous")
            opened.assert_not_called()

    def test_identity_only_and_handle_cleanup(self):
        class Transport:
            closed = False
            def __enter__(self): return self
            def __exit__(self, *args): self.closed = True
            def exchange(self, payload, accept):
                # Any PC-mode, backup, upload or patch request fails this test.
                self_test.assertEqual(payload, IDENTITY_REQUEST)
                response = bytes.fromhex("7e 6e 06 02 52 6e 00 23 00 31 2e 34 30")
                self_test.assertTrue(accept(response))
                return response
        self_test = self
        transport = Transport()
        with patch.object(msplus, "list_ports", return_value=self.ports), \
                patch.object(msplus, "open_default_device", return_value=transport):
            result = msplus.probe_device()
        self.assertEqual(result["status"], "connected")
        self.assertIn("MS-50G+", result["message"])
        self.assertTrue(transport.closed)

    def test_unknown_firmware_is_not_claimed_supported(self):
        class Transport:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def exchange(self, payload, accept):
                return bytes.fromhex("7e 6e 06 02 52 6e 00 23 00 39 2e 39 39")
        with patch.object(msplus, "list_ports", return_value=self.ports), \
                patch.object(msplus, "open_default_device", return_value=Transport()):
            self.assertEqual(msplus.probe_device()["status"], "unsupported")

    def test_disconnect_or_timeout_is_retryable(self):
        for error in (OSError("Disconnected"), MidiTimeout("No reply")):
            with patch.object(msplus, "list_ports", return_value=self.ports), \
                    patch.object(msplus, "open_default_device", side_effect=error):
                self.assertEqual(msplus.probe_device()["status"], "unavailable")

    def test_disconnect_after_connection_clears_status(self):
        with patch.object(msplus, "list_ports", side_effect=[self.ports, ([], [])]), \
                patch.object(msplus, "open_default_device"), \
                patch.object(msplus, "ReadOnlyMSPlus") as pedal:
            pedal.return_value.__enter__.return_value.identify.return_value = SimpleNamespace(
                family_code=0x6e, model_number=0x23, version="1.40")
            self.assertEqual(msplus.probe_device()["status"], "connected")
            self.assertEqual(msplus.probe_device()["status"], "absent")


if __name__ == "__main__":
    unittest.main()
