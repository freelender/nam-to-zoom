"""Build a private Full/Compact component profiling kit, offline (no USB writes)."""
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

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('model',type=Path)
    parser.add_argument('output',type=Path)
    args=parser.parse_args()
    output=args.output.resolve();output.mkdir(parents=True,exist_ok=False)
    models=load_models([args.model],['TIME'],profile='lite')
    tag=hashlib.sha256(models[0][2])
    for path in (*dict.fromkeys((*sources('lite',True), *sources('lite',True,True))),'dsp/nam_a2_bank_zd2/timing_effect.c'):
        tag.update((ROOT/path).read_bytes())
    tag.update(b'component-v2-full-compact-state128-arena128')
    comparison_tag=tag.hexdigest()[:8]
    report={'format':'nam2zoom.component-timing.v2','comparison_tag':comparison_tag,
            'weights_sha256':hashlib.sha256(models[0][2]).hexdigest(),
            'private_model_weights':True,'installed':False,'variants':{}}
    env=os.environ.copy();env['ZOOM_TI_CGT']=str(TOOLCHAIN)
    for variant,(name,compact) in enumerate((('original',False),('optimized',True))):
        manifest_path=prepare_bank(models,output/name,profile='lite',own_host=True,compact_effect=compact)
        directory=manifest_path.parent
        shutil.copyfile(ROOT/'dsp/nam_a2_bank_zd2/timing_effect.c',directory/'timing_effect.c')
        (directory/'timing_config.h').write_text(f'#define N2Z_TIMING_VARIANT {variant}u\n#define N2Z_TIMING_MODEL_TAG 0x{comparison_tag}u\n',encoding='ascii')
        manifest=json.loads(manifest_path.read_text())
        manifest.update(kernel='timing_effect.c',state_bytes=128,
                        description='Temporary component profiler. Never save a diagnostic patch.')
        manifest['params'][0]['values'][0]='CMP' if compact else 'FULL'
        manifest['kernel_cflags']=manifest.get('kernel_cflags',[])+[
            '--define=N2Z_PROFILE_COMPONENTS=1','--keep_asm',f'--asm_directory={directory/"build"}']
        manifest_path.write_text(json.dumps(manifest,indent=2)+'\n',encoding='ascii')
        subprocess.run([str(venv_python(STOMPHACKS/'.venv')),str(STOMPHACKS/'tools/zd2_make_effect.py'),str(manifest_path)],
                       cwd=STOMPHACKS,env=env,check=True)
        listing=(directory/'build/timing_effect.asm').read_text()
        counter=[line.split(';',1)[0] for line in listing.splitlines() if 'TSCL' in line.split(';',1)[0]]
        if not counter or any('TSCL,' not in line for line in counter):
            raise RuntimeError('unexpected or missing read-only TSCL instructions')
        report['variants'][name]={'mode':'compact' if compact else 'full',**{
            suffix.lower()+'_sha256':hashlib.sha256((directory/'build'/('N2ZBANK.'+suffix)).read_bytes()).hexdigest()
            for suffix in ('ZD2','ZIC')}}
    (output/'timing-kit.json').write_text(json.dumps(report,indent=2)+'\n')
    shutil.copyfile(ROOT/'tools/decode_lite_timing.py',output/'decode_lite_timing.py')
    script=(ROOT/'release/lite-timing/Run.ps1').read_text()
    script=script.replace('Install original','Install Full').replace('Install optimized','Install Compact')
    script=script.replace('Model ORIG/OPT','Model FULL/CMP').replace('Record 40 seconds','Record 60 seconds')
    script=script.replace('Lite timing:','Full/Compact component profiling:')
    (output/'Run.ps1').write_text(script)
    shutil.copyfile(ROOT/'release/component-timing/README.md',output/'README.md')
    print(f'Private component kit ready: {output}')

if __name__=='__main__':main()
