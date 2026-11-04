# Waveformer NAM engine

Unmodified `nam-core.cjs` is Thomas Hammer's `nam-core-WUsGF8je.js`,
version 0.8.1 (2026-10-15), obtained from https://sym.bios.is/assets/.
The `.cjs` extension permits explicit CommonJS loading by the bundled Node runtime.

The blank v0.21 hosts are from https://sym.bios.is/diy-effects/hosts/ms50gplus/.
The public manifest lists byte-identical hosts for MS-50G+ 1.40 and
MS-70CDR+ 1.20; it does not validate MS-60B+, MS-80IR+ or MS-200D+.
`upstream-host.json` preserves the original licence, notices and validation notes.
All resource digests are recorded in `pins.json` and verified before use.

The adapter in `tools/nam2zoom/waveformer_build.cjs` accepts only explicit
44,100 Hz full A2 Lite captures, runs the upstream quantization/fidelity gates,
and splices one to three images into the 44.1 kHz host in the user's chosen order.
It retains nam2zoom's N2ZBANK filename, N2Z Bank name and PREAMP ID 0x04001787.
The original nam2zoom artwork is retained byte-for-byte in the companion icon;
its original first frame is also embedded in the ZD2. The ICON chunk is resized
to hold that frame without changing any ELF bytes. Validation permits only
model data, labels, selector bounds, identity, icon and CRC changes; the host's DSP instructions and declared DSP
reservation stay unchanged. The 48 kHz host is included only because upstream
`makeEnv`/`processCapture` require both hosts for their checks; the adapter never
builds a 48 kHz effect or offers the slower-rate playback option.

134.5 is a declared reservation, about 49.8% of a 270-unit patch budget.
It is not a measurement of execution time. Upstream's published notes explicitly
say the declared load was not measured. Verify audio and combinations on hardware.

MIT and TI BSD notices accompany the app and every built effect. Original NAM
captures retain their authors' licences. See LICENSE.txt and TI-NOTICE.txt.
