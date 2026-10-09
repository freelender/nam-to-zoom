"""Timing probe's state bounds, wire protocol and audio-interface decoder."""
import json
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from decode_lite_timing import decode, compare, packet_bytes, valid_packets
from test_kernel_optimization import find_clang


def report(variant=0, mean=40000):
    return [0x4E32545A, 1, variant, 0, 4096, 16, 100000, 99999, 100001,
            10, mean, mean - 100, mean + 100, 100000, 99999, 100001, 435, 0x12345678]


def audio(words, rate=44100):
    bits = "".join(f"{w:032b}" for w in struct.unpack("<19I", packet_bytes(words)))
    phase = np.arange(441)
    slots = []
    for bit in bits:
        p = (phase * (1 + int(bit))) % 64
        tone = (np.minimum(p, 64 - p) - 16) * .0025
        slots.append(np.r_[tone, np.zeros(441)])
    samples = np.r_[np.zeros(33075), np.concatenate(slots), np.zeros(33075)]
    if rate != 44100:
        samples = np.interp(np.arange(round(len(samples) * rate / 44100)) * 44100 / rate,
                            np.arange(len(samples)), samples)
    return samples


class TimingCodecTests(unittest.TestCase):
    def test_sample_rates_gain_noise_stereo_and_comparison(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            rng = np.random.default_rng(23)
            first = None
            for rate, variant, gain in ((44100, 0, .08), (48000, 1, 4.0)):
                tones = audio(report(variant, 40000 - variant * 4000), rate) * gain
                samples = np.r_[.5 * np.sin(np.arange(round(rate * 2.5)) * .1), tones, tones, tones]
                samples += rng.normal(0, .00001, len(samples))
                # Opposite stereo polarity must not cancel through averaging.
                path = directory / f"{rate}.wav"
                sf.write(path, np.c_[samples, -samples], rate, subtype="PCM_24")
                result = decode(path)
                self.assertEqual(result["variant"], variant)
                self.assertEqual(result["channels_decoded"], [1, 2])
                if first is None:
                    first = result
                else:
                    self.assertAlmostEqual(compare(first, result)["mean_change_percent"], -10)
                    result["model_tag"] += 1
                    with self.assertRaises(ValueError):
                        compare(first, result)

    def test_resync_partial_crc_conflict_and_silence(self):
        words = struct.unpack("<19I", packet_bytes(report()))
        bits = "".join(f"{w:032b}" for w in words)
        self.assertEqual(valid_packets(bits[91:] + "xxxx" + bits), [words])
        corrupted = bits[:200] + str(1 - int(bits[200])) + bits[201:]
        self.assertEqual(valid_packets(corrupted), [])
        self.assertEqual(valid_packets(bits[:200] + "x" + bits[201:]), [])
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "recording.wav"
            sf.write(path, np.r_[audio(report()), audio(report(1))], 44100)
            with self.assertRaisesRegex(ValueError, "conflicting"):
                decode(path)
            sf.write(path, np.zeros(44100), 44100)
            with self.assertRaisesRegex(ValueError, "no complete"):
                decode(path)

    def test_real_c_callback_report_guards_rollover_and_stopped_timer(self):
        if sys.platform == "darwin":
            self.skipTest("32-bit callback ABI exercised on Windows")
        clang = find_clang()
        if not clang:
            self.skipTest("host Clang unavailable")
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            for name in ("compact_pair.c", "compact_pair.h", "compact_kernel.h"):
                shutil.copyfile(ROOT / "dsp/nam_a2_lite" / name, directory / name)
            for name in ("bank_effect.c", "timing_effect.c"):
                shutil.copyfile(ROOT / "dsp/nam_a2_bank_zd2" / name, directory / name)
            header = "#ifndef SH_PARAMS_H\n#define SH_PARAMS_H\n#define SH_STATE_BYTES 184\n#define SH_FRAMES 16\n#define SH_CH_B_OFFSET 16\n"
            header += "#define SH_CTX_EFF 1\n#define SH_STATE_GUARD_WORD 46\n#define SH_STATE_GUARD 0x57464731u\n#define SH_COEFF_BYPASS 0\n#define SH_AUDIO_FN Fx_SFX_N2ZBank\n"
            header += "".join(f"#define SH_PARAM_{name} {index}\n" for name, index in
                              zip(("MODEL", "BASS", "MID", "TREBLE", "VOL", "INPUT", "MIX"), (3, 5, 6, 7, 8, 9, 10)))
            (directory / "sh_params.h").write_text(header + "#endif\n", encoding="ascii")
            (directory / "bank_config.h").write_text("#define BANK_MODEL_COUNT 1u\n#define BANK_SELECTOR_MAX 1u\n#define BANK_WORDS_PER_MODEL 1871u\n", encoding="ascii")
            (directory / "timing_config.h").write_text("#define N2Z_TIMING_VARIANT 1u\n#define N2Z_TIMING_MODEL_TAG 0x12345678u\n", encoding="ascii")
            source = r'''
#include <stdint.h>
#include <stdio.h>
#include <string.h>
static uint32_t clock_value = 0xfffffff0u;
static int stopped;
static uint32_t fake_clock(void) { if (!stopped) clock_value += 100u; return clock_value; }
#define N2Z_READ_CLOCK() fake_clock()
#include "timing_effect.c"
const uint32_t N2ZBankWeights[1871] = {0};
static uint64_t storage[25];
static float arena[HISTORY_FLOATS+2], bus[32], coeff[16];
static uint32_t descriptor[3];
static void *instance[4], *ctx[48];
static int run(unsigned count, FILE *output) {
    unsigned i;
    for (i=0;i<count;++i) {
        Fx_SFX_N2ZBank(instance,ctx);
        if (((uint32_t*)storage)[46] != SH_STATE_GUARD || ((uint32_t*)storage)[47] != 0x1234u ||
            arena[0] != 12345.f || arena[HISTORY_FLOATS+1] != 12345.f) return 1;
        if(output) fwrite(bus,sizeof(float),16,output);
    }
    return 0;
}
int main(int argc,char **argv) {
    TimingState *s=(TimingState*)storage;
    FILE *out;
    { TickSum sum={0xffffffffu,0u}; sum_add(&sum,2u);
      if(sum.lo!=1u||sum.hi!=1u||average_arrival(0x123456789abull)!=0x123456789abull/4095u) return 10; }
    arena[0]=arena[HISTORY_FLOATS+1]=12345.f;
    ((uint32_t*)storage)[46]=SH_STATE_GUARD; ((uint32_t*)storage)[47]=0x1234u;
    descriptor[0]=(uint32_t)(uintptr_t)(arena+1);
    descriptor[1]=(uint32_t)(uintptr_t)(arena+1+HISTORY_FLOATS);
    descriptor[2]=HISTORY_BYTES;
    instance[1]=coeff; instance[2]=storage; instance[3]=descriptor; ctx[SH_CTX_EFF]=bus;
    coeff[0]=coeff[10]=1.f;
    coeff[5]=coeff[6]=coeff[7]=coeff[8]=coeff[9]=.5f;
    if(run(7000,0) || s->meter.stage != 3 || s->meter.data.packet[3] != 0 ||
       s->meter.data.packet[10] != 100 || s->meter.data.packet[6] != 100 ||
       s->meter.data.packet[13] != 300) return 2;
    out=fopen(argv[1],"wb"); if(!out) return 3;
    if(run(80000,out)) return 4; fclose(out);
    /* Reporting must leave the network state parked. */
    { EffectState saved=s->net; if(run(100,0)||memcmp(&saved,&s->net,sizeof(saved))) return 5; }
    coeff[0]=0.f; if(run(1,0)||s->meter.magic) return 6;
    stopped=1; coeff[0]=1.f;
    if(run(2100,0)||s->meter.stage!=3||s->meter.data.packet[3]!=1) return 7;
    coeff[0]=0.f; run(1,0); stopped=0; coeff[0]=1.f; coeff[10]=.5f;
    if(run(2,0)||s->meter.data.packet[3]!=4) return 8;
    coeff[0]=0.f; run(1,0); coeff[0]=1.f; coeff[10]=1.f; descriptor[2]=4;
    if(run(4200,0)||s->meter.stage!=3||s->meter.data.packet[3]!=3) return 9;
    puts("Timing: bounded state/history, rollover, parked network, restart, stopped timer, controls, invalid descriptor PASS");
    return 0;
}
'''
            (directory / "probe.c").write_text(source, encoding="ascii")
            exe = directory / "probe.exe"
            compiled = subprocess.run([clang, "-m32", "-O3", "-ffp-contract=off", "-Wno-unknown-pragmas",
                                       str(directory / "probe.c"), "-o", str(exe)], capture_output=True, text=True)
            self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)
            raw = directory / "tones.f32"
            result = subprocess.run([str(exe), str(raw)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            wav = directory / "actual-c.wav"
            sf.write(wav, np.fromfile(raw, dtype="<f4"), 44100, subtype="FLOAT")
            decoded = decode(wav)
            self.assertEqual(decoded["callback_mean"], 100)
            self.assertEqual(decoded["loaded_period_mean"], 300)
            self.assertEqual(decoded["variant"], 1)


if __name__ == "__main__":
    unittest.main()
