"""Compact timing against an independent scalar network, including ring wraps."""
import ctypes
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import numpy as np
from test_kernel_optimization import find_clang

ROOT=Path(__file__).resolve().parents[1]
P=ctypes.POINTER(ctypes.c_float)
class State(ctypes.Structure):
    _fields_=[('positions',ctypes.c_uint16*24)]

class CompactDelayTests(unittest.TestCase):
    def test_rounded_delays_match_scalar_reference(self):
        clang=find_clang()
        if not clang:self.skipTest('Clang unavailable')
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)
            shutil.copy2(ROOT/'dsp/nam_a2_own_host/block4.h',folder/'compact_pair.h')
            (folder/'probe.c').write_text('#define N2Z_COMPACT_EFFECT 1\n#include "'+(ROOT/'dsp/nam_a2_own_host/compact_block.c').as_posix()+'"\n#include "'+(ROOT/'tests/fixtures/compact_delay_reference.c').as_posix()+'"\n')
            dll=folder/('probe.dll' if os.name=='nt' else 'probe.so')
            cmd=[clang,'-O3','-ffp-contract=off','-shared','-I',str(folder),str(folder/'probe.c'),'-o',str(dll)]
            if os.name=='nt':cmd+=['-Wl,/export:compact_process_block','-Wl,/export:compact_reference']
            subprocess.run(cmd,check=True,capture_output=True)
            lib=ctypes.CDLL(str(dll))
            for symbol in ('compact_process_block','compact_reference'):
                fn=getattr(lib,symbol);fn.argtypes=[P,P,ctypes.POINTER(State),P,P];fn.restype=None
            try:
                rng=np.random.default_rng(493)
                x=rng.uniform(-.5,.5,24000).astype('float32');x[:256]=0;x[256]=.9
                for seed in range(3):
                    w=rng.uniform(-.08,.08,1871).astype('float32');w[-1]=1
                    outputs=[]
                    for symbol in ('compact_process_block','compact_reference'):
                        history=np.zeros(20120,dtype='float32');history[0]=history[-1]=12345
                        state=State();y=np.empty_like(x)
                        for i in range(0,len(x),12):
                            getattr(lib,symbol)(w.ctypes.data_as(P),history[1:-1].ctypes.data_as(P),ctypes.byref(state),x[i:i+12].ctypes.data_as(P),y[i:i+12].ctypes.data_as(P))
                        self.assertEqual((history[0],history[-1]),(12345,12345))
                        self.assertTrue(np.isfinite(y).all());outputs.append(y)
                    np.testing.assert_allclose(outputs[0],outputs[1],rtol=1e-5,atol=2e-6)
            finally:
                if os.name=='nt':
                    import _ctypes
                    _ctypes.FreeLibrary(lib._handle)

    def test_compact_template_binds_corrected_source_only(self):
        import sys
        sys.path.insert(0,str(ROOT/'tools'))
        from nam2zoom.template import sources
        compact=sources('lite',True,True);full=sources('lite',True)
        self.assertIn('dsp/nam_a2_own_host/compact_block.c',compact)
        self.assertNotIn('dsp/nam_a2_own_host/block4.c',compact)
        self.assertIn('dsp/nam_a2_own_host/block4.c',full)
        self.assertNotIn('dsp/nam_a2_own_host/compact_block.c',full)

if __name__=='__main__':unittest.main()
