"""Decode a sequence of tuner/model-state snapshots from a private probe WAV."""
import argparse
import json
from pathlib import Path
import struct
import zlib
import numpy as np
import soundfile as sf
from decode_lite_timing import channel_packets

SYNC=0x4e324d50
WORDS=19
KEYS=('sync','version','sequence','flags','ui_model','coefficient_before',
      'active_before','initialized_before','bypass','mix','arena_base','arena_span',
      'coefficient_after','active_after','clear_count','warm_count','model_tag','ui_on','crc32')

def valid_packets(bits):
    found=[]; start=bits.find(f'{SYNC:032b}')
    while start>=0:
        packet=bits[start:start+WORDS*32]
        if len(packet)==WORDS*32 and 'x' not in packet:
            words=tuple(int(packet[i:i+32],2) for i in range(0,len(packet),32))
            if words[1]==1 and zlib.crc32(struct.pack('<18I',*words[:-1]))==words[-1]:found.append(words)
        start=bits.find(f'{SYNC:032b}',start+1)
    return found

def interpret(packet):
    report=dict(zip(KEYS,packet))
    for key in ('coefficient_before','coefficient_after','bypass','mix'):
        word=report[key]; value=struct.unpack('<f',struct.pack('<I',word))[0]
        report[key]=value if np.isfinite(value) else f'nonfinite:0x{word:08x}'
    for key in ('ui_model','ui_on'):
        if report[key]>=0x80000000:report[key]-=0x100000000
    report['mode']='compact' if report['flags']&4 else 'full'
    report['parameter_service_available']=bool(report['flags']&1)
    return report

def decode(path):
    data,rate=sf.read(str(path),dtype='float64',always_2d=True)
    if not 8000<=rate<=192000 or not np.isfinite(data).all():raise ValueError('Invalid WAV')
    streams=[channel_packets(data[:,i],rate,valid_packets) for i in range(data.shape[1])]
    packets=max(streams,key=len)
    if not packets:raise ValueError('No complete CRC-valid model snapshots; record the direct probe tones without other effects')
    reports=[interpret(packet) for packet in packets]
    if len({report['model_tag'] for report in reports})!=1:raise ValueError('Recording mixes different probe kits')
    return {'format':'nam2zoom.model-probe.v1','recording':str(Path(path).resolve()),
            'sample_rate':rate,'clipped':bool(np.abs(data).max()>=.999),
            'reports':reports,'note':'Ordered snapshots from one channel; not timing or an audio-quality measurement.'}

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('wav',type=Path)
    args=parser.parse_args()
    result=decode(args.wav)
    for report in result['reports']:
        print(f"{report['mode']} #{report['sequence']}: UI model {report['ui_model']}, coefficient {report['coefficient_before']} -> {report['coefficient_after']}, active {report['active_before']} -> {report['active_after']}, arena 0x{report['arena_base']:08x}")
    target=args.wav.with_suffix('.model-probe.json')
    target.write_text(json.dumps(result,indent=2)+'\n');print(f'Saved {target}')

if __name__=='__main__':main()
