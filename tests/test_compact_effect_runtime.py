"""Compact's causal FIR resampling against an independent SciPy reference."""
import _ctypes
import ctypes
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import numpy as np
from scipy.signal import upfirdn
from test_kernel_optimization import find_clang

ROOT=Path(__file__).resolve().parents[1]

class RateState(ctypes.Structure):
    _fields_=[('down',ctypes.c_uint),('up',ctypes.c_uint),('dry',ctypes.c_uint)]

class CompactRuntimeTests(unittest.TestCase):
    def test_streaming_reference_latency_rejection_and_guards(self):
        import sys
        sys.path.insert(0,str(ROOT/'tools'))
        from create_compact_filters import coefficients
        clang=find_clang()
        if not clang:self.skipTest('Clang unavailable')
        pointer=ctypes.POINTER(ctypes.c_float)
        with tempfile.TemporaryDirectory() as temporary:
            directory=Path(temporary)
            source=directory/'runtime.c'
            source.write_text('#include "compact_runtime.h"\n'
                'void down(CompactRateState*s,float*h,const float*x,float*y){compact_downsample(s,h,x,y);}\n'
                'void up(CompactRateState*s,float*h,const float*x,float*y){compact_upsample(s,h,x,y);}\n'
                'void dry(CompactRateState*s,float*h,float*l,float*r){compact_delay_dry(s,h,l,r);}\n')
            dll=directory/('runtime.dll' if os.name=='nt' else 'runtime.so')
            cmd=[clang,'-O3','-ffp-contract=off','-shared','-I',str(ROOT/'dsp/nam_a2_own_host'),str(source),'-o',str(dll)]
            if os.name=='nt':cmd += ['-Wl,/export:down','-Wl,/export:up','-Wl,/export:dry']
            subprocess.run(cmd,check=True,capture_output=True)
            library=ctypes.CDLL(str(dll))
            for name in ('down','up','dry'):
                function=getattr(library,name);function.argtypes=[ctypes.POINTER(RateState),pointer,pointer,pointer];function.restype=None
            try:
                rng=np.random.default_rng(551)
                samples=(rng.normal(0,.05,8192)+.2*np.sin(np.arange(8192)*.03)).astype('float32')
                def run(samples):
                    state=RateState(); histories=[]; pointers=[]
                    for count in (130,98,128):
                        h=(ctypes.c_float*(count+2))();h[0]=h[-1]=12345;histories.append(h)
                        pointers.append(ctypes.cast(ctypes.byref(h,4),pointer))
                    result=[];dry=[]
                    for i in range(0,len(samples),16):
                        x=(ctypes.c_float*16)(*samples[i:i+16]);lower=(ctypes.c_float*12)();y=(ctypes.c_float*16)()
                        library.down(ctypes.byref(state),pointers[0],x,lower)
                        library.up(ctypes.byref(state),pointers[1],lower,y)
                        right=(ctypes.c_float*16)(*samples[i:i+16])
                        library.dry(ctypes.byref(state),pointers[2],x,right)
                        result.extend(y);dry.extend(x)
                    for h in histories:self.assertEqual((h[0],h[-1]),(12345,12345))
                    np.testing.assert_array_equal(dry,np.r_[np.zeros(64,dtype='float32'),samples[:-64]])
                    return np.array(result)
                actual=run(samples);np.testing.assert_array_equal(actual,run(samples))
                hd,hu=coefficients()
                reference=upfirdn(hu,upfirdn(hd,samples,up=3,down=4)[:len(samples)*3//4],up=4,down=3)[:len(samples)]
                self.assertLess(np.max(np.abs(actual-reference)),1e-6)
                impulse=np.zeros(1024,dtype='float32');impulse[0]=1
                self.assertEqual(int(np.argmax(np.abs(run(impulse)))),64)
                self.assertLess(np.max(np.abs(run(np.ones(1024,dtype='float32'))[256:]-1)),2e-6)
                high=np.sin(np.arange(8192)*2*np.pi*21000/44100).astype('float32')
                self.assertLess(np.sqrt(np.mean(run(high)[512:]**2)),.003)
            finally:
                del function
                if os.name=='nt':_ctypes.FreeLibrary(library._handle)
