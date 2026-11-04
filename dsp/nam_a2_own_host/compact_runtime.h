#ifndef N2Z_COMPACT_RUNTIME_H
#define N2Z_COMPACT_RUNTIME_H
/* 3/4-rate neural runtime. The public NAM and pedal I/O remain 44.1 kHz.
 * Two 193-tap polyphase FIRs add exactly 64 I/O samples of delay. Mirror
 * histories remove wrapping from FIR inner loops. Four independent sums and
 * contiguous per-phase coefficients retain the same FIR response. */
#include "compact_filters.h"
#define N2Z_RATE_FLOATS (130u + 98u + 128u)
typedef struct { unsigned down, up, dry; } CompactRateState;
static const unsigned char down_target[12]={0,1,2,4,5,6,8,9,10,12,13,14};
static const unsigned char down_phase[12]={0,1,2,0,1,2,0,1,2,0,1,2};
static const unsigned char up_target[16]={0,0,1,2,3,3,4,5,6,6,7,8,9,9,10,11};
static const unsigned char up_phase[16]={0,3,2,1,0,3,2,1,0,3,2,1,0,3,2,1};

#ifdef __TI_COMPILER_VERSION__
#pragma FUNC_CANNOT_INLINE(compact_downsample)
#endif
static void compact_downsample(CompactRateState *state, float *h,
                               const float input[16], float output[12]) {
    unsigned pos=state->down, j;
    int consumed=-1;
    for(j=0;j<12;++j) {
        unsigned phase=down_phase[j], t;
        const float *coefficients=N2Z_DownPhaseCoefficients[phase];
        int read;
        float sum0=0, sum1=0, sum2=0, sum3=0;
        while(consumed<(int)down_target[j]) {
            float x=input[++consumed]; h[pos]=h[pos+65u]=x;
            if(++pos==65u) pos=0;
        }
        read=(int)pos+64;
#ifdef __TI_COMPILER_VERSION__
#pragma MUST_ITERATE(16,16,16)
#pragma UNROLL(1)
#endif
        for(t=0;t<64;t+=4) {
            sum0+=coefficients[t+0]*h[read-0];
            sum1+=coefficients[t+1]*h[read-1];
            sum2+=coefficients[t+2]*h[read-2];
            sum3+=coefficients[t+3]*h[read-3];
            read-=4;
        }
        if(phase==0u) sum0+=coefficients[64]*h[read];
        output[j]=sum0+sum1+sum2+sum3;
    }
    /* The final input has no output at this phase, but belongs to history. */
    h[pos]=h[pos+65u]=input[15]; if(++pos==65u) pos=0;
    state->down=pos;
}

#ifdef __TI_COMPILER_VERSION__
#pragma FUNC_CANNOT_INLINE(compact_upsample)
#endif
static void compact_upsample(CompactRateState *state, float *h,
                             const float input[12], float output[16]) {
    unsigned pos=state->up, j;
    int consumed=-1;
    for(j=0;j<16;++j) {
        unsigned phase=up_phase[j], t;
        const float *coefficients=N2Z_UpPhaseCoefficients[phase];
        int read;
        float sum0=0, sum1=0, sum2=0, sum3=0;
        while(consumed<(int)up_target[j]) {
            float x=input[++consumed]; h[pos]=h[pos+49u]=x;
            if(++pos==49u) pos=0;
        }
        read=(int)pos+48;
#ifdef __TI_COMPILER_VERSION__
#pragma MUST_ITERATE(12,12,12)
#pragma UNROLL(1)
#endif
        for(t=0;t<48;t+=4) {
            sum0+=coefficients[t+0]*h[read-0];
            sum1+=coefficients[t+1]*h[read-1];
            sum2+=coefficients[t+2]*h[read-2];
            sum3+=coefficients[t+3]*h[read-3];
            read-=4;
        }
        if(phase==0u) sum0+=coefficients[48]*h[read];
        output[j]=sum0+sum1+sum2+sum3;
    }
    state->up=pos;
}

static void compact_delay_dry(CompactRateState *state, float *h,
                              float *left, float *right) {
    unsigned pos=state->dry, i;
    for(i=0;i<16;++i) {
        float l=h[2u*pos], r=h[2u*pos+1u];
        h[2u*pos]=left[i]; h[2u*pos+1u]=right[i];
        left[i]=l; right[i]=r;
        if(++pos==64u) pos=0;
    }
    state->dry=pos;
}
#endif
