"""Full callback replay; host ABI validation, not C674x execution or pedal timing."""

import os
from pathlib import Path
import random
import shutil
import struct
import subprocess
import tempfile
import unittest

from test_kernel_optimization import find_clang

ROOT = Path(__file__).resolve().parents[1]


def derive_callback(source):
    """Derive the expected pair callback from the scalar fixture."""
    def replace(old, new):
        nonlocal source
        if source.count(old) != 1:
            raise ValueError("release callback anchor changed: " + old[:80])
        source = source.replace(old, new)

    replace('#pragma FUNC_ALWAYS_INLINE(compact_process)\n#include "compact_kernel.c"',
            '#include "compact_pair.h"\n'
            '#pragma FUNC_ALWAYS_INLINE(compact_process_pair)\n#include "compact_pair.c"')
    replace("#define HISTORY_FLOATS COMPACT_MIRROR_HISTORY_FLOATS",
            "#define HISTORY_FLOATS PAIR_HISTORY_FLOATS\n"
            "typedef char even_callback[(SH_FRAMES % 2u == 0u) ? 1 : -1];\n"
            "#define BANK_WARMUP_FRAMES ((COMPACT_RECEPTIVE_FIELD + 1u) & ~1u)")
    replace("#define INITIALIZED 0x41324231u\n#define RECOVERING 0x52454331u",
            "#ifdef N2Z_LITE_KERNEL\n#define INITIALIZED 0x50324C31u\n#define RECOVERING 0x52454C31u\n"
            "#else\n#define INITIALIZED 0x50324231u\n#define RECOVERING 0x52454331u\n#endif")
    source = source.replace("state->warm_count > COMPACT_RECEPTIVE_FIELD", "state->warm_count > BANK_WARMUP_FRAMES")
    source = source.replace("state->warm_count < COMPACT_RECEPTIVE_FIELD", "state->warm_count < BANK_WARMUP_FRAMES")
    source = source.replace("remaining = COMPACT_RECEPTIVE_FIELD -", "remaining = BANK_WARMUP_FRAMES -")
    replace("    CompactState model;", "    CompactPairState model;")
    replace("        for (i = 0; i < count; ++i)\n"
            "            (void)compact_process(weights, history, &state->model, 0.0f);",
            "        for (i = 0; i < count; i += 2u) {\n"
            "            float ignored0, ignored1;\n"
            "            compact_process_pair(weights, history, &state->model, 0.0f, 0.0f,\n"
            "                                 &ignored0, &ignored1);\n        }")
    start = source.index("    for (i = 0; i < SH_FRAMES; ++i) {\n        float dry_l")
    end = source.index("\n}\n\nvoid SH_AUDIO_FN", start)
    source = source[:start] + '''    for (i = 0; i < SH_FRAMES; i += 2u) {
        float dry_l[2], dry_r[2], wet[2];
        unsigned int frame;
        for (frame = 0; frame < 2u; ++frame) {
            dry_l[frame] = bus[i + frame];
            dry_r[frame] = bus[i + frame + SH_CH_B_OFFSET];
            if (!(dry_l[frame] > -8.0f && dry_l[frame] < 8.0f)) dry_l[frame] = 0.0f;
            if (!(dry_r[frame] > -8.0f && dry_r[frame] < 8.0f)) dry_r[frame] = 0.0f;
        }
        compact_process_pair(weights, history, &state->model,
                             (dry_l[0] + dry_r[0]) * input,
                             (dry_l[1] + dry_r[1]) * input,
                             &wet[0], &wet[1]);
        if (!(wet[0] > -8.0f && wet[0] < 8.0f) ||
            !(wet[1] > -8.0f && wet[1] < 8.0f)) {
            /* Poisoned recurrent history cannot recover without a full clear. */
            state->initialized = RECOVERING;
            silence(bus);
            return;
        }
        for (frame = 0; frame < 2u; ++frame) {
            float out_l, out_r, modeled = wet[frame];
            modeled = tone_process(state, modeled, bass, mid, treble) * (2.0f * volume);
            out_l = blend_output(dry_l[frame], modeled, wet_gain);
            out_r = blend_output(dry_r[frame], modeled, wet_gain);
            bus[i + frame] = out_l > -8.0f && out_l < 8.0f ? out_l : 0.0f;
            bus[i + frame + SH_CH_B_OFFSET] = out_r > -8.0f && out_r < 8.0f ? out_r : 0.0f;
        }
    }''' + source[end:]
    if "compact_process(" in source:
        raise ValueError("scalar inference unexpectedly remains in pair callback")
    return source


