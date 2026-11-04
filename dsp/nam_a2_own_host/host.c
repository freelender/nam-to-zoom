/* nam2zoom-owned full A2 Lite float host: Model, Gain, Volume, Mix; Bass, Middle, Treble. */
#define SH_PARAM_VOL SH_PARAM_VOLUME
#define SH_PARAM_MID SH_PARAM_MIDDLE
#include <stdint.h>
#include "sh_params.h"
#include "bank_config.h"

#define N2Z_HOST_INTERNAL 1
#define COMPACT_CHANNELS 3
#include "compact_kernel.h"
#include "compact_pair.h"
#pragma FUNC_ALWAYS_INLINE(compact_process_block)
#include "compact_pair.c"
#ifdef N2Z_COMPACT_EFFECT
#include "compact_runtime.h"
#else
#define N2Z_RATE_FLOATS 0u
#endif

#define HISTORY_FLOATS (PAIR_HISTORY_FLOATS + N2Z_RATE_FLOATS)
typedef char full_callback[(SH_FRAMES % 16u == 0u) ? 1 : -1];
#define BANK_WARMUP_FRAMES (((COMPACT_RECEPTIVE_FIELD + N2Z_NETWORK_FRAMES - 1u) / N2Z_NETWORK_FRAMES) * N2Z_NETWORK_FRAMES)
#define HISTORY_BYTES (HISTORY_FLOATS * sizeof(float))
#define CLEAR_PER_BLOCK 512u
static const float warmup_zero[N2Z_NETWORK_FRAMES] = {0};
#ifdef N2Z_LITE_KERNEL
#define INITIALIZED 0x50314C34u
#define RECOVERING 0x52454C34u
#else
#define INITIALIZED 0x50324231u
#define RECOVERING 0x52454331u
#endif
/* Coefficient 3 is reset by tuner firmware; Model uses a dedicated word. */
typedef char owned_model_slot[(SH_PARAM_MODEL == 12) ? 1 : -1];

typedef struct {
    CompactPairState model;
#ifdef N2Z_COMPACT_EFFECT
    CompactRateState rate;
#endif
    float low;
    float upper;
    float input_gain;
    uint32_t clear_count;
    uint32_t warm_count;
    uintptr_t base_seen;
    uint32_t span_seen;
    uint32_t active_model;
    uint32_t initialized;
#ifdef N2Z_PROFILE_COMPONENTS
    uint32_t profile_start, profile_ticks[4], profile_session;
#endif
} EffectState;

#ifdef N2Z_PROFILE_COMPONENTS
#define PROFILE_BEGIN() (state->profile_start=N2Z_PROFILE_CLOCK())
#define PROFILE_END(stage) (state->profile_ticks[stage]+=N2Z_PROFILE_CLOCK()-state->profile_start)
#else
#define PROFILE_BEGIN() ((void)0)
#define PROFILE_END(stage) ((void)0)
#endif

typedef char state_fits[(sizeof(EffectState) <= SH_STATE_BYTES) ? 1 : -1];
extern const uint32_t N2ZBankWeights[];

#pragma FUNC_ALWAYS_INLINE(silence)
static void silence(float *bus)
{
    unsigned int i;
    for (i = 0; i < 2u * SH_FRAMES; ++i) bus[i] = 0.0f;
}

#pragma FUNC_ALWAYS_INLINE(blend_output)
static float blend_output(float dry, float wet, float wet_gain)
{
    return dry * (1.0f - wet_gain) + wet * wet_gain;
}

static void mute_wet(float *bus, float wet_gain)
{
    unsigned int i;
    for (i = 0; i < 2u * SH_FRAMES; ++i) {
        float dry = bus[i];
        bus[i] = dry > -8.0f && dry < 8.0f ? dry * (1.0f - wet_gain) : 0.0f;
    }
}

static float tone_process(EffectState *state, float wet, float bass,
                          float mid, float treble)
{
    state->low += 0.034992074f * (wet - state->low);   /* 250 Hz */
    state->upper += 0.299660207f * (wet - state->upper); /* 2.5 kHz */
    return 2.0f * (bass * state->low +
                   mid * (state->upper - state->low) +
                   treble * (wet - state->upper));
}

