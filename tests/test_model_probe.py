"""Probe wire format, multi-report decoding and bounded native transport state."""
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib
import numpy as np
import soundfile as sf

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from decode_model_probe import decode,valid_packets,SYNC
from test_kernel_optimization import find_clang

class ModelProbeTests(unittest.TestCase):
    def test_crc_partial_packet_resynchronization(self):
        words=[SYNC,1]+[0]*16
        words.append(zlib.crc32(struct.pack('<18I',*words)))
        bits=''.join(f'{word:032b}' for word in words)
        self.assertEqual(valid_packets(bits[93:]+'xx'+bits),[tuple(words)])
        self.assertEqual(valid_packets(bits[:100]+'x'+bits[101:]),[])

    def test_native_cycles_scratch_reset_guards_and_changing_snapshots(self):
        if sys.platform=='darwin':self.skipTest('32-bit ABI replay requires Windows/Linux')
        clang=find_clang()
        if not clang:self.skipTest('Clang unavailable')
        with tempfile.TemporaryDirectory() as temporary:
            folder=Path(temporary)
            shutil.copyfile(ROOT/'dsp/nam_a2_bank_zd2/model_probe.c',folder/'model_probe.c')
            (folder/'sh_params.h').write_text('''#pragma once
#define SH_STATE_BYTES 188
#define SH_STATE_GUARD_WORD 47
#define SH_STATE_GUARD 0x57464731u
#define SH_CTX_EFF 1
#define SH_FRAMES 16
#define SH_CH_B_OFFSET 16
#define SH_PARAM_MODEL 3
#define SH_PARAM_MIX 9
#define SH_COEFF_BYPASS 0
''')
            (folder/'model_probe_config.h').write_text('#define MODEL_PROBE_TAG 0x12345678u\n')
            # Isolate the transport from inference: emulate a full 96-byte host
            # state prefix, including the largest Compact layout, and host values
            # changing across tuner-like scratch resets. Production TI builds
            # separately compile the unchanged real inference callback.
            (folder/'bank_effect.c').write_text('''#include <stdint.h>
#define INITIALIZED 0x50314c34u
#define CTX_GET_PARAM 40
#define UI_PARAM_MODEL 2
typedef int (*GetParamFn)(void*,int);
typedef struct { uint32_t active_model,initialized,clear_count,warm_count,pad[20]; } EffectState;
void SH_AUDIO_FN(void **instance,void **ctx) {
    EffectState *state=instance[2]; float *coeff=instance[1];
    int model=((GetParamFn)ctx[40])(instance[0],2);
    state->active_model=(uint32_t)model; state->initialized=INITIALIZED;
    coeff[3]=model*.5f; state->clear_count=20000; state->warm_count=5000;
}
''')
            (folder/'probe.c').write_text('''#include "model_probe.c"
#include <stdio.h>
#include <string.h>
static uint32_t state[49];
static float coeff[16],bus[32],arena[4];
static uint32_t desc[3];
static int host_model=2;
static int get_param(void *object,int index) { return index==2?*(int*)object:1; }
int main(int argc,char **argv) {
    void *instance[4]={&host_model,coeff,state,desc}, *ctx[48]={0};
    unsigned block,i; FILE *output;
    if(argc!=2)return 1;
    output=fopen(argv[1],"wb");if(!output)return 2;
    state[47]=SH_STATE_GUARD;state[48]=0x12345678u;
    desc[0]=(uint32_t)(uintptr_t)arena;desc[2]=sizeof(arena);desc[1]=desc[0]+desc[2];
    coeff[0]=coeff[9]=1.0f;
    ctx[1]=bus;ctx[40]=(void*)get_param;
    for(block=0;block<300000;++block) {
        if(block==100000) { memset(state,0,188);host_model=0;coeff[3]=0; }
        if(block==200000) { host_model=2;coeff[3]=1.0f; }
        for(i=0;i<32;++i)bus[i]=.2f;
        Fx_SFX_N2ZBank(instance,ctx);
        if(state[47]!=SH_STATE_GUARD || state[48]!=0x12345678u)return 3;
        if(fwrite(bus,sizeof(float),32,output)!=32)return 4;
    }
    fclose(output);return 0;
}
''')
            executable=folder/'probe.exe'
            build=subprocess.run([clang,'-m32','-O3','-Wno-unknown-pragmas',str(folder/'probe.c'),'-o',str(executable)],capture_output=True,text=True)
            self.assertEqual(build.returncode,0,build.stdout+build.stderr)
            raw=folder/'audio.f32'
            run=subprocess.run([str(executable),str(raw)],capture_output=True,text=True)
            self.assertEqual(run.returncode,0,run.stdout+run.stderr)
            data=np.fromfile(raw,dtype='<f4').reshape(-1,32)
            left=data[:,:16].reshape(-1);right=data[:,16:].reshape(-1)
            np.testing.assert_array_equal(left,right)
            wav=folder/'probe.wav';sf.write(wav,np.c_[left,right],44100,subtype='FLOAT')
            result=decode(wav);reports=result['reports']
            values=[report['ui_model'] for report in reports]
            self.assertGreaterEqual(len(values),6)
            self.assertEqual(values[0],2);self.assertEqual(values[-1],2);self.assertIn(0,values)
            self.assertFalse(result['clipped'])
            self.assertTrue(all(report['model_tag']==0x12345678 for report in reports))
            self.assertTrue(all(report['active_after']==report['ui_model'] for report in reports))
            self.assertTrue(all(report['coefficient_after']==report['ui_model']*.5 for report in reports))
            self.assertGreaterEqual(sum(report['sequence']==1 for report in reports),2)

if __name__=='__main__':unittest.main()
