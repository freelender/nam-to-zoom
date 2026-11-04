"""Compare exported 44.1 kHz A2 Lite NAMs against the current Compact runtime.

Developer-only offline tool: requires Clang, NAM Core renderer and audio deps.
No retraining, effect installation or pedal access is performed.
"""
import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import numpy as np
import soundfile as sf

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'tests'),str(ROOT/'tools')]
from test_kernel_optimization import find_clang
from benchmark_adaptation import scores
from nam2zoom.bank import load_models
P=ctypes.POINTER(ctypes.c_float)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('models',nargs='+',type=Path)
    parser.add_argument('--di',required=True,type=Path)
    parser.add_argument('--renderer',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--start',type=float,default=4)
    parser.add_argument('--seconds',type=float,default=10)
    args=parser.parse_args()
    if args.seconds<=1 or args.start<0:parser.error('Use more than one second of audio and a nonnegative start.')
    out=args.output.resolve();out.mkdir(parents=True,exist_ok=False)
    work=out/'source';work.mkdir()
    for a,b in [('compact_block.c','compact_pair.c'),('block4.h','compact_pair.h'),('compact_runtime.h','compact_runtime.h'),('compact_filters.h','compact_filters.h')]:
        shutil.copy2(ROOT/'dsp/nam_a2_own_host'/a,work/b)
    source=work/'compare.c'
    source.write_text('''#define N2Z_COMPACT_EFFECT 1
#include <stdlib.h>
#include <string.h>
#include "compact_pair.c"
#include "compact_runtime.h"
int render(const float*w,const float*x,float*y,unsigned n) {
 CompactPairState net; CompactRateState rate; memset(&net,0,sizeof(net));memset(&rate,0,sizeof(rate));
 float*h=(float*)calloc(PAIR_HISTORY_FLOATS+N2Z_RATE_FLOATS,sizeof(float));if(!h)return 1;
 for(unsigned i=0;i<n;i+=16){float a[12],b[12];compact_downsample(&rate,h+PAIR_HISTORY_FLOATS,x+i,a);compact_process_block(w,h,&net,a,b);compact_upsample(&rate,h+PAIR_HISTORY_FLOATS+130,b,y+i);}
 free(h);return 0;
}
''')
    clang=find_clang()
    if not clang:raise RuntimeError('Clang is required for this developer comparison.')
    dll=work/('compare.dll' if os.name=='nt' else 'compare.so')
    cmd=[clang,'-O3','-ffp-contract=off','-shared',str(source),'-o',str(dll)]
    if os.name=='nt':cmd+=['-Wl,/export:render']
    subprocess.run(cmd,check=True,capture_output=True)
    lib=ctypes.CDLL(str(dll));lib.render.argtypes=[P,P,P,ctypes.c_uint];lib.render.restype=ctypes.c_int
    try:
        di,rate=sf.read(args.di,dtype='float32',always_2d=True)
        if rate!=44100:raise ValueError('Comparison DI must be 44.1 kHz; no implicit conversion.')
        di=np.mean(di,axis=1,dtype=np.float32)
        start=int(args.start*rate);count=int(args.seconds*rate)//16*16
        x=np.ascontiguousarray(di[start:start+count])
        if len(x)!=count:raise ValueError('DI does not contain the requested comparison range.')
        if not np.isfinite(x).all() or np.max(np.abs(x))>=1:raise ValueError('DI must be finite and below full scale.')
        sf.write(out/'input-with-warmup.wav',x,rate,subtype='FLOAT')
        xx=np.pad(x,(0,256));report={'format':'nam2zoom.original-lite-vs-compact.v1','sampleRate':rate,'internalCompactRate':33075,
          'warmupDiscardSamples':44100,'compactDelayCompensationSamples':64,
          'reference':'Independent NAM Core renderer of the same exported A2 Lite file; no EQ, no additional drive.',
          'diSha256':hashlib.sha256(args.di.read_bytes()).hexdigest(),'diStartSeconds':args.start,'diSeconds':count/rate,
          'compactSourceHashes':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in work.glob('*.c')},'models':[]}
        for number,model in enumerate(args.models,1):
            record=load_models([model],['AMP'],profile='lite')[0]
            w=np.frombuffer(record[2],dtype='float32').copy();y=np.empty_like(xx)
            if lib.render(w.ctypes.data_as(P),xx.ctypes.data_as(P),y.ctypes.data_as(P),len(xx)):raise MemoryError('Compact allocation failed.')
            folder=out/f'{number:02d}';folder.mkdir()
            subprocess.run([str(args.renderer.resolve()),str(model.resolve()),str(out/'input-with-warmup.wav'),str(folder/'original-with-warmup.wav')],check=True)
            original,actual_rate=sf.read(folder/'original-with-warmup.wav',dtype='float32');assert actual_rate==rate
            original=original[44100:];compact=y[64:64+len(x)][44100:]
            result={'model':model.name,'sha256':record[3],'folder':folder.name,**scores(compact,original)}
            rms_original=float(np.sqrt(np.mean(original.astype('float64')**2)));rms_compact=float(np.sqrt(np.mean(compact.astype('float64')**2)))
            matching_gain=rms_original/max(rms_compact,1e-20)
            result['compactRmsMatchGainDb']=float(20*np.log10(matching_gain))
            result['levelMatchedScores']=scores(compact*matching_gain,original)
            common=.8/max(float(np.max(np.abs(original))),float(np.max(np.abs(compact))),1e-20)
            sf.write(folder/'01-original-A2-Lite.wav',original*common,rate,subtype='PCM_24')
            sf.write(folder/'02-Compact.wav',compact*common,rate,subtype='PCM_24')
            silence=np.zeros(rate//2,dtype='float32');matched=compact*matching_gain
            ab=np.concatenate([original,silence,matched]);ab*=.8/max(float(np.max(np.abs(ab))),1e-20)
            sf.write(folder/'03-AB-original-then-Compact-level-matched.wav',ab,rate,subtype='PCM_24')
            result['audioCommonGain']=common;report['models'].append(result)
            print(model.name,'ESR',round(result['esr'],5),'correlation',round(result['correlation'],5),flush=True)
        (out/'results.json').write_text(json.dumps(report,indent=2)+'\n')
        rows=['| Folder | Model | ESR | Correlation | Spectral error |','| --- | --- | ---: | ---: | ---: |']
        rows += [f"| {r['folder']} | {r['model']} | {r['esr']:.4f} | {r['correlation']:.4f} | {r['spectral_error']:.4f} |" for r in report['models']]
        (out/'README.md').write_text('''# Original A2 Lite vs current Compact

This compares the SAME exported 44.1 kHz NAM weights, using the same local guitar DI. The original is rendered by the independent NAM Core executable; Compact uses the project's current C neural kernel and exact C resampling filters. It excludes pedal converters and common EQ/volume/mix processing. No retraining was performed.

Each numbered folder contains:
- `01-original-A2-Lite.wav`: reference output.
- `02-Compact.wav`: Compact output; the same gain is used for these two files, preserving their level difference.
- `03-AB-original-then-Compact-level-matched.wav`: original, half-second silence, then Compact. Compact is RMS-matched for listening; this is simple level matching, not perceptual LUFS matching.

The first second of each render is excluded for model warmup. Compact's known 64-sample FIR delay is removed. No additional model-dependent time alignment is fitted. Original-with-warmup files retain the renderer's unmodified floating-point output.

## Measurements

'''+ '\n'.join(rows)+'''

Lower ESR/spectral error and correlation closer to 1 indicate closer agreement. ESR is error energy divided by reference energy, not a percentage of perceived sound quality. Scores above use the original levels; separately level-matched scores are in results.json. Waveform scores are sensitive to phase, so use listening alongside them.

These clips sample three models and one guitar passage. They do not prove equivalence for every model or input. This is a software comparison, not a recording of the pedal. A hardware comparison should reamp the same DI through Full and Compact with identical settings, record both, and compensate measured converter/processing latency before scoring.
''',encoding='utf-8')
    finally:
        if os.name=='nt':
            import _ctypes
            _ctypes.FreeLibrary(lib._handle)

if __name__=='__main__':main()