static void effect_process(void **instance, void **ctx)
{
    EffectState *state = (EffectState *)instance[2];
    float *coeff = (float *)instance[1];
    uintptr_t descriptor_address = (uintptr_t)instance[3];
    const uint32_t *descriptor;
    uintptr_t base, end;
    uint32_t span, selected;
    float *history, fade, selector, threshold, step;
    float bass, mid, treble, volume, input, mix, wet_gain;
    const float *weights;
    float *bus = (float *)ctx[SH_CTX_EFF];
    unsigned int i;

    if (state == 0 || coeff == 0 || descriptor_address == 0 ||
        (descriptor_address & 3u) != 0 ||
        ((const uint32_t *)state)[SH_STATE_GUARD_WORD] != SH_STATE_GUARD) {
        silence(bus);
        return;
    }
    descriptor = (const uint32_t *)descriptor_address;
    base = (uintptr_t)descriptor[0];
    end = (uintptr_t)descriptor[1];
    span = descriptor[2];
    fade = coeff[SH_COEFF_BYPASS];
    selector = coeff[SH_PARAM_MODEL];
    bass = coeff[SH_PARAM_BASS];
    mid = coeff[SH_PARAM_MID];
    treble = coeff[SH_PARAM_TREBLE];
    volume = coeff[SH_PARAM_VOL];
    input = coeff[SH_PARAM_GAIN]; /* 50 = unity stereo average; 100 = 2x drive. */
    mix = coeff[SH_PARAM_MIX];
    if (base == 0 || (base & 3u) != 0 || end <= base ||
        end - base != span || span < HISTORY_BYTES ||
        !(fade >= 0.0f && fade <= 1.0f) ||
        !(bass >= 0.0f && bass <= 1.0f) ||
        !(mid >= 0.0f && mid <= 1.0f) ||
        !(treble >= 0.0f && treble <= 1.0f) ||
        !(volume >= 0.0f && volume <= 1.0f) ||
        !(input >= 0.0f && input <= 1.0f) ||
        !(mix >= 0.0f && mix <= 1.0f) ||
        !(selector >= 0.0f && selector <= 1.0f)) {
        silence(bus);
        return;
    }
    wet_gain = fade * mix;
    selected = 0;
    step = 1.0f / (float)BANK_SELECTOR_MAX;
    threshold = 0.5f * step;
    while (selected < BANK_SELECTOR_MAX && selector >= threshold) {
        ++selected;
        threshold += step;
    }
    if (selected >= BANK_MODEL_COUNT) {
        state->initialized = 0;
        return; /* the one-model bank's EMPTY selector is dry pass-through */
    }
    history = (float *)base;
    weights = (const float *)N2ZBankWeights + selected * BANK_WORDS_PER_MODEL;

    if (state->initialized != INITIALIZED || state->base_seen != base ||
        state->span_seen != span || state->active_model != selected ||
        state->clear_count > HISTORY_FLOATS ||
        state->warm_count > BANK_WARMUP_FRAMES) {
        for (i = 0; i < COMPACT_LAYERS; ++i) state->model.layer_pos[i] = 0;
        state->model.head_pos = 0;
#ifdef N2Z_COMPACT_EFFECT
        state->rate.down = state->rate.up = state->rate.dry = 0;
#endif
        state->low = 0.0f;
        state->upper = 0.0f;
        state->input_gain = input;
        state->clear_count = 0;
        state->warm_count = 0;
        state->base_seen = base;
        state->span_seen = span;
        state->active_model = selected;
        state->initialized = INITIALIZED;
    }
    if (state->clear_count < HISTORY_FLOATS) {
        unsigned int remaining = HISTORY_FLOATS - state->clear_count;
        unsigned int count = remaining < CLEAR_PER_BLOCK ? remaining : CLEAR_PER_BLOCK;
        for (i = 0; i < count; ++i) history[state->clear_count + i] = 0.0f;
        state->clear_count += count;
        mute_wet(bus, wet_gain);
        return;
    }
    if (state->warm_count < BANK_WARMUP_FRAMES) {
        unsigned int remaining = BANK_WARMUP_FRAMES - state->warm_count;
        unsigned int count = remaining < N2Z_NETWORK_FRAMES ? remaining : N2Z_NETWORK_FRAMES;
        for (i = 0; i < count; i += N2Z_NETWORK_FRAMES) {
            float ignored[N2Z_NETWORK_FRAMES];
            compact_process_block(weights, history, &state->model, warmup_zero, ignored);
#ifdef N2Z_COMPACT_EFFECT
            float discarded[16];
            compact_upsample(&state->rate, history + PAIR_HISTORY_FLOATS + 130u, ignored, discarded);
#endif
        }
        state->warm_count += count;
        mute_wet(bus, wet_gain);
        return;
    }
    for (i = 0; i < SH_FRAMES; i += 16u) {
        float dry_l[16], dry_r[16], wet[16], mono[16];
        unsigned int frame;
        for (frame = 0; frame < 16u; ++frame) {
            dry_l[frame] = bus[i + frame];
            dry_r[frame] = bus[i + frame + SH_CH_B_OFFSET];
            if (!(dry_l[frame] > -8.0f && dry_l[frame] < 8.0f)) dry_l[frame] = 0.0f;
            if (!(dry_r[frame] > -8.0f && dry_r[frame] < 8.0f)) dry_r[frame] = 0.0f;
            state->input_gain += 0.01f * (input - state->input_gain);
            mono[frame] = (dry_l[frame] + dry_r[frame]) * state->input_gain;
        }
        /* Settle exactly at the knob target, including zero input. */
        if (input-state->input_gain > -0.000004f && input-state->input_gain < 0.000004f)
            state->input_gain = input;
#ifdef N2Z_COMPACT_EFFECT
        {
            float network_in[12], network_out[12];
            PROFILE_BEGIN();
            compact_downsample(&state->rate, history + PAIR_HISTORY_FLOATS, mono, network_in);
            PROFILE_END(1);
            PROFILE_BEGIN();
            compact_process_block(weights, history, &state->model, network_in, network_out);
            PROFILE_END(0);
            for(frame=0; frame<12u; ++frame) {
                if (!(network_out[frame]>-8.0f && network_out[frame]<8.0f)) {
                    state->initialized=RECOVERING; silence(bus); return;
                }
            }
            PROFILE_BEGIN();
            compact_upsample(&state->rate, history + PAIR_HISTORY_FLOATS + 130u, network_out, wet);
            PROFILE_END(2);
            /* Keep dry timing aligned with the two FIRs for partial wet mixes. */
            if(wet_gain > 0.0f) compact_delay_dry(&state->rate, history + PAIR_HISTORY_FLOATS + 228u, dry_l, dry_r);
            else {
                float ignored_l[16], ignored_r[16];
                for(frame=0; frame<16u; ++frame) { ignored_l[frame]=dry_l[frame]; ignored_r[frame]=dry_r[frame]; }
                compact_delay_dry(&state->rate, history + PAIR_HISTORY_FLOATS + 228u, ignored_l, ignored_r);
            }
        }
#else
        PROFILE_BEGIN();
        compact_process_block(weights, history, &state->model, mono, wet);
        PROFILE_END(0);
#endif
        PROFILE_BEGIN();
        for(frame=0; frame<16u; ++frame) {
            if (!(wet[frame]>-8.0f && wet[frame]<8.0f)) {
                state->initialized=RECOVERING;
                silence(bus);
                return;
            }
        }
        for (frame = 0; frame < 16u; ++frame) {
            float out_l, out_r, modeled = wet[frame];
            modeled = tone_process(state, modeled, bass, mid, treble) * (2.0f * volume);
            out_l = blend_output(dry_l[frame], modeled, wet_gain);
            out_r = blend_output(dry_r[frame], modeled, wet_gain);
            bus[i + frame] = out_l > -8.0f && out_l < 8.0f ? out_l : 0.0f;
            bus[i + frame + SH_CH_B_OFFSET] = out_r > -8.0f && out_r < 8.0f ? out_r : 0.0f;
        }
        PROFILE_END(3);
    }
}

void SH_AUDIO_FN(void **instance, void **ctx)
{
    effect_process(instance, ctx);
}
