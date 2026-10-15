# Zoom G11: community hardware report

**Status: community-tested with a manual conversion. The nam2zoom app does not
install on the G11.** The app refuses the G11's identity, and it must keep
refusing it until it has a G11 transport (see [Installing](#installing-on-the-g11)).
The file-session sequence the app uses for MS Plus fails on this pedal.

This page records what was needed to run an unmodified N2Z Bank on a Zoom G11,
so the maintainer can decide whether and how to support it.

## Tested setup

| Item | Value |
| :--- | :--- |
| Pedal | Zoom G11, system firmware 2.10 |
| USB-MIDI identity | `7E 00 06 02 52 6E 00 13 00` + `"2.10"` (family `0x006E`, model `0x0013`) |
| MIDI ports (Windows) | `ZOOM G11 0` (in), `ZOOM G11 1` (out) |
| nam2zoom | source checkout at `df62a9d` (2026-10-09), Compact precompiled template |
| Bank | 2 Compact models (Vox AC30 clean / pushed), ESR 0.011 and 0.033 |
| Date | 2026-10-10 |

`release/precompiled` and `dsp/` are unchanged between `df62a9d` and v1.2.3,
so the same recipe should apply to current builds. No v1.2.x build has been
tried on the G11.

### Results on the pedal

- The effect is listed in the AMP category and loads without errors.
- Audio is correct, and the Model selector switches between both models.
  Mix works (0 = dry) and sits on the edit screen, not on a physical knob.
  The other controls were not checked one by one.
- A saved patch containing the bank survives a power cycle, and the pedal
  boots normally with it.
- The G11's DSP meter shows **29%** for the declared load of 150. On this
  pedal, about 514 raw = 100%.
- Real cost is lower than declared. With only NAM instances and one stock IR
  (20%) in a patch, four instances play cleanly and the fifth fails, so each
  costs about 16–20%. This was measured with a G11-specific derivative
  that keeps the N2Z Compact kernel but has different tone controls, not with
  the unmodified N2Z Bank.

## What differs from the MS Plus output

The G11 runs the same C674x code. The `DATA` chunk (code and weights), `PRMJ`,
`PRME`, `TXJ1` and `TXE1` were left **byte-identical**. Only the container
metadata changed. Field names below follow `tools/zd2.py`.

| Field | MS Plus output | G11 version | Why |
| :--- | :--- | :--- | :--- |
| `target` | `0x90` | `0x04` | Stock G11 effects use `0x7`, `0x5`, `0x4`, `0x3` or `0x1`; visible amps use `0x4`. |
| `unknown_header[0]`, `[8]`, `[72]` | `00` | `01`, `80`, `02` | Copied from a stock G11 amp (MS800_AU). Byte `[72]` is the slot count. |
| `unknown_header[4]`, `[40]` | `00` | `01`, `80` | Delay-memory request, as in stock delays and reverbs. Without it the G11 does not pass `instance[3]`, the N2Z guard fails, and the effect mutes the bus (even the dry signal). |
| `group_name` | `PREAMP` | `AMP` | The G11 shows effects only in its own categories. |
| `unknown4` | `00 00 00` | `f8 00 40` | Constant for every stock G11 AMP. |
| `INFO` chunk | category empty | `\0\0\0\0AMPAMP\0…`, keeping `dspload` 150 | Every visible stock G11 effect has its category text here. |
| `ICON` chunk | 1261 bytes | 302-byte BMP (starts with `BM`) | Every visible stock G11 effect embeds a BMP icon. |
| trailer (16 bytes) | zeros | copied from the stock amp | Not isolated; copied to match stock files. |
| `checksum` | — | recomputed | `crc32(data[12:-16]) ^ 0xFFFFFFFF`, same as `compute_checksum`. |

`name` was also changed to `NAM A2`. The effect ID `0x04001787` was kept.

This set of changes is sufficient. With the MS Plus `INFO`, `PREAMP` group and
icon, the effect was in the effect list but hidden in the UI. Which of those
three is needed on its own has not been isolated. The delay-memory flags are
required on their own: without them the effect is silent.

The donor fields (`INFO`, `ICON`, trailer, header bytes) were copied from a
stock effect in the user's own G11 firmware. Stock Zoom files are not
redistributed here.

## Installing on the G11

The G11 uses the same `F0 52 00 6E … F7` SysEx header and `60 xx` file
commands, but its file session differs from MS Plus. The sequences below were
captured with USBPcap while Guitar Lab installed a stock effect, and then
reproduced.

The writer the app uses (`stomphacks/tools-pedal/file_session.py`, the
zoomzt2 vocabulary) fails on the G11. It reads with
`60 22 14 2F 60 00 0C 00 04 00 00 00`, closes with a fixed
`60 21 40 00 00 00 00`, writes with `60 23 40 00 00 00 00 …`, and never sends
`57`. On the G11, these reads leak handles. Writing a new file without `57`
creates a 0-byte file that never acknowledges its blocks.

- Before writing, send `52`, then `50`, then **`57`**. Without `57`, open-for-write
  creates a 0-byte file and never replies.
- Every open (`60 20 01` write, `60 20 02` read) replies with a **5-byte handle**
  at `data[10:15]`. Chunks use it (`60 22 <handle> 78 05 00 00 00`,
  `60 23 <handle> <len> …`, each followed by `60 05 00`).
- Close each file with `60 21 <handle>`.
  Older-style reads and closes (`60 22 14 2f 60 …`, `60 21 40 00 00 00 00`)
  leak handles. After about 150 opens the file system stops responding, the
  screens go blank, and only a power cycle recovers the pedal.
- End with `60 09`, wait for the delayed `60 05 00` (~1.8 s), then `53` and wait
  for its reply (~6.3 s, effects reload), then `51`. If the session ends early
  after `57`, the next session can leave the pedal deaf on USB until power-off.
- Icons are `.svg` files written to the `EffectIcons` folder with the same
  write command (the G11 does not use `.ZIC`). All visible stock effects have
  one; stock effects without one are hidden. Opening an `.svg` for reading never replies, so do not read
  one back.
- `FLST_SEQ.ZT2` must be rewritten with the new effect entry, as for MS Plus.
  Guitar Lab may rewrite this list later and hide the effect.
- A partial or corrupt `.ZD2` left on the pedal makes boot ("Loading...") very
  slow. Delete it before restarting.

While PC mode is on (`52`), every screen shows "MISSING EFFECT NOT FOUND".
This is normal and clears after `53`.

## Not yet verified

- Any v1.2.x N2Z Bank build on the G11 (template and kernel are unchanged).
- Banks with more than two models.
- Long-duration stability and full-patch stress tests.
- Measured DSP cycle cost (only the admission meter and the four-instance test
  above).
- Behavior after a Guitar Lab session that rewrites `FLST_SEQ.ZT2`.

## Recovery

If the G11 stops booting, reflash the official firmware. Put `G11.ZUF` (from
Zoom) on a FAT32 USB stick and insert it in the USB HOST port. Hold the two
left round footswitches while powering on until "Starting..." appears.
This takes about 10 minutes; do not power off.
For blank screens or a pedal that ignores USB, power-cycle it (wait 5 s).