class PairBankTests(unittest.TestCase):
    def test_callback_replay(self):
        clang = find_clang()
        if not clang:
            self.skipTest("host Clang unavailable")
        bank = Path(os.environ.get("NAM2ZOOM_PAIR_BANK", ROOT / ".tooling/pair-bank-test-input"))
        source = (ROOT / "tests/fixtures/bank_effect_scalar.c").read_text(encoding="utf-8")
        production = (ROOT / "dsp/nam_a2_bank_zd2/bank_effect.c").read_text(encoding="utf-8")
        self.assertEqual(production, derive_callback(source))
        header = "#ifndef SH_PARAMS_H\n#define SH_PARAMS_H\n"
        header += "#define SH_STATE_BYTES 128\n#define SH_FRAMES 16\n#define SH_CH_B_OFFSET 16\n"
        header += "#define SH_CTX_EFF 1\n#define SH_STATE_GUARD_WORD 32\n#define SH_STATE_GUARD 0x57464731u\n"
        header += "#define SH_COEFF_BYPASS 0\n#define SH_AUDIO_FN unused_audio\n"
        header += "".join(f"#define SH_PARAM_{name} {index}\n" for name, index in
                          zip(("MODEL", "BASS", "MID", "TREBLE", "VOL", "INPUT", "MIX"),
                              (3, 5, 6, 7, 8, 9, 10)))
        header += "#endif\n"
        if (bank / "build/sh_params.h").is_file():
            header = (bank / "build/sh_params.h").read_text(encoding="utf-8")
        if (bank / "weights.f32").is_file():
            self.assertEqual((bank / "bank_effect.c").read_text(encoding="utf-8"),
                             derive_callback(source))
            for name in ("compact_pair.c",):
                self.assertEqual((bank / name).read_bytes(),
                                 (ROOT / "dsp/nam_a2_compact" / name).read_bytes())
            payload = (bank / "weights.f32").read_bytes()
        else:
            rng = random.Random(74)
            weights = [rng.uniform(-0.08, 0.08) for _ in range(659 * 5)]
            for index in range(5):
                weights[index * 659 + 658] = 1.0
            payload = struct.pack("<3295f", *weights)
        self.assertEqual(len(payload), 3295 * 4)
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            objects = []
            for variant in ("scalar", "pair"):
                path = folder / variant
                path.mkdir()
                (path / "sh_params.h").write_text(header, encoding="ascii")
                (path / "bank_config.h").write_text(
                    "#define BANK_MODEL_COUNT 5u\n#define BANK_SELECTOR_MAX 4u\n"
                    "#define BANK_WORDS_PER_MODEL 659u\n#define N2Z_OPTIMIZED_KERNEL 1\n", encoding="ascii")
                for name in ("compact_kernel.c", "compact_kernel.h"):
                    shutil.copyfile(ROOT / "dsp/nam_a2_compact" / name, path / name)
                for name in ("compact_pair.c", "compact_pair.h"):
                    shutil.copyfile(ROOT / "dsp/nam_a2_compact" / name, path / name)
                callback = source if variant == "scalar" else production
                (path / "callback.c").write_text(callback, encoding="ascii")
                words = ",".join(f"0x{word:08x}u" for word in struct.unpack("<3295I", payload))
                wrapper = path / "wrapper.c"
                wrapper.write_text(f'''
#include "sh_params.h"
#undef SH_AUDIO_FN
#define SH_AUDIO_FN {variant}_audio
#define N2ZBankWeights {variant}_weights
#include "callback.c"
#include <string.h>
const uint32_t N2ZBankWeights[3295] = {{{words}}};
static uint32_t storage[SH_STATE_BYTES / 4 + 2];
static float arena[HISTORY_FLOATS + 2];
static int ui_model_override = -1;
static int get_param(void *object, int index) {{
    if (index == 0) return 1;
    if (index != 2) return -1;
    return ui_model_override >= 0 ? ui_model_override : *(int *)object;
}}
void {variant}_reset(void) {{
    unsigned i;
    memset(storage, 0, sizeof(storage));
    storage[SH_STATE_GUARD_WORD] = SH_STATE_GUARD;
    storage[SH_STATE_GUARD_WORD + 1] = 0x12345678u;
    for (i = 0; i < HISTORY_FLOATS + 2; ++i) arena[i] = 12345.0f;
    ui_model_override = -1;
}}
void {variant}_run(float *bus, float *coeff, int invalid_descriptor) {{
    uint32_t descriptor[3] = {{(uint32_t)(uintptr_t)(arena + 1),
        (uint32_t)(uintptr_t)(arena + 1 + HISTORY_FLOATS), HISTORY_BYTES}};
    int ui_model = (int)(coeff[SH_PARAM_MODEL] * BANK_SELECTOR_MAX + 0.5f);
    void *instance[4] = {{&ui_model, coeff, storage, descriptor}};
    void *ctx[41] = {{0}};
    ctx[SH_CTX_EFF] = bus;
    ctx[CTX_GET_PARAM] = (void *)get_param;
    if (invalid_descriptor) descriptor[2] = 0;
    effect_process(instance, ctx);
}}
void {variant}_set_ui_model(int model) {{ ui_model_override = model; }}
void {variant}_poison_history(void) {{
    unsigned i;
    for (i = 1; i <= HISTORY_FLOATS; ++i) arena[i] = 0.0f / 0.0f;
}}
int {variant}_ready(void) {{
    EffectState *s = (EffectState *)storage;
    return s->initialized == INITIALIZED && s->clear_count == HISTORY_FLOATS &&
           s->warm_count == COMPACT_RECEPTIVE_FIELD;
}}
unsigned {variant}_active_model(void) {{ return ((EffectState *)storage)->active_model; }}
int {variant}_guards(void) {{
    return storage[SH_STATE_GUARD_WORD] == SH_STATE_GUARD &&
           storage[SH_STATE_GUARD_WORD + 1] == 0x12345678u &&
           arena[0] == 12345.0f && arena[HISTORY_FLOATS + 1] == 12345.0f;
}}
''', encoding="ascii")
                obj = path / "wrapper.obj"
                subprocess.run([clang, "-m32", "-O3", "-ffp-contract=off",
                                "-Wno-unknown-pragmas", "-c", str(wrapper), "-o", str(obj)],
                               check=True, capture_output=True)
                objects.append(str(obj))
            exe = folder / "probe.exe"
            link = subprocess.run([clang, "-m32", "-O3", "-ffp-contract=off", *objects,
                                   str(ROOT / "tests/pair_bank_probe.c"), "-o", str(exe)],
                                  capture_output=True, text=True)
            self.assertEqual(link.returncode, 0, link.stdout + link.stderr)
            result = subprocess.run([str(exe)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("bit-exact", result.stdout)
            print(result.stdout.strip(), flush=True)

    def test_generator_refuses_changed_release_anchors(self):
        source = (ROOT / "tests/fixtures/bank_effect_scalar.c").read_text(encoding="utf-8")
        with self.assertRaises(ValueError):
            derive_callback(source.replace("#define INITIALIZED 0x41324231u", "#define INITIALIZED 0u"))


if __name__ == "__main__":
    unittest.main()
