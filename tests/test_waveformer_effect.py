"""Real offline full-Lite packing and host-integrity regressions; no MIDI."""
import json
import os
from pathlib import Path
import shutil
import struct
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from nam2zoom.waveformer import build_ready_effect, validate_ready_effect, require_host_device
from nam2zoom.devices import SUPPORTED_DEVICES
from zd2 import parse_zd2_bytes, compute_checksum
from elf32 import parse_elf32
from test_lite_profiles import lite_model


def stable_lite(gain=.2):
    model = lite_model()
    sub = model['config']['submodels'][0]['model']
    weights = [0.] * 1871
    weights[3 + 54 + 3] = 1.0  # First layer's input mix, channel 0.
    weights[1871 - 2 - 48 + 15] = gain  # Latest head tap of channel 0.
    weights[-1] = 1.0
    sub['weights'] = weights
    return model


@unittest.skipUnless(shutil.which('node') or (ROOT / 'runtime/node').exists(), 'Node builder runtime required')
class WaveformerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.work = tempfile.TemporaryDirectory(prefix='nam2zoom optimized effect ')
        cls.root = Path(cls.work.name)
        cls.paths = []
        for i in range(3):
            path = cls.root / f'model-{i}.nam'
            path.write_text(json.dumps(stable_lite(.2 + .1 * i)))
            cls.paths.append(path)
        cls.effect = build_ready_effect(cls.paths, ['LAST','FIRST','MID'], cls.root / 'built')

    @classmethod
    def tearDownClass(cls):
        cls.work.cleanup()

    def test_full_model_sound_gate_order_identity_and_budget(self):
        zd2 = parse_zd2_bytes(self.effect.read_bytes())
        self.assertEqual(zd2.effect_id, 0x04001787)
        self.assertEqual(zd2.name, 'N2Z Bank')
        self.assertEqual(zd2.dspload, 134.5)
        self.assertTrue(zd2.checksum_valid)
        report = json.loads(self.effect.with_name('engine-report.json').read_text())
        self.assertEqual(report['labels'], ['LAST','FIRST','MID'])
        self.assertEqual(report['sampleRate'], 44100)
        self.assertIsNone(report['measuredDspPercent'])
        for capture in report['captures']:
            self.assertEqual(len(capture['analysis']['exponents']), 23)
            for signal in ('pluck','probe'):
                gate = capture['analysis']['gate'][signal]
                self.assertLessEqual(gate['esr'], .01)
                self.assertEqual(gate['xclip'], 0)
                self.assertEqual(gate['accOverflow'], 0)
        validate_ready_effect(self.effect)
        self.assertTrue(self.effect.with_name('Waveformer-LICENSE.txt').is_file())

    def test_original_artwork_is_preserved(self):
        original = (ROOT / 'release/precompiled/lite/N2ZBANK.ZIC').read_bytes()
        self.assertEqual(self.effect.with_suffix('.ZIC').read_bytes(), original)
        zd2 = parse_zd2_bytes(self.effect.read_bytes())
        icon = next(chunk for chunk in zd2.chunks if chunk.tag == 'ICON')
        width, height = struct.unpack_from('<HH', original, 8)
        frame_bytes = width * ((height + 7) // 8)
        self.assertEqual(icon.data, original[32:32 + frame_bytes])

    def test_instructions_and_reservation_cannot_be_changed(self):
        original = self.effect.read_bytes()
        zd2 = parse_zd2_bytes(original)
        info = next(c for c in zd2.chunks if c.tag == 'INFO')
        elf = parse_elf32(zd2.data_chunk.data)
        code = next(section for section in elf.sections if section.name == '.text')
        for offset in (zd2.data_chunk.offset + 8 + code.offset, info.offset + 8 + info.length - 4):
            changed = bytearray(original)
            changed[offset] ^= 1
            struct.pack_into('<I', changed, 8, compute_checksum(changed))
            other = self.root / f'tamper-{offset}.ZD2'
            other.write_bytes(changed)
            other.with_suffix('.ZIC').write_bytes(self.effect.with_suffix('.ZIC').read_bytes())
            with self.assertRaises(Exception):
                validate_ready_effect(other)

    def test_rejects_48khz_and_wrong_shape_without_training(self):
        for name, model in [('48k', stable_lite()), ('shape', stable_lite())]:
            if name == '48k':
                model['sample_rate'] = 48000
            else:
                model['config']['submodels'][0]['model']['config']['layers'][0]['channels'] = 4
            path = self.root / (name + '.nam')
            path.write_text(json.dumps(model))
            with self.assertRaises(ValueError):
                build_ready_effect([path], ['AMP'], self.root / name)
            self.assertFalse((self.root / name / 'build/N2ZBANK.ZD2').exists())

    def test_supported_host_devices(self):
        for profile in SUPPORTED_DEVICES[:2]:
            require_host_device(self.effect, profile)
        with self.assertRaisesRegex(ValueError, 'only'):
            require_host_device(self.effect, SUPPORTED_DEVICES[2])

