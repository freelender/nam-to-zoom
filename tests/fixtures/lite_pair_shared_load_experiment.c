#include "compact_pair.h"

static const unsigned char lite_kernels[PAIR_LAYERS] = {6,6,6,6,6,6,6,6,6,6,6,6,6,6,15,15,6,6,6,6,6,6,6};
static const unsigned char lite_dilations[PAIR_LAYERS] = {1,3,7,17,41,101,239,1,3,7,17,41,101,239,1,13,1,3,7,17,41,101,239};

/* Full-rate, two-sample A2 Lite. Reuse each pair of history loads across
   all three output channels instead of loading that window three times.
   Fixed trip counts keep the MAC loop modulo-scheduled on TI C674x.
   Geometry, causal ring layout, weights and inference rate are unchanged.
   Summation order differs from the original split accumulators by rounding. */
typedef struct {
    float current[2][3];
    float head[2][3];
} LiteWork;

#ifdef __TI_COMPILER_VERSION__
#pragma FUNC_CANNOT_INLINE(lite_layer6)
#endif
static void lite_layer6(const float *w, float *history, uint16_t *position,
                         LiteWork *work, int dilation, float input0, float input1) {
    int capacity = 5 * dilation + 2;
    int pos0 = *position, pos1 = pos0 + 1;
    int read0 = pos0 + 2, read1;
    int tap0[6], tap1[6], tap, channel;
    const float *bias = w + 54, *mixin = bias + 3;
    const float *residual = mixin + 3, *rbias = residual + 9;
    float activation[2][3];
    if (pos1 == capacity) pos1 = 0;
    if (read0 >= capacity) read0 -= capacity;
    read1 = read0 + 1;
    if (read1 == capacity) read1 = 0;
    for (channel = 0; channel < 3; ++channel) {
        history[3 * pos0 + channel] = work->current[0][channel];
        history[3 * pos1 + channel] = work->current[1][channel];
    }
    for (tap = 0; tap < 6; ++tap) {
        tap0[tap] = 3 * read0;
        tap1[tap] = 3 * read1;
        read0 += dilation; read1 += dilation;
        if (read0 >= capacity) read0 -= capacity;
        if (read1 >= capacity) read1 -= capacity;
    }
    {
        float z00 = bias[0], z01 = bias[1], z02 = bias[2];
        float z10 = bias[0], z11 = bias[1], z12 = bias[2];
        int input_channel;
        for (input_channel = 0; input_channel < 3; ++input_channel) {
#ifdef __TI_COMPILER_VERSION__
#pragma MUST_ITERATE(6,6,6)
#pragma UNROLL(1)
#endif
            for (tap = 0; tap < 6; ++tap) {
                float v0 = history[tap0[tap] + input_channel];
                float v1 = history[tap1[tap] + input_channel];
                float c0 = w[6 * input_channel + tap];
                float c1 = w[3 * 6 + 6 * input_channel + tap];
                float c2 = w[6 * 6 + 6 * input_channel + tap];
                z00 += c0 * v0; z10 += c0 * v1;
                z01 += c1 * v0; z11 += c1 * v1;
                z02 += c2 * v0; z12 += c2 * v1;
            }
        }
        activation[0][0] = z00; activation[0][1] = z01; activation[0][2] = z02;
        activation[1][0] = z10; activation[1][1] = z11; activation[1][2] = z12;
        for (channel = 0; channel < 3; ++channel) {
            float z0 = activation[0][channel] + mixin[channel] * input0;
            float z1 = activation[1][channel] + mixin[channel] * input1;
            if (z0 < 0.0f) z0 *= 0.01f;
            if (z1 < 0.0f) z1 *= 0.01f;
            activation[0][channel] = z0; activation[1][channel] = z1;
            work->head[0][channel] += z0; work->head[1][channel] += z1;
        }
    }
    for (channel = 0; channel < 3; ++channel) {
        float r0 = rbias[channel], r1 = rbias[channel];
        r0 += residual[3 * channel] * activation[0][0];
        r1 += residual[3 * channel] * activation[1][0];
        r0 += residual[3 * channel + 1] * activation[0][1];
        r1 += residual[3 * channel + 1] * activation[1][1];
        r0 += residual[3 * channel + 2] * activation[0][2];
        r1 += residual[3 * channel + 2] * activation[1][2];
        work->current[0][channel] += r0; work->current[1][channel] += r1;
    }
    ++pos1;
    if (pos1 == capacity) pos1 = 0;
    *position = (uint16_t)pos1;
}

