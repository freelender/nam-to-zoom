#ifndef N2Z_OWN_BLOCK4_H
#define N2Z_OWN_BLOCK4_H
#include <stdint.h>
#define PAIR_LAYERS 23
#define PAIR_WEIGHTS 1871
#define N2Z_FULL_HISTORY_FLOATS 20406
#ifdef N2Z_COMPACT_EFFECT
#define N2Z_NETWORK_FRAMES 12
#define PAIR_HISTORY_FLOATS 20118
#else
#define N2Z_NETWORK_FRAMES 16
#define PAIR_HISTORY_FLOATS N2Z_FULL_HISTORY_FLOATS
#endif
typedef struct {
    uint16_t layer_pos[PAIR_LAYERS];
    uint16_t head_pos;
} CompactPairState;
#ifdef N2Z_HOST_INTERNAL
#define N2Z_KERNEL_SCOPE static
#else
#define N2Z_KERNEL_SCOPE
#endif
N2Z_KERNEL_SCOPE void compact_process_block(const float *weights, float *history,
                          CompactPairState *state, const float input[N2Z_NETWORK_FRAMES], float output[N2Z_NETWORK_FRAMES]);
#endif
