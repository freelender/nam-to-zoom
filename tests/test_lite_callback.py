"""Replay Lite callback startup, all slots, guards and poisoned-history recovery."""
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from test_kernel_optimization import find_clang

ROOT = Path(__file__).resolve().parents[1]


class LiteCallbackTests(unittest.TestCase):
    def test_full_callback_32_bit_host_abi(self):
        self.replay("lite", 1871)

    def test_compact_ten_slots_32_bit_host_abi(self):
        self.replay("compact", 659)

    def test_owned_seven_control_callback_32_bit_host_abi(self):
        self.replay("lite", 1871, own_host=True)

    def test_compact_effect_seven_control_callback_32_bit_host_abi(self):
        self.replay("lite", 1871, own_host=True, compact_effect=True)

    def test_full_tuner_preserves_model_when_host_overwrites_legacy_slot(self):
        self.replay("lite", 1871, own_host=True, tuner=True)

    def test_compact_tuner_preserves_model_when_host_overwrites_legacy_slot(self):
        self.replay("lite", 1871, own_host=True, compact_effect=True, tuner=True)

    def test_full_gain_changes_input_drive_and_preserves_dry_mix(self):
        self.replay("lite",1871,own_host=True,gain_probe=True)

    def test_compact_gain_changes_input_drive_and_preserves_dry_mix(self):
        self.replay("lite",1871,own_host=True,compact_effect=True,gain_probe=True)

    def replay(self, profile, words_per_model, own_host=False, compact_effect=False, tuner=False, gain_probe=False):
        if sys.platform == "darwin":
            self.skipTest("macOS has no 32-bit host ABI; callback replay runs on Windows CI")
        clang = find_clang()
        if not clang:
            self.skipTest("host Clang unavailable")
        model_count = (5 if own_host else 3) if profile == "lite" else 10
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in ("compact_pair.c", "compact_pair.h", "compact_kernel.h"):
                shutil.copyfile(ROOT / f"dsp/nam_a2_{profile}" / name, root / name)
            shutil.copyfile(ROOT / ("dsp/nam_a2_own_host/host.c" if own_host else "dsp/nam_a2_bank_zd2/bank_effect.c"), root / "bank_effect.c")
            if own_host:
                shutil.copyfile(ROOT / "dsp/nam_a2_own_host" / ("compact_block.c" if compact_effect else "block4.c"), root / "compact_pair.c")
                shutil.copyfile(ROOT / "dsp/nam_a2_own_host/block4.h", root / "compact_pair.h")
                for name in ("compact_runtime.h", "compact_filters.h"):
                    shutil.copyfile(ROOT / "dsp/nam_a2_own_host" / name, root / name)
            header = "#define SH_STATE_BYTES 128\n#define SH_FRAMES 16\n#define SH_CH_B_OFFSET 16\n"
            header += "#define SH_CTX_EFF 1\n#define SH_STATE_GUARD_WORD 32\n#define SH_STATE_GUARD 0x57464731u\n"
            header += "#define SH_COEFF_BYPASS 0\n#define SH_AUDIO_FN lite_audio\n"
            header += "".join(f"#define SH_PARAM_{name} {index}\n" for name, index in
                              zip(("MODEL", "BASS", "MID", "TREBLE", "VOL", "INPUT", "MIX"),
                                  (3, 5, 6, 7, 8, 9, 10)))
            if own_host:
                header = header.replace("#define SH_PARAM_MODEL 3", "#define SH_PARAM_MODEL 12")
                header = header.replace("#define SH_PARAM_MID 6", "#define SH_PARAM_MIDDLE 6")
                header += "#define SH_PARAM_GAIN 13\n"
                header = header.replace("#define SH_PARAM_VOL 8", "#define SH_PARAM_VOLUME 8")
                header = header.replace("#define SH_PARAM_INPUT 9\n", "").replace("#define SH_PARAM_MIX 10", "#define SH_PARAM_MIX 9")
            (root / "sh_params.h").write_text(header)
            (root / "bank_config.h").write_text(f"#define BANK_MODEL_COUNT {model_count}u\n#define BANK_SELECTOR_MAX {model_count - 1}u\n#define BANK_WORDS_PER_MODEL {words_per_model}u\n")
            weights = [0.] * (words_per_model * model_count)
            for i in range(model_count):
                weights[i * words_per_model + words_per_model - 2] = .1 * (i + 1)
                weights[i * words_per_model + words_per_model - 1] = 1.
                if gain_probe:
                    base=i*words_per_model
                    weights[base]=1.
                    offset=base+3
                    for kernel in [6]*14+[15,15]+[6]*7:
                        weights[offset+9*kernel+3]=1.
                        offset+=9*kernel+18
                    weights[offset+15]=.5*(i+1)/23
                    weights[base+words_per_model-2]=0.
            words = struct.unpack(f"<{len(weights)}I", struct.pack(f"<{len(weights)}f", *weights))
            code = '#include "bank_effect.c"\n#include <math.h>\n#include <stdio.h>\n'
            code += f'const uint32_t N2ZBankWeights[{len(weights)}] = {{' + ','.join(f'0x{x:08x}u' for x in words) + '};\n'
            code += r'''
static uint32_t storage[34];
static float arena[HISTORY_FLOATS + 2], bus[32], coeff[16];
static uint32_t descriptor[3];
static void *instance[4], *ctx[48];
static int guards(void) {
    return storage[32] == SH_STATE_GUARD && storage[33] == 0x12345678u
        && arena[0] == 12345.0f && arena[HISTORY_FLOATS + 1] == 12345.0f;
}
static int run(int blocks, float expected) {
    int block, i;
    for (block = 0; block < blocks; ++block) {
        for (i = 0; i < 32; ++i) bus[i] = .2f;
        lite_audio(instance, ctx);
        if (!guards()) return 1;
    }
    for (i = 0; i < 32; ++i)
        if (!isfinite(bus[i]) || fabsf(bus[i] - expected) > 1e-6f) {
            fprintf(stderr,"sample %d: got %.9g expected %.9g\n",i,bus[i],expected); return 2;
        }
    return 0;
}
int main(void) {
    unsigned i;
    EffectState *state = (EffectState *)storage;
    storage[32] = SH_STATE_GUARD; storage[33] = 0x12345678u;
    for (i = 0; i < HISTORY_FLOATS + 2; ++i) arena[i] = 12345.0f;
    descriptor[0] = (uint32_t)(uintptr_t)(arena + 1);
    descriptor[1] = (uint32_t)(uintptr_t)(arena + 1 + HISTORY_FLOATS);
    descriptor[2] = HISTORY_BYTES;
    instance[1] = coeff; instance[2] = storage; instance[3] = descriptor;
    ctx[SH_CTX_EFF] = bus;
    coeff[0] = coeff[10] = 1.0f;
    coeff[5] = coeff[6] = coeff[7] = coeff[8] = coeff[9] = .5f;
    for (i = 0; i < BANK_MODEL_COUNT; ++i) {
        coeff[SH_PARAM_MODEL] = i / (float)BANK_SELECTOR_MAX;
        if (run(500, .1f * (i + 1)) || state->active_model != i
            || state->warm_count != BANK_WARMUP_FRAMES) return 10 + i;
    }
    descriptor[2] = HISTORY_BYTES - 4;
    if (run(1, 0.0f)) return 20;
    descriptor[2] = HISTORY_BYTES;
    storage[32] = 0;
    lite_audio(instance, ctx);
    for (i = 0; i < 32; ++i) if (bus[i] != 0.0f) return 21;
    storage[32] = SH_STATE_GUARD;
    coeff[10] = NAN;
    if (run(1, 0.0f)) return 22;
    coeff[10] = 1.0f;
    for (i = 1; i <= HISTORY_FLOATS; ++i) arena[i] = NAN;
    if (run(1, 0.0f) || state->initialized != RECOVERING) return 23;
    if (run(500, .1f * BANK_MODEL_COUNT)) return 24;
    coeff[10] = 0.0f;
    if (run(1, .2f)) return 25;
    puts("Callback: all supported slots, receptive-field warmup, descriptor/state guards, recovery and dry mix PASS");
    return 0;
}
'''
            source = root / "probe.c"
            if own_host:
                code = code.replace("coeff[10]", "coeff[9]")
                code = code.replace("    for (i = 0; i < BANK_MODEL_COUNT; ++i)", "    coeff[13]=.5f;\n    for (i = 0; i < BANK_MODEL_COUNT; ++i)")
                code = code.replace("coeff[8] = coeff[9] = .5f", "coeff[8] = .5f")
                code = code.replace('    puts("Callback:', '''    coeff[9] = 1.0f; coeff[8] = 0.0f;
    if (run(500, 0.0f)) return 26;
    coeff[8] = 1.0f;
    if (run(500, .2f * BANK_MODEL_COUNT)) return 27;
    coeff[8] = .5f; coeff[5] = 0.0f;
    if (run(500, 0.0f)) return 28;
    coeff[5] = 1.0f;
    if (run(500, .2f * BANK_MODEL_COUNT)) return 29;
    coeff[5] = .5f; coeff[9] = .5f;
    if (run(500, .1f + .05f * BANK_MODEL_COUNT)) return 30;
    puts("Callback:''')
            if compact_effect:
                code = "#define N2Z_COMPACT_EFFECT 1\n" + code.replace("run(500", "run(700")
            if gain_probe:
                code=code.replace('    puts("Callback:', '''    coeff[9]=1.0f; coeff[13]=0.0f;
    if(run(700,0.0f)) return 50;
    coeff[13]=.5f;
    if(run(700,.1f * BANK_MODEL_COUNT)) return 51;
    coeff[13]=1.0f;
    if(run(700,.2f * BANK_MODEL_COUNT)) return 52;
    coeff[9]=0.0f;
    if(run(700,.2f)) return 53;
    coeff[9]=1.0f; coeff[13]=NAN;
    if(run(1,0.0f)) return 54;
    coeff[13]=.5f;
    if(run(700,.1f * BANK_MODEL_COUNT)) return 55;
    puts("Callback:''')
            if tuner:
                code = code.replace('static int guards(void)', 'static int tuner_writer;\nstatic int guards(void)')
                code = code.replace('        lite_audio(instance, ctx);', '        if(tuner_writer) coeff[3]=0.0f;\n        lite_audio(instance, ctx);')
                code = code.replace('    descriptor[2] = HISTORY_BYTES - 4;', r'''    /* Hardware recording: scratch/arena survive, coefficient 3 resets,
       and the audio callback has no host parameter getter. */
    ctx[40]=0; instance[0]=0; tuner_writer=1;
    if(run(700,.1f * BANK_MODEL_COUNT) || state->active_model!=BANK_MODEL_COUNT-1u) return 40;
    for(i=0;i<BANK_MODEL_COUNT;++i) {
        /* Real knob edit materializes Model through its dedicated handler. */
        coeff[SH_PARAM_MODEL]=i/(float)BANK_SELECTOR_MAX;
        if(run(700,.1f*(i+1)) || state->active_model!=i) return 41;
        /* Repeated tuner visits must not change weights or force re-warmup. */
        if(run(700,.1f*(i+1)) || state->active_model!=i || state->warm_count!=BANK_WARMUP_FRAMES) return 42;
    }
    /* Scratch loss must still initialize from the dedicated model coefficient. */
    for(i=0;i<SH_STATE_BYTES/4;++i)storage[i]=0;
    if(run(700,.1f * BANK_MODEL_COUNT) || state->active_model!=BANK_MODEL_COUNT-1u) return 43;
    tuner_writer=0;
    coeff[SH_PARAM_MODEL]=0.0f;
    if(run(700,.1f) || state->active_model!=0u) return 44;
    coeff[SH_PARAM_MODEL]=1.0f;
    if(run(700,.1f * BANK_MODEL_COUNT) || state->active_model!=BANK_MODEL_COUNT-1u) return 45;
    descriptor[2] = HISTORY_BYTES - 4;''')
            source.write_text(code)
            exe = root / "probe.exe"
            compiled = subprocess.run([clang, "-m32", "-O3", "-ffp-contract=off", "-Wno-unknown-pragmas",
                                       str(source), "-o", str(exe)], capture_output=True, text=True)
            self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)
            result = subprocess.run([str(exe)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            print(result.stdout.strip())
