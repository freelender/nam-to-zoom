"""Catch mixed source encodings that turn UI symbols into mojibake."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class UiEncodingTests(unittest.TestCase):
    def test_app_sources_are_utf8_without_corrupted_symbols(self):
        corrupt = ("\u00e2\u20ac", "\u00e2\u2020", "\u00ef\u00bc", "\ufffd")
        for folder in ("nam2zoom-avalonia", "nam2zoom-core"):
            for path in (ROOT / "apps" / folder).glob("*.cs"):
                with self.subTest(path=path.name):
                    text = path.read_text(encoding="utf-8-sig")
                    self.assertFalse(any(sequence in text for sequence in corrupt))
