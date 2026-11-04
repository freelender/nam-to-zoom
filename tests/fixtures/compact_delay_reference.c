/* Independent, scalar definition of Compact's rounded-delay network.
 * Deliberately no mirrored reads, step tables or multi-sample scheduling. */
#include "compact_pair.h"
static const int ref_k[23]={6,6,6,6,6,6,6,6,6,6,6,6,6,6,15,15,6,6,6,6,6,6,6};
static const int ref_d[23]={1,3,7,17,41,101,239,1,3,7,17,41,101,239,1,13,1,3,7,17,41,101,239};
void compact_reference(const float *weights, float *history, CompactPairState *state,
                       const float input[12], float output[12]) {
    for(int sample=0;sample<12;sample++) {
        float current[3], head[3]={0,0,0};
        const float *w=weights+3; float *h=history;
        for(int c=0;c<3;c++) current[c]=weights[c]*input[sample];
        for(int layer=0;layer<23;layer++) {
            int k=ref_k[layer], d=ref_d[layer], cap=(k-1)*d+12;
            int pos=state->layer_pos[layer];
            const float *bias=w+9*k, *mx=bias+3, *r=mx+3, *rb=r+9;
            float v[3]={bias[0],bias[1],bias[2]};
            for(int c=0;c<3;c++)h[3*pos+c]=current[c];
            for(int tap=0;tap<k;tap++) {
                int delay=(3*(k-1-tap)*d+2)/4, read=pos-delay;
                if(read<0)read+=cap;
                float a=h[3*read],b=h[3*read+1],c=h[3*read+2];
                for(int row=0;row<3;row++)
                    v[row]+=(w[(3*row)*k+tap]*a+w[(3*row+1)*k+tap]*b)+w[(3*row+2)*k+tap]*c;
            }
            for(int c=0;c<3;c++) {v[c]+=mx[c]*input[sample];if(v[c]<0)v[c]*=.01f;head[c]+=v[c];}
            for(int c=0;c<3;c++)current[c]+=((rb[c]+r[3*c]*v[0])+r[3*c+1]*v[1])+r[3*c+2]*v[2];
            state->layer_pos[layer]=(pos+1)%cap;
            h+=3*(cap+3);w+=9*k+18;
        }
        int cap=27,pos=state->head_pos;float y=w[48];
        for(int c=0;c<3;c++)h[3*pos+c]=head[c];
        for(int c=0;c<3;c++)for(int tap=0;tap<16;tap++) {
            int delay=(3*(15-tap)+2)/4,read=pos-delay;if(read<0)read+=cap;
            y+=w[c*16+tap]*h[3*read+c];
        }
        output[sample]=y*w[49];state->head_pos=(pos+1)%cap;
    }
}
