"""Three independent bank identities, named artwork and targeted removal."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "tools"), str(ROOT / "tests"), str(ROOT / ".tooling/stomphacks/tools-pedal")]
from nam2zoom.identity import SLOTS, identify, validate_name
from nam2zoom.own_host import build_ready_effect
from nam2zoom import deploy
from nam2zoom.artwork import named_icon
from offline_effect_audit import audit_bytes
from zd2 import parse_zd2_bytes
from test_waveformer_effect import stable_lite
import offline_effect_audit
import pedal_diy


class EffectSlotTests(unittest.TestCase):
    def build(self, root, slot, compact=False, name=None, artwork=True):
        model = root / "ready.nam"
        model.write_text(json.dumps(stable_lite()), encoding="utf-8")
        return build_ready_effect([model] * 5, [f"MODEL{i}" for i in range(1,6)],
                                  root / f"slot-{slot.number}-{int(compact)}", effect_slot=slot.number,
                                  effect_name=name or f"My Amp {slot.number}", compact_effect=compact,
                                  name_artwork=artwork)

    def test_all_slots_both_modes_keep_dsp_and_have_unique_id_filename_name(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for compact in (False, True):
                dsp = None
                for slot in SLOTS:
                    effect = self.build(root, slot, compact)
                    s, z = identify(effect)
                    self.assertEqual(s, slot)
                    self.assertEqual(z.name, f"My Amp {slot.number}")
                    self.assertEqual(z.dspload, 190 if compact else 260)
                    self.assertEqual(audit_bytes(effect.read_bytes(), effect.with_suffix('.ZIC').read_bytes(), {}), [])
                    self.assertTrue(pedal_diy.classify(str(effect))[0])
                    if dsp is not None:
                        self.assertEqual(z.data_chunk.data, dsp)
                    dsp = z.data_chunk.data
                    base = (ROOT/'release/precompiled'/('own-lite-compact' if compact else 'own-lite')/'N2ZBANK.ZIC').read_bytes()
                    self.assertEqual(effect.with_suffix('.ZIC').read_bytes(), named_icon(base,z.name))

    def test_invalid_names_and_optional_artwork(self):
        for name in ("", "NINECHARS", "elevenchars", "Écho", " leading", "trailing ", "amp/drive", "\n"):
            with self.assertRaises(ValueError): validate_name(name)
        self.assertEqual(validate_name("AMP-TEST"), "AMP-TEST")
        with tempfile.TemporaryDirectory() as temporary:
            effect = self.build(Path(temporary),SLOTS[1],name="AMP-TEST",artwork=False)
            self.assertEqual(effect.with_suffix('.ZIC').read_bytes(),(ROOT/'release/precompiled/own-lite/N2ZBANK.ZIC').read_bytes())
            wrong = effect.with_name(SLOTS[2].filename)
            wrong.write_bytes(effect.read_bytes())
            with self.assertRaises(ValueError): identify(wrong)

    def test_bold_titles_fit_both_frames_with_matching_proportions(self):
        import struct
        for compact in (False, True):
            base=(ROOT/'release/precompiled'/('own-lite-compact' if compact else 'own-lite')/'N2ZBANK.ZIC').read_bytes()
            icon=named_icon(base,'WWWWWWWW')
            offset=32; spans=[]
            for width,height in [struct.unpack_from('<HH',icon,i) for i in (8,12)]:
                top,bottom=height*38//97,height*67//97
                xs=[];ys=[]
                for y in range(height):
                    for x in range(width):
                        index=offset+(y//8)*width+x;mask=1<<(y%8)
                        if 10<=x<width-10 and top<=y<bottom:
                            if icon[index]&mask:xs.append(x);ys.append(y)
                        else:self.assertEqual(icon[index]&mask,base[index]&mask)
                self.assertGreaterEqual(min(xs),13 if width==97 else 17)
                self.assertGreaterEqual(width-1-max(xs),13 if width==97 else 17)
                self.assertEqual(max(ys)-min(ys)+1,11 if width==97 else 15)
                spans.append((max(xs)-min(xs)+1)/width)
                offset+=width*((height+7)//8)
            self.assertLess(abs(spans[0]-spans[1]),.01)

    def test_old_longer_names_remain_identifiable_and_removable(self):
        import struct
        from zd2 import compute_checksum
        with tempfile.TemporaryDirectory() as temporary:
            effect=self.build(Path(temporary),SLOTS[1])
            raw=bytearray(effect.read_bytes());raw[100:111]=b'NAM CLEAN\0\0'
            struct.pack_into('<I',raw,8,compute_checksum(raw));effect.write_bytes(raw)
            slot,z=identify(effect)
            self.assertEqual(z.name,'NAM CLEAN')
            self.assertTrue(deploy._valid_existing(z,slot))
            with self.assertRaises(ValueError):validate_name(z.name)

    def test_backup_preflight_accepts_three_slots_and_checks_name_collisions(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary); effects=[self.build(root,s) for s in SLOTS]
            backup=root/'backup';files=backup/'files';files.mkdir(parents=True)
            for effect in effects:
                for p in (effect,effect.with_suffix('.ZIC')):(files/p.name).write_bytes(p.read_bytes())
            (files/'FLST_SEQ.ZT2').write_bytes(b'list')
            (backup/'manifest.json').write_text(json.dumps({'identity':{'family_code':1,'model_number':1,'version':'1.40'}}))
            entries=[(4,s.filename,'0.01',s.effect_id,1) for s in SLOTS]
            flst=Mock();flst.validate_flst.return_value=(True,[],entries);flst.parse_entries.return_value=entries
            installed={s.filename:s.effect_id for s in SLOTS}
            names={f'my amp {s.number}' for s in SLOTS}
            with patch.object(deploy,'_profile',return_value=SimpleNamespace(name='pedal',firmware='1.40',patch_count=0)), \
                 patch.object(deploy,'require_stock_patch'), patch.object(deploy,'_flst',return_value=flst), \
                 patch.object(offline_effect_audit,'load_backup',side_effect=lambda _: (dict(installed),set(names),files/'FLST_SEQ.ZT2')):
                for slot,effect in zip(SLOTS,effects):
                    self.assertTrue(deploy.plan_backup(effect,effect.with_suffix('.ZIC'),backup,root/'current',slot.number))
                from nam2zoom.identity import personalize
                effect=personalize(effects[1],2,'My Amp 1')
                with self.assertRaisesRegex(deploy.DeployError,'collides'):
                    deploy.plan_backup(effect,effect.with_suffix('.ZIC'),backup,root/'current',2)

    def test_uninstall_touches_only_selected_slot(self):
        for slot in SLOTS:
            with self.subTest(slot=slot.number), tempfile.TemporaryDirectory() as temporary:
                session=Path(temporary)/'session'
                active={s.filename:b'bank'+bytes([s.number]) for s in SLOTS}
                active.update({s.icon:b'icon'+bytes([s.number]) for s in SLOTS})
                original=dict(active)
                def backup(*args):
                    files=session/'backup/files';files.mkdir(parents=True)
                    for name,data in active.items():(files/name).write_bytes(data)
                    (files/'FLST_SEQ.ZT2').write_bytes(b'before')
                    self.assertEqual(args[-1],slot.number)
                    return True
                def tool(name,*args,**kwargs):
                    if name=='safe_connect.py':return 'Autosave OFF - CONFIRMED; CRC ok'
                    if name=='pedal_diy.py':
                        self.assertEqual(Path(args[1]).name,slot.filename)
                        if '--dry-run' not in args:
                            active.pop(slot.filename);active.pop(slot.icon)
                    if name=='readback.py':
                        self.assertIn(args[0],(slot.filename,slot.icon))
                        self.assertNotIn(args[0],active)
                    return ''
                flst=Mock();flst.expect_single_remove.return_value=(True,[])
                with patch.object(deploy,'_tool',side_effect=tool),patch.object(deploy,'_run'), \
                     patch.object(deploy,'require_stock_patch'),patch.object(deploy,'plan_backup',side_effect=backup), \
                     patch.object(deploy,'_read_effect_list',return_value=b'after'),patch.object(deploy,'_flst',return_value=flst):
                    self.assertEqual(deploy.uninstall_bank(session,slot_number=slot.number),'uninstalled')
                self.assertEqual(active,{n:d for n,d in original.items() if n not in (slot.filename,slot.icon)})
                flst.expect_single_remove.assert_called_once_with(b'before',b'after',slot.filename)

    def test_other_slot_patch_is_allowed_but_target_is_blocked(self):
        for slot in SLOTS:
            allowed={s.effect_id for s in SLOTS if s!=slot}
            with patch.object(deploy,'patch_ids',return_value=allowed):
                deploy.require_stock_patch(Path('saved'),allowed)
            with patch.object(deploy,'patch_ids',return_value={slot.effect_id}):
                with self.assertRaises(deploy.DeployError):deploy.require_stock_patch(Path('saved'),allowed)

    def test_replace_only_selected_slot_in_both_backup_modes(self):
        for full_backup in (False, True):
            for slot in SLOTS:
                with self.subTest(slot=slot.number,full_backup=full_backup), tempfile.TemporaryDirectory() as temporary:
                    root=Path(temporary);effect=self.build(root,slot);session=root/'session'
                    active={s.filename:b'old bank'+bytes([s.number]) for s in SLOTS}
                    active.update({s.icon:b'old icon'+bytes([s.number]) for s in SLOTS})
                    before=dict(active)
                    def preflight(*args):
                        self.assertEqual(args[-1],slot.number)
                        prior=session/('backup/files' if full_backup else 'live-check');prior.mkdir(parents=True)
                        for name,data in active.items():(prior/name).write_bytes(data)
                        (prior/'FLST_SEQ.ZT2').write_bytes(b'before')
                        return True if full_backup else (True,prior)
                    def tool(name,*args,**kwargs):
                        if name=='safe_connect.py':return 'Autosave OFF - CONFIRMED; CRC ok'
                        if name=='pedal_diy.py':
                            self.assertEqual(Path(args[1]).name,slot.filename)
                            if '--dry-run' not in args:
                                if args[0]=='uninstall':
                                    active.pop(slot.filename);active.pop(slot.icon)
                                else:
                                    p=Path(args[1]);active[slot.filename]=p.read_bytes();active[slot.icon]=p.with_suffix('.ZIC').read_bytes()
                        if name=='readback.py':
                            self.assertIn(args[0],(slot.filename,slot.icon))
                            if kwargs.get('expected')==1:self.assertNotIn(args[0],active)
                            else:
                                p=Path(args[1]);p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(active[args[0]])
                        return ''
                    flst=Mock();flst.expect_single_remove.return_value=(True,[]);flst.expect_single_add.return_value=(True,[])
                    with patch.object(deploy,'_tool',side_effect=tool),patch.object(deploy,'_run'), \
                         patch.object(deploy,'require_stock_patch'),patch.object(deploy,'plan_backup',side_effect=preflight), \
                         patch.object(deploy,'plan_live',side_effect=preflight),patch.object(deploy,'_read_effect_list',return_value=b'after'), \
                         patch.object(deploy,'_flst',return_value=flst):
                        self.assertEqual(deploy.install_bank(effect,session,deploy.digest(effect),deploy.digest(effect.with_suffix('.ZIC')),full_backup=full_backup),'installed')
                    self.assertEqual(active[slot.filename],effect.read_bytes())
                    for name,data in before.items():
                        if name not in (slot.filename,slot.icon):self.assertEqual(active[name],data)

    def test_live_preflight_allows_coexisting_slots_and_rejects_duplicate_name(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);effects=[self.build(root,s) for s in SLOTS]
            catalog={p.name:p.read_bytes() for e in effects for p in (e,e.with_suffix('.ZIC'))}
            catalog['FLST_SEQ.ZT2']=b'list'
            entries=[(4,s.filename,'0.01',s.effect_id,1) for s in SLOTS]
            flst=Mock();flst.validate_flst.return_value=(True,[],entries)
            def run(*args,**kwargs):
                command=args[0]
                if 'identify' in command:return 'Family: 0x0001\nModel: 0x0001\nVersion: 1.40\n'
                if 'patch-info' in command:return 'Patches: 0\n'
                if 'list-files' in command:return '\n'.join(catalog)
                raise AssertionError(command)
            def download(name,destination):destination.write_bytes(catalog[name])
            with patch.object(deploy,'_profile',return_value=SimpleNamespace(name='pedal',firmware='1.40',patch_count=0)), \
                 patch.object(deploy,'require_stock_patch'),patch.object(deploy,'_flst',return_value=flst), \
                 patch.object(deploy,'_run',side_effect=run),patch.object(deploy,'_download',side_effect=download):
                for slot,effect in zip(SLOTS,effects):
                    session=root/f'live{slot.number}';session.mkdir()
                    self.assertTrue(deploy.plan_live(effect,effect.with_suffix('.ZIC'),session,root/'current',slot.number)[0])
                from nam2zoom.identity import personalize
                effect=personalize(effects[1],2,'My Amp 1');session=root/'duplicate';session.mkdir()
                with self.assertRaisesRegex(deploy.DeployError,'collides'):
                    deploy.plan_live(effect,effect.with_suffix('.ZIC'),session,root/'current',2)
