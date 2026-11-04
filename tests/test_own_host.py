"""Own-host controls, original artwork, lossless weights and code integrity."""
import hashlib
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from nam2zoom.own_host import build_ready_effect
from nam2zoom.bank import prepare_bank, load_models, OWN_HOST_COEFFICIENT_SLOTS
from nam2zoom.template import fill_template
from nam2zoom.artwork import compact_icon, stamp_compact_artwork
from elf32 import parse_elf32
from zd2 import parse_zd2_bytes
from test_waveformer_effect import stable_lite


class OwnHostTests(unittest.TestCase):
    def test_compact_uses_same_full_lite_weights_and_separate_templates(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary); path=root/'ready.nam'
            path.write_text(json.dumps(stable_lite()))
            before=path.read_bytes()
            effect=build_ready_effect([path],['AMP'],root/'compact',compact_effect=True)
            report=json.loads(effect.with_name('engine-report.json').read_text())
            self.assertEqual(report['effectMode'],'compact')
            self.assertEqual(report['modelProfile'],'lite')
            self.assertEqual(report['sampleRate'],44100)
            self.assertEqual(report['internalSampleRate'],33075)
            self.assertEqual(report['delayAdjustment'],'round-each-tap-3-over-4-precomputed-v1')
            self.assertEqual(report['declaredDspLoad'],190)
            self.assertEqual(report['addedLatencySamples'],64)
            self.assertEqual(report['modelCoefficientSlot'],12)
            self.assertEqual(parse_zd2_bytes(effect.read_bytes()).dspload,190)
            self.assertEqual(path.read_bytes(),before)
            weights=load_models([path],['AMP'],profile='lite')[0][2]
            index=json.loads((ROOT/'release/precompiled/own-lite-compact/index.json').read_text())
            offset=index['banks']['1']['weights_offset']
            self.assertEqual(effect.read_bytes()[offset:offset+len(weights)],weights)
            full_icon=(ROOT/'release/precompiled/own-lite/N2ZBANK.ZIC').read_bytes()
            self.assertEqual(effect.with_suffix('.ZIC').read_bytes(),compact_icon(full_icon))
            self.assertNotEqual(effect.with_suffix('.ZIC').read_bytes(),full_icon)
            stamped=effect.read_bytes()
            stamp_compact_artwork(effect)
            self.assertEqual(effect.read_bytes(),stamped)
            manifest=prepare_bank(load_models([path],['AMP'],profile='lite'),root/'wrong',profile='lite',own_host=True,compact_effect=True)
            with self.assertRaisesRegex(ValueError,'mode mismatch'):
                fill_template(ROOT/'release/precompiled/own-lite',manifest)

    def test_one_three_four_and_five_model_hosts_preserve_audio_data_artwork_and_text(self):
        with tempfile.TemporaryDirectory(prefix='nam2zoom own host ') as temporary:
            root = Path(temporary)
            path = root / 'ready.nam'
            model = stable_lite()
            path.write_text(json.dumps(model))
            expected_weights = struct.pack('<1871f', *model['config']['submodels'][0]['model']['weights'])
            templates = ROOT / 'release/precompiled/own-lite'
            index = json.loads((templates / 'index.json').read_text())
            for count in (1,3,4,5):
                labels = [f'AMP{i}' for i in range(count)]
                effect = build_ready_effect([path] * count, labels, root / str(count))
                manifest = json.loads((effect.parent.parent / 'manifest.json').read_text())
                report = json.loads(effect.with_name('engine-report.json').read_text())
                self.assertEqual([p['name'] for p in manifest['params']], ['Model','Gain','Volume','Mix','Bass','Middle','Treble'])
                self.assertEqual([p['default'] for p in manifest['params']], [0,50,50,100,50,50,50])
                self.assertEqual(report['controlPages'],[['Model','Gain','Volume','Mix'],['Bass','Middle','Treble']])
                self.assertEqual({p['name']:p['slot'] for p in manifest['params']},OWN_HOST_COEFFICIENT_SLOTS)
                self.assertEqual(index['coefficient_slots'],OWN_HOST_COEFFICIENT_SLOTS)
                self.assertEqual(report['arithmetic'], 'float32')
                self.assertFalse(report['weightsQuantized'])
                self.assertEqual(report['processingSamples'], 16)
                self.assertEqual(report['convolutionHistoryPasses'], 1)
                self.assertEqual(report['convolutionGroupSamples'], 2)
                self.assertEqual(report['historyBytes'], 81624)
                self.assertEqual(report['declaredDspLoad'],260)
                self.assertTrue(report['experimentalDspLoad'])
                self.assertIsNone(report['measuredDspPercent'])
                self.assertEqual(effect.with_suffix('.ZIC').read_bytes(), (ROOT / 'release/precompiled/lite/N2ZBANK.ZIC').read_bytes())
                data = effect.read_bytes()
                offset = index['banks'][str(count)]['weights_offset']
                self.assertEqual(data[offset:offset+len(expected_weights)*count], expected_weights*count)
                actual = parse_zd2_bytes(data)
                blank = parse_zd2_bytes((templates / f'bank-{count}.ZD2').read_bytes())
                def text(zd2):
                    elf = parse_elf32(zd2.data_chunk.data)
                    section = next(s for s in elf.sections if s.name == '.text')
                    return elf.data[section.offset:section.offset+section.size]
                self.assertEqual(text(actual),text(blank))
                self.assertEqual(actual.dspload,260)
                self.assertTrue(actual.checksum_valid)
                self.assertEqual(actual.effect_id,0x04001787)

    def test_five_distinct_models_in_both_modes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = []
            for i in range(5):
                model = stable_lite()
                model['config']['submodels'][0]['model']['weights'][-2] = .01 * (i + 1)
                path = root / f'amp{i}.nam'
                path.write_text(json.dumps(model))
                paths.append(path)
            labels = ['CLEAN1', 'CRUNCH', 'DRIVE1', 'LEAD01', 'AMP005']
            weights = b''.join(row[2] for row in load_models(paths, labels, profile='lite'))
            for compact in (False, True):
                mode = 'compact' if compact else 'full'
                templates = ROOT / 'release/precompiled' / ('own-lite-compact' if compact else 'own-lite')
                index = json.loads((templates / 'index.json').read_text())
                effect = build_ready_effect(paths, labels, root / mode, compact_effect=compact)
                data = effect.read_bytes()
                offset = index['banks']['5']['weights_offset']
                self.assertEqual(data[offset:offset + len(weights)], weights)
                labels_offset = index['banks']['5']['labels_offset']
                for i, label in enumerate(labels):
                    self.assertEqual(data[labels_offset + 8*i:labels_offset + 8*i + len(label) + 1], label.encode() + b'\0')
                self.assertTrue(parse_zd2_bytes(data).checksum_valid)
                report = json.loads(effect.with_name('engine-report.json').read_text())
                self.assertEqual(report['labels'], labels)
                self.assertEqual(report['modelCoefficientSlot'], 12)

    def test_wrong_rate_and_legacy_control_template_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); path = root / 'ready.nam'
            model = stable_lite(); model['sample_rate'] = 48000
            path.write_text(json.dumps(model))
            with self.assertRaises(ValueError):
                build_ready_effect([path], ['AMP'], root / 'bad-rate')
            model['sample_rate'] = 44100; path.write_text(json.dumps(model))
            manifest = prepare_bank(load_models([path],['AMP'],profile='lite'),root / 'prepared',profile='lite',own_host=True)
            with self.assertRaisesRegex(ValueError,'control layout'):
                fill_template(ROOT / 'release/precompiled/lite',manifest)
