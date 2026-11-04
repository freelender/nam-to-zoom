"""Build private tuner/model-state probes offline, without any pedal access."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from nam2zoom.bank import load_models,prepare_bank,STOMPHACKS,TOOLCHAIN
from nam2zoom.platforms import venv_python
from nam2zoom.template import sources
from nam2zoom.artwork import stamp_compact_artwork

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('models',type=Path,nargs='+')
    parser.add_argument('--label',dest='labels',action='append')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args(); output=args.output.resolve();output.mkdir(parents=True,exist_ok=False)
    models=load_models(args.models,args.labels,profile='lite')
    tag=hashlib.sha256(b''.join(row[2] for row in models))
    for path in (*sources('lite',True),'dsp/nam_a2_bank_zd2/model_probe.c'):tag.update((ROOT/path).read_bytes())
    model_tag=tag.hexdigest()[:8]
    report={'format':'nam2zoom.model-probe.v1','model_tag':model_tag,'installed':False,
            'private_model_weights':True,'labels':[row[1] for row in models],'variants':{}}
    env=os.environ.copy();env['ZOOM_TI_CGT']=str(TOOLCHAIN)
    for name,compact in [('full',False),('compact',True)]:
        manifest_path=prepare_bank(models,output/name,profile='lite',own_host=True,compact_effect=compact)
        directory=manifest_path.parent
        shutil.copyfile(ROOT/'dsp/nam_a2_bank_zd2/model_probe.c',directory/'model_probe.c')
        (directory/'model_probe_config.h').write_text(f'#define MODEL_PROBE_TAG 0x{model_tag}u\n',encoding='ascii')
        manifest=json.loads(manifest_path.read_text())
        manifest.update(kernel='model_probe.c',state_bytes=188,
                        description='Temporary tuner model-state probe. Output is report tones. Do not save this patch.')
        manifest_path.write_text(json.dumps(manifest,indent=2)+'\n',encoding='ascii')
        subprocess.run([str(venv_python(STOMPHACKS/'.venv')),str(STOMPHACKS/'tools/zd2_make_effect.py'),str(manifest_path)],cwd=STOMPHACKS,env=env,check=True)
        effect=directory/'build/N2ZBANK.ZD2'
        if compact:stamp_compact_artwork(effect)
        report['variants'][name]={ext.lower()+'_sha256':hashlib.sha256(effect.with_suffix('.'+ext).read_bytes()).hexdigest() for ext in ('ZD2','ZIC')}
    (output/'probe-kit.json').write_text(json.dumps(report,indent=2)+'\n')
    for name in ('decode_model_probe.py','decode_lite_timing.py'):shutil.copyfile(ROOT/'tools'/name,output/name)
    for name in ('Run.ps1','Run.cmd','README.md'):shutil.copyfile(ROOT/'release/model-probe'/name,output/name)
    print(f'Private model probe ready: {output}')

if __name__=='__main__':main()
