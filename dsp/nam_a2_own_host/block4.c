/* Full-rate A2 Lite: one 16-frame callback, two-lane convolution groups.
 * Process a whole callback per layer to reduce setup and improve history
 * locality. Three mirrored slots also support four-lane output-head reads.
 * Float32 weights and sample rate are unchanged. */
#include "compact_pair.h"
static const unsigned char kernels[23] = {6,6,6,6,6,6,6,6,6,6,6,6,6,6,15,15,6,6,6,6,6,6,6};
static const unsigned char dilations[23] = {1,3,7,17,41,101,239,1,3,7,17,41,101,239,1,13,1,3,7,17,41,101,239};
typedef struct { float current[N2Z_NETWORK_FRAMES][3], head[N2Z_NETWORK_FRAMES][3]; } BlockWork;

#define FINISH_LANE(L) do { \
    float a=values[L][0], b=values[L][1], c=values[L][2]; \
    a += mx[0]*input[base+(L)]; b += mx[1]*input[base+(L)]; c += mx[2]*input[base+(L)]; \
    if (a < 0.0f) a *= .01f; \
    if (b < 0.0f) b *= .01f; \
    if (c < 0.0f) c *= .01f; \
    work->head[base+(L)][0] += a; work->head[base+(L)][1] += b; work->head[base+(L)][2] += c; \
    work->current[base+(L)][0] += ((rb[0] + r[0]*a) + r[1]*b) + r[2]*c; \
    work->current[base+(L)][1] += ((rb[1] + r[3]*a) + r[4]*b) + r[5]*c; \
    work->current[base+(L)][2] += ((rb[2] + r[6]*a) + r[7]*b) + r[8]*c; \
} while (0)

/* Two samples across all three outputs share each history read. Six
 * accumulators bound register pressure; the caller supplies disjoint arrays. */
#ifdef __TI_COMPILER_VERSION__
#pragma FUNC_CANNOT_INLINE(block_layer)
#endif
static void block_layer(const float * restrict w, float * restrict history, uint16_t * restrict position,
                        BlockWork * restrict work, int k, int dilation, const float input[N2Z_NETWORK_FRAMES]) {
    int capacity = (k-1)*dilation + N2Z_NETWORK_FRAMES;
    int pos = *position, tap, base, lane;
    const float *bias = w + 9*k, *mx = bias + 3, *r = mx + 3, *rb = r + 9;
    float values[2][3];
    for (lane=0; lane<N2Z_NETWORK_FRAMES; ++lane) {
        int p=pos+lane; if (p>=capacity) p-=capacity;
        history[3*p]=work->current[lane][0];
        history[3*p+1]=work->current[lane][1];
        history[3*p+2]=work->current[lane][2];
        if(p<3) {
            history[3*(capacity+p)]=work->current[lane][0];
            history[3*(capacity+p)+1]=work->current[lane][1];
            history[3*(capacity+p)+2]=work->current[lane][2];
        }
    }
    for (base=0; base<N2Z_NETWORK_FRAMES; base+=2) {
        int limit=3*capacity, step=3*dilation, read=3*(pos+N2Z_NETWORK_FRAMES+base);
        float z00=bias[0], z01=bias[0], z10=bias[1], z11=bias[1], z20=bias[2], z21=bias[2];
        if(read>=limit) read-=limit;
        if(read>=limit) read-=limit;
#ifdef __TI_COMPILER_VERSION__
#pragma MUST_ITERATE(6,15,3)
#pragma UNROLL(1)
#endif
        for(tap=0;tap<k;++tap) {
            float a0=history[read], b0=history[read+1], c0=history[read+2];
            float a1=history[read+3], b1=history[read+4], c1=history[read+5];
            float w00=w[tap], w01=w[k+tap], w02=w[2*k+tap];
            float w10=w[3*k+tap], w11=w[4*k+tap], w12=w[5*k+tap];
            float w20=w[6*k+tap], w21=w[7*k+tap], w22=w[8*k+tap];
            int next=read+step;
            z00+=(w00*a0+w01*b0)+w02*c0; z01+=(w00*a1+w01*b1)+w02*c1;
            z10+=(w10*a0+w11*b0)+w12*c0; z11+=(w10*a1+w11*b1)+w12*c1;
            z20+=(w20*a0+w21*b0)+w22*c0; z21+=(w20*a1+w21*b1)+w22*c1;
            read=next-(limit & -(next>=limit));
        }
        values[0][0]=z00; values[0][1]=z10; values[0][2]=z20;
        values[1][0]=z01; values[1][1]=z11; values[1][2]=z21;
        FINISH_LANE(0); FINISH_LANE(1);
    }
    pos += N2Z_NETWORK_FRAMES; if (pos >= capacity) pos -= capacity;
    *position = (uint16_t)pos;
}

N2Z_KERNEL_SCOPE void compact_process_block(const float *weights, float *history, CompactPairState *state,
                          const float input[N2Z_NETWORK_FRAMES], float output[N2Z_NETWORK_FRAMES]) {
    BlockWork work;
    const float *w=weights+3;
    int layer, lane, channel;
    for (lane=0; lane<N2Z_NETWORK_FRAMES; ++lane) for (channel=0; channel<3; ++channel) {
        work.current[lane][channel] = weights[channel]*input[lane];
        work.head[lane][channel] = 0.0f;
    }
    for (layer=0; layer<23; ++layer) {
        int k=kernels[layer], d=dilations[layer];
        block_layer(w,history,&state->layer_pos[layer],&work,k,d,input);
        history += 3*((k-1)*d+N2Z_NETWORK_FRAMES+3);
        w += 9*k+18;
    }
    {
        int capacity=15+N2Z_NETWORK_FRAMES, pos=state->head_pos, tap, base;
        for (lane=0; lane<N2Z_NETWORK_FRAMES; ++lane) {
            int p=pos+lane; if(p>=capacity) p-=capacity;
            for(channel=0; channel<3; ++channel) {
                history[3*p+channel]=work.head[lane][channel];
                if(p<3) history[3*(capacity+p)+channel]=work.head[lane][channel];
            }
        }
        for(base=0; base<N2Z_NETWORK_FRAMES; base+=4) {
            float y0=w[48], y1=w[48], y2=w[48], y3=w[48];
            for(channel=0; channel<3; ++channel) {
                int read=pos+N2Z_NETWORK_FRAMES+base; if(read>=capacity) read-=capacity;
#ifdef __TI_COMPILER_VERSION__
#pragma MUST_ITERATE(16,16,16)
#pragma UNROLL(1)
#endif
                for(tap=0; tap<16; ++tap) {
                    float coefficient=w[channel*16+tap];
                    int q=3*read+channel, next=read+1;
                    y0+=coefficient*history[q]; y1+=coefficient*history[q+3];
                    y2+=coefficient*history[q+6]; y3+=coefficient*history[q+9];
                    read=next-(capacity & -(next>=capacity));
                }
            }
            output[base]=y0*w[49]; output[base+1]=y1*w[49];
            output[base+2]=y2*w[49]; output[base+3]=y3*w[49];
        }
        pos+=N2Z_NETWORK_FRAMES; if(pos>=capacity) pos-=capacity;
        state->head_pos=(uint16_t)pos;
    }
}
