/* Full-rate A2 Lite, four consecutive samples per call. No integer quantization.
 * Tap-major convolution reuses each weight across four samples and input
 * history addressing across each four-sample group. Three mirrored slots make the four reads
 * contiguous even at a ring boundary; hot loops contain no wrapping branches. */
#include "compact_pair.h"
static const unsigned char kernels[23] = {6,6,6,6,6,6,6,6,6,6,6,6,6,6,15,15,6,6,6,6,6,6,6};
static const unsigned char dilations[23] = {1,3,7,17,41,101,239,1,3,7,17,41,101,239,1,13,1,3,7,17,41,101,239};
typedef struct { float current[4][3], head[4][3]; } BlockWork;

#define WRITE_LANE(L, VALUES) do { \
    int p = pos + (L); \
    if (p >= capacity) p -= capacity; \
    history[3*p] = (VALUES)[L][0]; \
    history[3*p+1] = (VALUES)[L][1]; \
    history[3*p+2] = (VALUES)[L][2]; \
    if (p < 3) { \
        history[3*(capacity+p)] = (VALUES)[L][0]; \
        history[3*(capacity+p)+1] = (VALUES)[L][1]; \
        history[3*(capacity+p)+2] = (VALUES)[L][2]; \
    } \
} while (0)

#define ACCUMULATE(L) do { \
    float a = history[q + 3*(L)], b = history[q + 3*(L)+1], c = history[q + 3*(L)+2]; \
    z##L += (w0*a + w1*b) + w2*c; \
} while (0)

#define ACCUMULATE_TWO(L) do { \
    float a=history[q+3*(L)], b=history[q+3*(L)+1], c=history[q+3*(L)+2]; \
    z##L += (w0*a+w1*b)+w2*c; \
    v##L##sum += (v0*a+v1*b)+v2*c; \
} while (0)

#define FINISH_LANE(L) do { \
    float a=values[L][0], b=values[L][1], c=values[L][2]; \
    a += mx[0]*input[L]; b += mx[1]*input[L]; c += mx[2]*input[L]; \
    if (a < 0.0f) a *= .01f; \
    if (b < 0.0f) b *= .01f; \
    if (c < 0.0f) c *= .01f; \
    work->head[L][0] += a; work->head[L][1] += b; work->head[L][2] += c; \
    work->current[L][0] += ((rb[0] + r[0]*a) + r[1]*b) + r[2]*c; \
    work->current[L][1] += ((rb[1] + r[3]*a) + r[4]*b) + r[5]*c; \
    work->current[L][2] += ((rb[2] + r[6]*a) + r[7]*b) + r[8]*c; \
} while (0)

/* Share twelve history reads between the first two outputs using eight
 * accumulators. Evaluate the third output separately to bound register use. */
#ifdef __TI_COMPILER_VERSION__
#pragma FUNC_CANNOT_INLINE(block_layer)
#endif
static void block_layer(const float *w, float *history, uint16_t *position,
                        BlockWork *work, int k, int dilation, const float input[4]) {
    int capacity = (k-1)*dilation + 4;
    int pos = *position, tap;
    const float *bias = w + 9*k, *mx = bias + 3, *r = mx + 3, *rb = r + 9;
    float values[4][3];
    WRITE_LANE(0, work->current); WRITE_LANE(1, work->current);
    WRITE_LANE(2, work->current); WRITE_LANE(3, work->current);
    {
        /* Float offsets avoid a multiply by three for every tap. */
        int limit=3*capacity, step=3*dilation, read=3*(pos+4);
        float z0=bias[0], z1=bias[0], z2=bias[0], z3=bias[0];
        float v0sum=bias[1], v1sum=bias[1], v2sum=bias[1], v3sum=bias[1];
        if (read >= limit) read-=limit;
#ifdef __TI_COMPILER_VERSION__
#pragma MUST_ITERATE(6,15,3)
#pragma UNROLL(1)
#endif
        for (tap=0; tap<k; ++tap) {
            int q=read, next;
            float w0=w[tap], w1=w[k+tap], w2=w[2*k+tap];
            float v0=w[3*k+tap], v1=w[4*k+tap], v2=w[5*k+tap];
            ACCUMULATE_TWO(0); ACCUMULATE_TWO(1); ACCUMULATE_TWO(2); ACCUMULATE_TWO(3);
            next=read+step;
            read=next-(limit & -(next>=limit));
        }
        values[0][0]=z0; values[1][0]=z1; values[2][0]=z2; values[3][0]=z3;
        values[0][1]=v0sum; values[1][1]=v1sum; values[2][1]=v2sum; values[3][1]=v3sum;
    }
    {
        const int out=2;
        /* Float offsets avoid a multiply by three for every tap. */
        int limit=3*capacity, step=3*dilation, read=3*(pos+4);
        float z0=bias[out], z1=bias[out], z2=bias[out], z3=bias[out];
        const float *cw=w+out*3*k;
        if (read >= limit) read-=limit;
#ifdef __TI_COMPILER_VERSION__
#pragma MUST_ITERATE(6,15,3)
#pragma UNROLL(1)
#endif
        for (tap=0; tap<k; ++tap) {
            int q=read, next;
            float w0=cw[tap], w1=cw[k+tap], w2=cw[2*k+tap];
            ACCUMULATE(0); ACCUMULATE(1); ACCUMULATE(2); ACCUMULATE(3);
            next=read+step;
            read = next - (limit & -(next>=limit));
        }
        values[0][out]=z0; values[1][out]=z1; values[2][out]=z2; values[3][out]=z3;
    }
    FINISH_LANE(0); FINISH_LANE(1); FINISH_LANE(2); FINISH_LANE(3);
    pos += 4; if (pos >= capacity) pos -= capacity;
    *position = (uint16_t)pos;
}

void compact_process_quad(const float *weights, float *history, CompactPairState *state,
                          const float input[4], float output[4]) {
    BlockWork work;
    const float *w=weights+3;
    int layer, lane, channel;
    for (lane=0; lane<4; ++lane) for (channel=0; channel<3; ++channel) {
        work.current[lane][channel] = weights[channel]*input[lane];
        work.head[lane][channel] = 0.0f;
    }
    for (layer=0; layer<23; ++layer) {
        int k=kernels[layer], d=dilations[layer];
        block_layer(w,history,&state->layer_pos[layer],&work,k,d,input);
        history += 3*((k-1)*d+7);
        w += 9*k+18;
    }
    {
        int capacity=19, pos=state->head_pos, tap;
        float y0=w[48], y1=w[48], y2=w[48], y3=w[48];
        WRITE_LANE(0, work.head); WRITE_LANE(1, work.head);
        WRITE_LANE(2, work.head); WRITE_LANE(3, work.head);
        for (channel=0; channel<3; ++channel) {
            int read=pos+4; if (read >= capacity) read-=capacity;
#ifdef __TI_COMPILER_VERSION__
#pragma MUST_ITERATE(16,16,16)
#pragma UNROLL(1)
#endif
            for (tap=0; tap<16; ++tap) {
                float coefficient=w[channel*16+tap];
                int q=3*read+channel, next=read+1;
                y0 += coefficient*history[q]; y1 += coefficient*history[q+3];
                y2 += coefficient*history[q+6]; y3 += coefficient*history[q+9];
                read=next-(capacity & -(next >= capacity));
            }
        }
        pos+=4; if (pos >= capacity) pos-=capacity;
        state->head_pos=(uint16_t)pos;
        output[0]=y0*w[49]; output[1]=y1*w[49]; output[2]=y2*w[49]; output[3]=y3*w[49];
    }
}
