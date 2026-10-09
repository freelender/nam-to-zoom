/* Temporary Lite timing probe. Reads TSCL only; never changes clock/cache registers.
 * Uses the Plus production ABI and callback, including its startup safeguards.
 * After one measurement the network stays parked; bypass/on starts a new run. */
#include "sh_params.h"
#undef SH_AUDIO_FN
#define SH_AUDIO_FN n2z_measured_audio
#pragma FUNC_CANNOT_INLINE(n2z_measured_audio)
#include "bank_effect.c"
#undef SH_AUDIO_FN
#define SH_AUDIO_FN Fx_SFX_N2ZBank

#ifndef N2Z_READ_CLOCK
#include <c6x.h>
#define N2Z_READ_CLOCK() ((uint32_t)TSCL)
#endif
#include "timing_config.h"
#define TIMING_MAGIC 0x54494D31u
#define PACKET_WORDS 19u
#define CAL_BLOCKS 2048u
#define RUN_BLOCKS 4096u

/* Firmware state is only assumed word-aligned. Keep accumulators as two words
 * so the compiler cannot emit aligned 64-bit loads against that state. */
typedef struct { uint32_t lo, hi; } TickSum;
static void sum_add(TickSum *sum, uint32_t value)
{
    uint32_t previous = sum->lo;
    sum->lo += value;
    if (sum->lo < previous) ++sum->hi;
}
static uint32_t sum_shift(TickSum sum, unsigned shift)
{
    return (sum.lo >> shift) | (sum.hi << (32u - shift));
}
typedef struct {
    TickSum total, arrival_total;
    uint32_t count, previous, have_previous, minimum, maximum, overhead, warm_calls;
    uint32_t arrival_min, arrival_max, idle_mean, idle_min, idle_max;
} TimingStats;
typedef struct {
    uint32_t magic, stage, sample, phase;
    union { TimingStats stats; uint32_t packet[PACKET_WORDS]; } data;
} TimingMeter;
typedef struct { EffectState net; TimingMeter meter; } TimingState;
typedef char timing_fits[(sizeof(TimingState) <= SH_STATE_BYTES) ? 1 : -1];

/* Constant unsigned division without a firmware/runtime-library dependency.
 * Only used once, after measurement has ended. */
static uint32_t average_arrival(uint64_t value)
{
    uint32_t hi = (uint32_t)(value >> 32), lo = (uint32_t)value;
    uint32_t remainder = 0u, quotient = 0u, i;
    for (i = 0; i < 64u; ++i) {
        remainder = (remainder << 1) | (hi >> 31);
        hi = (hi << 1) | (lo >> 31); lo <<= 1;
        quotient <<= 1;
        if (remainder >= RUN_BLOCKS - 1u) {
            remainder -= RUN_BLOCKS - 1u; quotient |= 1u;
        }
    }
    return quotient;
}

static void finish(TimingMeter *m, uint32_t status)
{
    TimingStats saved;
    /* Volatile scalar copy prevents an imported memcpy in the freestanding DSP. */
    volatile uint32_t *dst = (volatile uint32_t *)&saved;
    const volatile uint32_t *src = (const volatile uint32_t *)&m->data.stats;
    uint32_t crc = 0xffffffffu, i, j, byte;
    for (i = 0; i < sizeof(saved) / sizeof(uint32_t); ++i) dst[i] = src[i];
    for (i = 0; i < PACKET_WORDS; ++i) m->data.packet[i] = 0u;
    m->data.packet[0] = 0x4e32545au;
    m->data.packet[1] = 1u;
    m->data.packet[2] = N2Z_TIMING_VARIANT;
    m->data.packet[3] = status;
    m->data.packet[4] = status == 0u ? RUN_BLOCKS : 0u;
    m->data.packet[5] = SH_FRAMES;
    m->data.packet[6] = saved.idle_mean;
    m->data.packet[7] = saved.idle_min;
    m->data.packet[8] = saved.idle_max;
    m->data.packet[9] = saved.overhead;
    if (status == 0u) {
        m->data.packet[10] = sum_shift(saved.total, 12u);
        m->data.packet[11] = saved.minimum;
        m->data.packet[12] = saved.maximum;
        m->data.packet[13] = average_arrival(((uint64_t)saved.arrival_total.hi << 32) | saved.arrival_total.lo);
        m->data.packet[14] = saved.arrival_min;
        m->data.packet[15] = saved.arrival_max;
    }
    m->data.packet[16] = saved.warm_calls;
    m->data.packet[17] = N2Z_TIMING_MODEL_TAG;
    for (i = 0; i < PACKET_WORDS - 1u; ++i) {
        uint32_t word = m->data.packet[i];
        for (byte = 0; byte < 4u; ++byte) {
            crc ^= word & 255u;
            word >>= 8;
            for (j = 0; j < 8u; ++j)
                crc = (crc >> 1) ^ (0xedb88320u & (0u - (crc & 1u)));
        }
    }
    m->data.packet[18] = crc ^ 0xffffffffu;
    m->stage = 3u;
    m->sample = m->phase = 0u;
}