#ifdef __TI_COMPILER_VERSION__
#pragma FUNC_CANNOT_INLINE(lite_layer15)
#endif
static void lite_layer15(const float *w, float *history, uint16_t *position,
                         LiteWork *work, int dilation, float input0, float input1) {
    int capacity = 14 * dilation + 2;
    int pos0 = *position, pos1 = pos0 + 1;
    int read0 = pos0 + 2, read1;
    int tap0[15], tap1[15], tap, channel;
    const float *bias = w + 135, *mixin = bias + 3;
    const float *residual = mixin + 3, *rbias = residual + 9;
    float activation[2][3];
    if (pos1 == capacity) pos1 = 0;
    if (read0 >= capacity) read0 -= capacity;
    read1 = read0 + 1;
    if (read1 == capacity) read1 = 0;
    for (channel = 0; channel < 3; ++channel) {
        history[3 * pos0 + channel] = work->current[0][channel];
        history[3 * pos1 + channel] = work->current[1][channel];
    }
    for (tap = 0; tap < 15; ++tap) {
        tap0[tap] = 3 * read0;
        tap1[tap] = 3 * read1;
        read0 += dilation; read1 += dilation;
        if (read0 >= capacity) read0 -= capacity;
        if (read1 >= capacity) read1 -= capacity;
    }
    {
        float z00 = bias[0], z01 = bias[1], z02 = bias[2];
        float z10 = bias[0], z11 = bias[1], z12 = bias[2];
        int input_channel;
        for (input_channel = 0; input_channel < 3; ++input_channel) {
#ifdef __TI_COMPILER_VERSION__
#pragma MUST_ITERATE(15,15,15)
#pragma UNROLL(1)
#endif
            for (tap = 0; tap < 15; ++tap) {
                float v0 = history[tap0[tap] + input_channel];
                float v1 = history[tap1[tap] + input_channel];
                float c0 = w[15 * input_channel + tap];
                float c1 = w[3 * 15 + 15 * input_channel + tap];
                float c2 = w[6 * 15 + 15 * input_channel + tap];
                z00 += c0 * v0; z10 += c0 * v1;
                z01 += c1 * v0; z11 += c1 * v1;
                z02 += c2 * v0; z12 += c2 * v1;
            }
        }
        activation[0][0] = z00; activation[0][1] = z01; activation[0][2] = z02;
        activation[1][0] = z10; activation[1][1] = z11; activation[1][2] = z12;
        for (channel = 0; channel < 3; ++channel) {
            float z0 = activation[0][channel] + mixin[channel] * input0;
            float z1 = activation[1][channel] + mixin[channel] * input1;
            if (z0 < 0.0f) z0 *= 0.01f;
            if (z1 < 0.0f) z1 *= 0.01f;
            activation[0][channel] = z0; activation[1][channel] = z1;
            work->head[0][channel] += z0; work->head[1][channel] += z1;
        }
    }
    for (channel = 0; channel < 3; ++channel) {
        float r0 = rbias[channel], r1 = rbias[channel];
        r0 += residual[3 * channel] * activation[0][0];
        r1 += residual[3 * channel] * activation[1][0];
        r0 += residual[3 * channel + 1] * activation[0][1];
        r1 += residual[3 * channel + 1] * activation[1][1];
        r0 += residual[3 * channel + 2] * activation[0][2];
        r1 += residual[3 * channel + 2] * activation[1][2];
        work->current[0][channel] += r0; work->current[1][channel] += r1;
    }
    ++pos1;
    if (pos1 == capacity) pos1 = 0;
    *position = (uint16_t)pos1;
}

#undef LITE_ACC

void compact_process_pair(const float *weights, float *history, CompactPairState *state,
                          float input0, float input1, float *output0, float *output1) {
    LiteWork work;
    const float *w = weights + 3;
    int layer, channel, tap;
    for (channel = 0; channel < 3; ++channel) {
        work.current[0][channel] = weights[channel] * input0;
        work.current[1][channel] = weights[channel] * input1;
        work.head[0][channel] = work.head[1][channel] = 0.0f;
    }
    for (layer = 0; layer < PAIR_LAYERS; ++layer) {
        int k = lite_kernels[layer], d = lite_dilations[layer];
        if (k == 6)
            lite_layer6(w, history, &state->layer_pos[layer], &work, d, input0, input1);
        else
            lite_layer15(w, history, &state->layer_pos[layer], &work, d, input0, input1);
        history += 3 * ((k - 1) * d + 2);
        w += 9 * k + 18;
    }
    {
        int pos0 = state->head_pos, pos1 = pos0 + 1;
        float y0 = w[48], y1 = w[48];
        if (pos1 == 17) pos1 = 0;
        for (channel = 0; channel < 3; ++channel) {
            history[3 * pos0 + channel] = work.head[0][channel];
            history[3 * pos1 + channel] = work.head[1][channel];
        }
        for (channel = 0; channel < 3; ++channel) {
            int read0 = pos0 + 2, read1 = pos1 + 2;
            if (read0 >= 17) read0 -= 17;
            if (read1 >= 17) read1 -= 17;
            for (tap = 0; tap < 16; ++tap) {
                float coefficient = w[channel * 16 + tap];
                y0 += coefficient * history[3 * read0 + channel];
                y1 += coefficient * history[3 * read1 + channel];
                if (++read0 == 17) read0 = 0;
                if (++read1 == 17) read1 = 0;
            }
        }
        if (++pos1 == 17) pos1 = 0;
        state->head_pos = (uint16_t)pos1;
        *output0 = y0 * w[49]; *output1 = y1 * w[49];
    }
}
