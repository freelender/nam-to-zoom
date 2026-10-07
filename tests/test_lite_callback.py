"""Replay Lite callback startup, all slots, guards and poisoned-history recovery."""
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest
from test_kernel_optimization import find_clang

ROOT = Path(__file__).resolve().parents[1]


class LiteCallbackTests(unittest.TestCase):
    def test_full_callback_32_bit_host_abi(self):
        self.replay("lite", 1871)

    def test_compact_ten_slots_32_bit_host_abi(self):
        self.replay("compact", 659)

    def replay(self, profile, words_per_model):
        clang = find_clang()
        if not clang:
            self.skipTest("host Clang unavailable")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in ("compact_pair.c", "compact_pair.h", "compact_kernel.h"):
                shutil.copyfile(ROOT / f"dsp/nam_a2_{profile}" / name, root / name)
            shutil.copyfile(ROOT / "dsp/nam_a2_bank_zd2/bank_effect.c", root / "bank_effect.c")
            header = "#define SH_STATE_BYTES 128\n#define SH_FRAMES 16\n#define SH_CH_B_OFFSET 16\n"
            header += "#define SH_CTX_EFF 1\n#define SH_STATE_GUARD_WORD 32\n#define SH_STATE_GUARD 0x57464731u\n"
            header += "#define SH_COEFF_BYPASS 0\n#define SH_AUDIO_FN lite_audio\n"
            header += "".join(f"#define SH_PARAM_{name} {index}\n" for name, index in
                              zip(("MODEL", "BASS", "MID", "TREBLE", "VOL", "INPUT", "MIX"),
                                  (3, 5, 6, 7, 8, 9, 10)))
            (root / "sh_params.h").write_text(header)
            (root / "bank_config.h").write_text(f"#define BANK_MODEL_COUNT 10u\n#define BANK_SELECTOR_MAX 9u\n#define BANK_WORDS_PER_MODEL {words_per_model}u\n")
            weights = [0.] * (words_per_model * 10)
            for i in range(10):
                weights[i * words_per_model + words_per_model - 2] = .1 * (i + 1)
                weights[i * words_per_model + words_per_model - 1] = 1.
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
        if (!isfinite(bus[i]) || fabsf(bus[i] - expected) > 1e-6f) return 2;
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
    for (i = 0; i < 10; ++i) {
        coeff[3] = i / 9.0f;
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
    if (run(500, 1.0f)) return 24;
    coeff[10] = 0.0f;
    if (run(1, .2f)) return 25;
    puts("Callback: ten slots, receptive-field warmup, descriptor/state guards, recovery and dry mix PASS");
    return 0;
}
'''
            source = root / "probe.c"
            source.write_text(code)
            exe = root / "probe.exe"
            compiled = subprocess.run([clang, "-m32", "-O3", "-ffp-contract=off", "-Wno-unknown-pragmas",
                                       str(source), "-o", str(exe)], capture_output=True, text=True)
            self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)
            result = subprocess.run([str(exe)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            print(result.stdout.strip())