static void tones(TimingMeter *m, float *bus)
{
    unsigned i;
    for (i = 0; i < SH_FRAMES; ++i) {
        uint32_t slot = m->sample / 882u;
        uint32_t offset = m->sample % 882u;
        float value = 0.0f;
        if (slot < PACKET_WORDS * 32u && offset < 441u) {
            uint32_t bit = (m->data.packet[slot >> 5] >> (31u - (slot & 31u))) & 1u;
            int triangle = m->phase < 32u ? (int)m->phase : 64 - (int)m->phase;
            value = ((float)triangle - 16.0f) * 0.0025f;
            m->phase = (m->phase + 1u + bit) & 63u;
        } else m->phase = 0u;
        bus[i] = bus[i + SH_CH_B_OFFSET] = value;
        if (++m->sample == PACKET_WORDS * 32u * 882u + 33075u) m->sample = 0u;
    }
}

void SH_AUDIO_FN(void **instance, void **ctx)
{
    TimingState *s;
    TimingMeter *m;
    float *bus, *coeff;
    uint32_t now, elapsed, end, cost;
    unsigned i;
    if (!instance || !ctx || !ctx[SH_CTX_EFF] || !instance[2] || !instance[1]) return;
    bus = (float *)ctx[SH_CTX_EFF];
    s = (TimingState *)instance[2];
    if (((const uint32_t *)s)[SH_STATE_GUARD_WORD] != SH_STATE_GUARD) return;
    m = &s->meter;
    coeff = (float *)instance[1];
    if (coeff[SH_COEFF_BYPASS] < 0.99f) { m->magic = 0u; return; }
    now = N2Z_READ_CLOCK();
    if (m->magic != TIMING_MAGIC) {
        uint32_t *p = (uint32_t *)m;
        for (i = 0; i < sizeof(*m) / sizeof(uint32_t); ++i) p[i] = 0u;
        m->magic = TIMING_MAGIC;
        m->data.stats.minimum = m->data.stats.arrival_min = 0xffffffffu;
        m->data.stats.overhead = N2Z_READ_CLOCK() - now;
        s->net.initialized = 0u;
    }
    if (m->stage == 3u) { tones(m, bus); return; }
    /* Controls are fixed for a comparable full-wet, first-model measurement. */
    if (!(coeff[0] <= 1.0f && coeff[0] >= 0.99f) || coeff[SH_PARAM_MODEL] != 0.0f ||
        coeff[SH_PARAM_MIX] != 1.0f || coeff[SH_PARAM_BASS] != 0.5f ||
        coeff[SH_PARAM_MID] != 0.5f || coeff[SH_PARAM_TREBLE] != 0.5f ||
        coeff[SH_PARAM_VOL] != 0.5f || coeff[SH_PARAM_INPUT] != 0.5f) {
        finish(m, 4u); silence(bus); return;
    }
    elapsed = now - m->data.stats.previous; /* unsigned arithmetic handles TSCL rollover */
    m->data.stats.previous = now;
    if (m->stage == 0u) {
        if (m->data.stats.have_previous) {
            sum_add(&m->data.stats.total, elapsed);
            if (elapsed < m->data.stats.minimum) m->data.stats.minimum = elapsed;
            if (elapsed > m->data.stats.maximum) m->data.stats.maximum = elapsed;
            if (++m->data.stats.count == CAL_BLOCKS) {
                m->data.stats.idle_mean = sum_shift(m->data.stats.total, 11u);
                m->data.stats.idle_min = m->data.stats.minimum;
                m->data.stats.idle_max = m->data.stats.maximum;
                m->stage = 1u; m->data.stats.count = 0u;
                m->data.stats.total.lo = m->data.stats.total.hi = 0u;
                m->data.stats.minimum = 0xffffffffu; m->data.stats.maximum = 0u;
                if (!m->data.stats.idle_mean) finish(m, 1u);
            }
        }
        if (m->stage != 3u) m->data.stats.have_previous = 1u;
        silence(bus); return;
    }
    if (m->stage == 1u) {
        n2z_measured_audio(instance, ctx);
        if (++m->data.stats.warm_calls > 2048u) { finish(m, 3u); return; }
        if (s->net.initialized == INITIALIZED && s->net.clear_count == HISTORY_FLOATS &&
            s->net.warm_count == BANK_WARMUP_FRAMES) m->stage = 2u;
        return;
    }
    /* First arrival spans warmup/measurement; exclude it from loaded cadence. */
    if (m->data.stats.count) {
        sum_add(&m->data.stats.arrival_total, elapsed);
        if (elapsed < m->data.stats.arrival_min) m->data.stats.arrival_min = elapsed;
        if (elapsed > m->data.stats.arrival_max) m->data.stats.arrival_max = elapsed;
    }
    now = N2Z_READ_CLOCK();
    n2z_measured_audio(instance, ctx);
    end = N2Z_READ_CLOCK();
    cost = end - now;
    if (s->net.initialized != INITIALIZED || s->net.warm_count != BANK_WARMUP_FRAMES) {
        finish(m, 2u); return;
    }
    sum_add(&m->data.stats.total, cost);
    if (cost < m->data.stats.minimum) m->data.stats.minimum = cost;
    if (cost > m->data.stats.maximum) m->data.stats.maximum = cost;
    if (++m->data.stats.count == RUN_BLOCKS) {
        finish(m, cost == 0u && m->data.stats.maximum == 0u ? 1u : 0u);
    }
}
