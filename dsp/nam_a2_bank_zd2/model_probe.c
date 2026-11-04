/* Private model-state telemetry, not a production effect or a tuner fix.
 * The ordinary host runs unchanged; report tones replace its final output.
 * No clock reads, writable globals, history-tail allocation or UI writes. */
#include "sh_params.h"
#undef SH_AUDIO_FN
#define SH_AUDIO_FN n2z_model_probe_audio
#include "bank_effect.c"
#undef SH_AUDIO_FN
#define SH_AUDIO_FN Fx_SFX_N2ZBank
#include "model_probe_config.h"
#ifndef CTX_GET_PARAM
#define CTX_GET_PARAM 40u
#define UI_PARAM_MODEL 2
typedef int (*GetParamFn)(void*,int);
#endif

#define PROBE_MAGIC 0x4d505231u
#define PROBE_SYNC 0x4e324d50u
#define PROBE_WORDS 19u
#define PROBE_PERIOD (((PROBE_WORDS*32u*882u+33075u+SH_FRAMES-1u)/SH_FRAMES)*SH_FRAMES)
typedef struct {
    EffectState net;
    uint32_t magic, sample, phase;
    uint32_t packet[PROBE_WORDS];
} ModelProbe;
typedef char model_probe_fits[(sizeof(ModelProbe)<=SH_STATE_BYTES)?1:-1];

static uint32_t float_word(float value) {
    union { float f; uint32_t u; } bits;
    bits.f=value; return bits.u;
}

void SH_AUDIO_FN(void **instance, void **ctx) {
    ModelProbe *probe;
    float *coeff, *bus;
    uint32_t capture, i;
    if(!instance || !ctx || !ctx[SH_CTX_EFF] || !instance[1] || !instance[2]) return;
    probe=(ModelProbe*)instance[2];
    if(((const uint32_t*)probe)[SH_STATE_GUARD_WORD]!=SH_STATE_GUARD) return;
    coeff=(float*)instance[1]; bus=(float*)ctx[SH_CTX_EFF];
    if(probe->magic!=PROBE_MAGIC || probe->sample>=PROBE_PERIOD || probe->phase>=64u) {
        probe->sample=probe->phase=0u;
        for(i=0;i<PROBE_WORDS;++i) probe->packet[i]=0u;
        probe->magic=PROBE_MAGIC;
    }
    capture=probe->sample==0u;
    if(capture) {
        uint32_t flags=0u;
        uintptr_t address=(uintptr_t)instance[3];
        probe->packet[0]=PROBE_SYNC; probe->packet[1]=1u;
        ++probe->packet[2];
#ifdef N2Z_COMPACT_EFFECT
        flags|=4u;
#endif
        if(probe->net.initialized==INITIALIZED) flags|=8u;
        probe->packet[4]=0xfffffffeu;
        probe->packet[17]=0xfffffffeu;
        if(instance[0] && ctx[CTX_GET_PARAM]) {
            flags|=1u;
            probe->packet[4]=(uint32_t)((GetParamFn)ctx[CTX_GET_PARAM])(instance[0],UI_PARAM_MODEL);
            probe->packet[17]=(uint32_t)((GetParamFn)ctx[CTX_GET_PARAM])(instance[0],0);
        }
        probe->packet[5]=float_word(coeff[SH_PARAM_MODEL]);
        probe->packet[6]=probe->net.active_model;
        probe->packet[7]=probe->net.initialized;
        probe->packet[8]=float_word(coeff[SH_COEFF_BYPASS]);
        probe->packet[9]=float_word(coeff[SH_PARAM_MIX]);
        probe->packet[10]=probe->packet[11]=0u;
        if(address && !(address&3u)) {
            const uint32_t *descriptor=(const uint32_t*)address;
            flags|=2u;
            probe->packet[10]=descriptor[0]; probe->packet[11]=descriptor[2];
        }
        probe->packet[3]=flags;
        probe->packet[16]=MODEL_PROBE_TAG;
    }
    n2z_model_probe_audio(instance,ctx);
    if(capture) {
        uint32_t crc=0xffffffffu, j, byte;
        probe->packet[12]=float_word(coeff[SH_PARAM_MODEL]);
        probe->packet[13]=probe->net.active_model;
        probe->packet[14]=probe->net.clear_count;
        probe->packet[15]=probe->net.warm_count;
        for(i=0;i<PROBE_WORDS-1u;++i) {
            uint32_t word=probe->packet[i];
            for(byte=0;byte<4u;++byte) {
                crc^=word&255u; word>>=8;
                for(j=0;j<8u;++j) crc=(crc>>1)^(0xedb88320u&(0u-(crc&1u)));
            }
        }
        probe->packet[18]=crc^0xffffffffu;
    }
    for(i=0;i<SH_FRAMES;++i) {
        uint32_t slot=probe->sample/882u, offset=probe->sample%882u;
        float value=0.0f;
        if(slot<PROBE_WORDS*32u && offset<441u) {
            uint32_t bit=(probe->packet[slot>>5]>>(31u-(slot&31u)))&1u;
            int triangle=probe->phase<32u?(int)probe->phase:64-(int)probe->phase;
            value=((float)triangle-16.0f)*0.0025f;
            probe->phase=(probe->phase+1u+bit)&63u;
        } else probe->phase=0u;
        bus[i]=bus[i+SH_CH_B_OFFSET]=value;
        if(++probe->sample==PROBE_PERIOD) probe->sample=0u;
    }
}
