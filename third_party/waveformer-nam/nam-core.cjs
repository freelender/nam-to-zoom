/* SPDX-License-Identifier: MIT
 * Copyright (c) 2026 Thomas Hammer
 *
 * nam-core.js — the NAM capture builder's computational core (desk prototype).
 *
 * A JavaScript port of the Python reference pipeline:
 *   nam_ref.py   (parse_a2, quantize, forward_float, forward_kernel,
 *                 rescale_a2; the output level: warm_pluck, level_db,
 *                 level_choose, level_oscale)
 *   nam_pack.py  (pack, prepare_rexp, choose_ring_exp, blank_info,
 *                 splice_bytes, set_identity, corpus_one's gate (_fid),
 *                 prepare_level, level_record, capture_identity,
 *                 capture_name)
 *   nam_icon.py  (the icon composer: render, lay_plan, includes_cab)
 *   nam_set.py   (an effect of SEVERAL captures: set_key, set_identity,
 *                 set_labels, check_labels, set_name, check_image,
 *                 build_blob, host_regions, splice_set, read_set; the
 *                 selection: folder_files, check_selection, final_labels,
 *                 final_name)
 * following the splice specification, nam-splice-spec.md (blob layout 6,
 * the v0.12 release hosts), and for several captures in one effect
 * multi-profile-contract.md (blob layout 7, the v0.20 release hosts). The
 * output must be BYTE-IDENTICAL to the reference; run_vectors.js proves it
 * against the vector files.
 *
 * TWO ENVIRONMENTS (0.7.1). makeEnv takes either pair of pinned blank hosts
 * and nothing else: the two one-capture hosts (layout 6: processCapture,
 * then buildOutputs, one effect per capture) or the two hosts that take
 * several captures (layout 7: processCapture, then buildSetOutputs, for one
 * capture and for several). processCapture runs the same checks, the same
 * chooser and the same gate in both; only its container check differs (a
 * splice into the hosts it was given). The layout-7 environment needs no
 * layout-6 host.
 *
 * The output level (spec §5.8, ruled 2026-10-02: "we always measure"): every
 * capture is level-matched at build time. processCapture MEASURES the level
 * on the warm pluck and writes the 0.5 dB step's `oscale` word; there is no
 * user switch. opts.fixedLevelSteps (tests only) pins the step instead;
 * 0 = oscale 1.0 = the bytes from before the rule.
 *
 * File/memory only: no MIDI, no network, no DOM. Runs as a classic browser
 * script (defines window.NAMB) and as a Node module (module.exports), so
 * the same code is tested headless and runs in the page.
 */
(function (root) {
  'use strict';

  var VERSION = '0.8.1 (2026-10-15, desk prototype)';

  // ---- the A2 fixed shape (nam_ref.py) --------------------------------
  var A2_KERNELS = [6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 15, 15, 6, 6, 6, 6, 6, 6, 6];
  var A2_DILATIONS = [1, 3, 7, 17, 41, 101, 239, 1, 3, 7, 17, 41, 101, 239,
    1, 13, 1, 3, 7, 17, 41, 101, 239];
  var HEAD_K = 16;
  var SLOPE = 0.01;
  var NL = 23;
  var C = 3;
  var N_WEIGHTS = 1871;

  // ---- kernel constants (host-splice-spec §2) --------------------------
  var AQ = 10, CQ = 13;
  var MAGIC = 0x4E414D31;
  var HDR = 8, DW = 7, MIR = 16, RBIAS = 0x4000, RALIGN = 128;
  var BLOB_WORDS = 12288;
  var ARENA_GRANT = 705600;
  var RING_LO = -0x4000, RING_HI = 0x7F7F - 0x4000;
  var RING_LIMIT = (0x7F7F - RBIAS) / 1024.0;   // 15.87
  var Z_LIMIT = 32767 / 1024.0;                 // 32.0
  var RECH_LIMIT = 1.9;
  var FIXD_LIMIT = 8.0;
  var LAYOUT_REXP = 6;
  var MARGIN_DB = 1.0;                          // spec §5.6: margin_db = 1
  var GATE_ESR = 0.01;                          // spec §5.5

  // ---- the output level (spec §5.8; nam_ref.LEVEL_*) --------------------
  // Captures come out up to 31 dB apart on a guitar. The blob's `oscale`
  // word (header word 3) level-matches them:
  //   x_ref  = warmPluck(pluck)                the level signal
  //   L      = levelDb(float model on x_ref)   dB RMS
  //   n      = roundHalfEven((-18 - L) / 0.5)  the LEVEL STEP, clamped -36..+36
  //   while n > -36 and ymax_probe * OSCALE(n) * 1.5 > 4.0:  n -= 1   (peak guard)
  //   oscale = LEVEL_OSCALE_BITS[n + 36]       a TABLE, never Math.pow
  var LEVEL_RULE = 'warm-pluck-rms-v1';
  var LEVEL_TARGET_DB = -18.0;                  // the NAM plugin's "Normalized" target
  var LEVEL_STEP_DB = 0.5;
  var LEVEL_MAX_STEPS = 36;                     // the clamp: -36..+36 steps = -18..+18 dB
  var LEVEL_VOL_MAX = 1.5;                      // the stock VOL curve at 100 (80 is unity)
  var LEVEL_GUARD_CEILING = 4.0;                // the peak guard: 6 dB under Fix D at VOL 100
  var LEVEL_PEAK = 0.7;                         // the warm pluck's peak (the pluck's own)
  // The two one-pole coefficients, 1 - exp(-2 pi f / 44100) for f = 70 and
  // 300 Hz, as LITERALS (IEEE bits 3F8452E608DD4780 and 3FA56C55FE5FC360):
  // Math.exp may differ in the last bit between engines, and these two
  // numbers decide every sample of the level signal.
  var LEVEL_HP_K = 0.009923741479415105;
  var LEVEL_LP_K = 0.04184216241981775;
  // sha256 of the two signals as 352,800 little-endian float64 each: the
  // gate's pluck (data bundle: signals.pluck) and the warm pluck made from
  // it. makeEnv refuses a bundle whose signals are not these.
  var LEVEL_PLUCK_SHA256 = '520fbba8551f1038106ac4d2be3c272433f15b7b29294bd3f74d414e8996ffd7';
  var LEVEL_WARM_SHA256 = '52be86bbffd25511057590f29382d67dd577c6e565b4933360069a779666b7f4';
  // oscale as IEEE float32 bits for step n = -36 .. +36, index n + 36: the
  // float32 nearest 10^(n/40). The 73 words a build can ever write.
  // NORMATIVE (spec §5.8 step 4): take the word from here.
  var LEVEL_OSCALE_BITS = new Uint32Array([
    0x3E00E9F9, 0x3E088D77, 0x3E10A4D3, 0x3E1936EC, 0x3E224B06, 0x3E2BE8D7,
    0x3E361887, 0x3E40E2BB, 0x3E4C509B, 0x3E586BD9, 0x3E653EBB, 0x3E72D424,
    0x3E809BCC, 0x3E883AA8, 0x3E904D1C, 0x3E98DA02, 0x3EA1E89B, 0x3EAB8097,
    0x3EB5AA1A, 0x3EC06DC3, 0x3ECBD4B4, 0x3ED7E89B, 0x3EE4B3B6, 0x3EF240E2,
    0x3F004DCE, 0x3F07E80B, 0x3F0FF59A, 0x3F187D50, 0x3F21866C, 0x3F2B1896,
    0x3F353BEF, 0x3F3FF911, 0x3F4B5918, 0x3F5765AC, 0x3F642905, 0x3F71ADF9,
    0x3F800000,
    0x3F8795A0, 0x3F8F9E4D, 0x3F9820D7, 0x3FA12478, 0x3FAAB0D5, 0x3FB4CE08,
    0x3FBF84A6, 0x3FCADDC8, 0x3FD6E30D, 0x3FE39EA9, 0x3FF11B6A, 0x3FFF64C1,
    0x40074368, 0x400F4735, 0x4017C496, 0x4020C2BF, 0x402A4952, 0x40346063,
    0x403F1082, 0x404A62C2, 0x405660BD, 0x406314A0, 0x40708933, 0x407EC9E1,
    0x4086F161, 0x408EF052, 0x4097688D, 0x40A06142, 0x40A9E20E, 0x40B3F300,
    0x40BE9CA5, 0x40C9E807, 0x40D5DEBC, 0x40E28AEB, 0x40EFF755, 0x40FE2F5E]);
  // the same 73 words read as float32 VALUES (what the kernel multiplies by)
  var LEVEL_OSCALE = new Float32Array(LEVEL_OSCALE_BITS.buffer);

  // ---- the ZD2 container (spec §7) -------------------------------------
  var ZD2_HEADER = 128, ZD2_TRAILER = 16;

  // ---- identity (spec §9, ruled 2026-10-01; nam_pack.capture_identity) ---
  var GROUP_PREAMP = 0x04;
  var GROUP_NAME = 'PREAMP';
  var ID_BAND_LO = 0x1400, ID_BAND_SIZE = 0x400;   // NAM user captures 0x1400-0x17FF (ruled 2026-09-30)
  // the pedal filename: the writer's author prefix 'WF' + the tool letter 'N'
  // + 5 hash characters (RULED 2026-10-11, replacing 'NM' + 6; 0.8.0). The 5
  // characters are the top 25 bits of uint32_be(H[4:8]), so they equal the
  // first 5 of the old 6-character suffix (NM7W0DY5 -> WFN7W0DY). A name is a
  // generated capture file only if FILE_RE matches it IN FULL: never test the
  // 'WFN' prefix alone (the blank host files WFNAM48 / WFNAM44 share it).
  var FILE_PREFIX = 'WFN';
  var FILE_CHARS = 5;
  var FILE_ALPHABET = '0123456789ABCDEFGHJKMNPQRSTVWXYZ';   // Crockford base 32: no I, L, O, U
  var FILE_RE = /^WFN[0-9A-HJKMNP-TV-Z]{5}$/;
  var NAME_MAX = 11;

  // ---- the icon (nam_icon.py; the icon vectors) --------------------------
  // The icon data both sides compose from, pinned by the sha256 of its
  // canonical JSON. Re-freezing the data (nam_icon.py vectors --refreeze)
  // moves this pin, the one in tools/make_data.py and every icon vector.
  var ICON_DATA_FORMAT = 'nam-icon-data/2';
  var ICON_DATA_SHA256 = 'c0f5884bbcdef363f782fd26c15127767579efa117fb78c15d856f41623bf810';
  var ICON_CAB_SUFFIX = '+cab';                 // the art key of a "+CAB" picture
  var ICON_SEPARATORS = '_-/.+&,:';
  var ICON_COST_SEPARATOR = 2, ICON_COST_CHANGE = 4, ICON_COST_WORD = 12;

  // The two blank hosts this prototype accepts, pinned by sha256 (spec §2).
  // makeEnv refuses anything else. They are the v0.12 RELEASE hosts
  // (WFNAMA2 0x04002130, WFNAMR48 0x04002140) since 2026-10-03.
  // hostKind = the reference's host kind, the string the id hash covers.
  // imageKB = the loaded image in thousands of bytes (59,928 B / 80,480 B).
  var HOSTS = {
    a2: {
      key: 'a2', label: 'NAM 44.1k', kind: 0, hostKind: 'nam-a2', rs48: false, dspload: 134.5,
      sha256: 'd665822fc1d087efef57dcb905428c27f377ddebd01fe9e33dc92290b05b822a',
      imageKB: 59.9
    },
    r48: {
      key: 'r48', label: 'NAM 48k', kind: 1, hostKind: 'nam-48k', rs48: true, dspload: 150,
      sha256: 'b6a1b985ababf1450497c5d42f4fabcca60ec932311fb0257262e11bc5e4a0e8',
      imageKB: 80.5
    }
  };
  // The two blank hosts that take SEVERAL captures (blob layout 7), pinned
  // the same way: the v0.21 RELEASE hosts (WFNAM44 0x04002151, WFNAM48
  // 0x04002150; multi-profile-contract.md section 9, rows 26 and 34). makeEnv
  // accepts both hosts of HOSTS or both of these, never one of each. What a
  // host kind is (label, kind, hostKind, rs48, dspload) is HOSTS' in both.
  // imageKB = the loaded image in thousands of bytes (49,976 B / 60,192 B).
  var SET_HOSTS = {
    a2: {
      key: 'a2', file: 'WFNAM44.ZD2',
      sha256: '38823ba9ec668d71bf69a122c7b11e5784d51fcc19cef6f0d96eaf24e26967b6',
      imageKB: 50.0
    },
    r48: {
      key: 'r48', file: 'WFNAM48.ZD2',
      sha256: '91377b8262aea87db66ba492d1163f4979ef17d18feffa29b4c84d2e7b6324e3',
      imageKB: 60.2
    }
  };
  // the label of the one-capture splice processCapture makes as its container
  // check in the layout-7 environment (a test article, never handed over)
  var SET_CHECK_LABEL = 'CHECK';
  var LOAD_LIMIT_PROVEN_KB = 80.5;   // spec §11: proven 80.5 KB, 133 KB froze pedal #1

  // =====================================================================
  // small numeric helpers
  // =====================================================================
  var _f32buf = new DataView(new ArrayBuffer(4));
  function f2u(f) {                        // float32 bits of f
    _f32buf.setFloat32(0, f, true);
    return _f32buf.getUint32(0, true);
  }
  function u2f(u) {                        // the float32 a word's bits read as
    _f32buf.setUint32(0, u, true);
    return _f32buf.getFloat32(0, true);
  }
  function u32(v) { return v >>> 0; }      // two's complement word (exact for |v| < 2^53)
  function roundHalfEven(x) {              // numpy np.round / Python round()
    var f = Math.floor(x);
    var d = x - f;                         // exact for |x| < 2^52
    if (d < 0.5) return f;
    if (d > 0.5) return f + 1;
    return (f % 2 === 0) ? f : f + 1;
  }
  function floorShift(v, s) {             // arithmetic >> on an integer-valued double
    return s === 0 ? v : Math.floor(v / Math.pow(2, s));
  }
  function sat16(v) { return v > 32767 ? 32767 : (v < -32768 ? -32768 : v); }
  function db(v) { return v > 0 ? 20 * Math.log10(v) : -Infinity; }
  function pair(lo, hi) {
    if (lo < -32768 || lo > 32767 || hi < -32768 || hi > 32767) {
      throw new PackError('packed value ' + (lo < -32768 || lo > 32767 ? lo : hi) + ' does not fit int16');
    }
    return u32(((hi & 0xFFFF) << 16) | (lo & 0xFFFF));
  }
  function PackError(msg) { this.name = 'PackError'; this.message = msg; this.stack = (new Error(msg)).stack; }
  PackError.prototype = Object.create(Error.prototype);

  var noYield = function () { return null; };

  // =====================================================================
  // SHA-256 (pure JS: crypto.subtle is not guaranteed on file:// pages)
  // =====================================================================
  var SHA_K = new Uint32Array([
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
    0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
    0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
    0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
    0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
    0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
    0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
    0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2]);
  function sha256Hex(bytes) {
    var n = bytes.length;
    var total = ((n + 9 + 63) >> 6) << 6;
    var buf = new Uint8Array(total);
    buf.set(bytes);
    buf[n] = 0x80;
    var bits = n * 8;
    var dv = new DataView(buf.buffer);
    dv.setUint32(total - 4, bits >>> 0, false);
    dv.setUint32(total - 8, Math.floor(bits / 4294967296) >>> 0, false);
    var H = new Uint32Array([0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a,
      0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19]);
    var W = new Uint32Array(64);
    for (var off = 0; off < total; off += 64) {
      for (var i = 0; i < 16; i++) W[i] = dv.getUint32(off + 4 * i, false);
      for (i = 16; i < 64; i++) {
        var w15 = W[i - 15], w2 = W[i - 2];
        var s0 = ((w15 >>> 7) | (w15 << 25)) ^ ((w15 >>> 18) | (w15 << 14)) ^ (w15 >>> 3);
        var s1 = ((w2 >>> 17) | (w2 << 15)) ^ ((w2 >>> 19) | (w2 << 13)) ^ (w2 >>> 10);
        W[i] = (W[i - 16] + s0 + W[i - 7] + s1) >>> 0;
      }
      var a = H[0], b = H[1], c = H[2], d = H[3], e = H[4], f = H[5], g = H[6], h = H[7];
      for (i = 0; i < 64; i++) {
        var S1 = ((e >>> 6) | (e << 26)) ^ ((e >>> 11) | (e << 21)) ^ ((e >>> 25) | (e << 7));
        var ch = (e & f) ^ (~e & g);
        var t1 = (h + S1 + ch + SHA_K[i] + W[i]) >>> 0;
        var S0 = ((a >>> 2) | (a << 30)) ^ ((a >>> 13) | (a << 19)) ^ ((a >>> 22) | (a << 10));
        var maj = (a & b) ^ (a & c) ^ (b & c);
        var t2 = (S0 + maj) >>> 0;
        h = g; g = f; f = e; e = (d + t1) >>> 0; d = c; c = b; b = a; a = (t1 + t2) >>> 0;
      }
      H[0] = (H[0] + a) >>> 0; H[1] = (H[1] + b) >>> 0; H[2] = (H[2] + c) >>> 0; H[3] = (H[3] + d) >>> 0;
      H[4] = (H[4] + e) >>> 0; H[5] = (H[5] + f) >>> 0; H[6] = (H[6] + g) >>> 0; H[7] = (H[7] + h) >>> 0;
    }
    var out = '';
    for (i = 0; i < 8; i++) out += ('00000000' + H[i].toString(16)).slice(-8);
    return out;
  }

  // =====================================================================
  // CRC-32 (zlib) and the ZD2 container (nam_pack.py "splice" section)
  // =====================================================================
  var CRC_TABLE = (function () {
    var t = new Uint32Array(256);
    for (var n = 0; n < 256; n++) {
      var c = n;
      for (var k = 0; k < 8; k++) c = (c & 1) ? (0xEDB88320 ^ (c >>> 1)) : (c >>> 1);
      t[n] = c >>> 0;
    }
    return t;
  })();
  function crc32(bytes, start, end) {
    var c = 0xFFFFFFFF;
    for (var i = start; i < end; i++) c = CRC_TABLE[(c ^ bytes[i]) & 0xFF] ^ (c >>> 8);
    return (c ^ 0xFFFFFFFF) >>> 0;
  }
  function zd2Crc(raw) {                  // crc32(raw[12 : len-16]) XOR 0xFFFFFFFF
    return (crc32(raw, 12, raw.length - ZD2_TRAILER) ^ 0xFFFFFFFF) >>> 0;
  }
  function rd32(raw, off) {
    return (raw[off] | (raw[off + 1] << 8) | (raw[off + 2] << 16) | (raw[off + 3] << 24)) >>> 0;
  }
  function wr32(raw, off, v) {
    raw[off] = v & 0xFF; raw[off + 1] = (v >>> 8) & 0xFF;
    raw[off + 2] = (v >>> 16) & 0xFF; raw[off + 3] = (v >>> 24) & 0xFF;
  }
  function zd2CheckEnvelope(raw, what) {
    if (raw.length < ZD2_HEADER + ZD2_TRAILER + 8) throw new Error(what + ': too short to be a ZD2');
    if (raw[0] !== 0x5A || raw[1] !== 0x44 || raw[2] !== 0x4C || raw[3] !== 0x46) throw new Error(what + ': bad magic');
    if (rd32(raw, 4) !== 120) throw new Error(what + ': header @4 is not the constant 120');
    if (rd32(raw, 8) !== zd2Crc(raw)) throw new Error(what + ': header CRC does not validate');
  }
  function zd2Chunks(raw) {
    var end = raw.length - ZD2_TRAILER;
    var off = ZD2_HEADER, out = [];
    while (off < end) {
      if (off + 8 > end) throw new Error('chunk header overruns the trailer');
      var tag = String.fromCharCode(raw[off], raw[off + 1], raw[off + 2], raw[off + 3]);
      var ln = rd32(raw, off + 4);
      if (off + 8 + ln > end) throw new Error('chunk ' + tag + ' overruns the trailer');
      out.push({ tag: tag, start: off + 8, len: ln });
      off += 8 + ln;
    }
    if (off !== end) throw new Error('chunks do not tile to the trailer');
    return out;
  }
  // start, end (optional): look inside raw[start:end] only, as Python's
  // bytes.count(sub, start, end) / bytes.find(sub, start, end) do
  function countPattern(raw, pat, start, end) {   // bytes.count(): non-overlapping occurrences
    var n = 0, i = start == null ? 0 : start, L = pat.length;
    var lim = end == null ? raw.length : end;
    outer:
    while (i <= lim - L) {
      for (var j = 0; j < L; j++) {
        if (raw[i + j] !== pat[j]) { i++; continue outer; }
      }
      n++; i += L;
    }
    return n;
  }
  function findPattern(raw, pat, start, end) {
    var lim = end == null ? raw.length : end;
    outer:
    for (var i = start == null ? 0 : start; i <= lim - pat.length; i++) {
      for (var j = 0; j < pat.length; j++) if (raw[i + j] !== pat[j]) continue outer;
      return i;
    }
    return -1;
  }
  var MAGIC_BYTES = [0x31, 0x4D, 0x41, 0x4E];

  function blankInfo(raw) {                // spec §7.2, all fail-closed
    var data = zd2Chunks(raw).filter(function (c) { return c.tag === 'DATA'; });
    if (data.length !== 1) throw new Error('host must have exactly one DATA chunk');
    var ds = data[0].start, dl = data[0].len;
    var cnt = countPattern(raw, MAGIC_BYTES);
    if (cnt !== 1) throw new Error('host must contain the NAM magic exactly once (found ' + cnt + ')');
    var off = findPattern(raw, MAGIC_BYTES);
    if (!(ds <= off && off + 20 <= ds + dl)) throw new Error('NAM magic is not inside the DATA chunk');
    if ((off - ds) % 4) throw new Error('NAM magic is not word-aligned in the ELF');
    var nl = rd32(raw, off + 4), reserved = rd32(raw, off + 8), ver = rd32(raw, off + 12), kind = rd32(raw, off + 16);
    if (nl !== 0) throw new Error('host already holds a capture (NL ' + nl + '); splice into a BLANK host only');
    if (ver !== 5 && ver !== 6) throw new Error('host blob layout version ' + ver + ', this tool writes 5 or 6');
    if (reserved !== BLOB_WORDS) throw new Error('host reserves ' + reserved + ' words, the kernel is built for ' + BLOB_WORDS);
    if (off + reserved * 4 > ds + dl) throw new Error('reservation overruns the DATA chunk');
    var sent = ver === 5 ? 16 : 20;
    if (ver === 6 && kind !== 0 && kind !== 1) throw new Error('layout-6 host kind ' + kind + ' is not 0 (plain) or 1 (rs48)');
    for (var i = off + sent; i < off + reserved * 4; i++) {
      if (raw[i]) throw new Error('reservation is not zero beyond the sentinel');
    }
    return { off: off, reserved: reserved, layout: ver, kind: ver === 6 ? (kind === 1 ? 'rs48' : 'plain') : null };
  }

  function blobExponents(words) {
    var nl = words[1], e = [];
    for (var l = 0; l < nl; l++) e.push((words[HDR + l * DW + 3] >>> 8) & 15);
    return e;
  }

  function spliceBytes(host, words, used) {
    zd2CheckEnvelope(host, 'host');
    var b = blankInfo(host);
    var off = b.off, reserved = b.reserved;
    if (b.layout === 5 && blobExponents(words).some(function (v) { return v; })) {
      throw new Error('the image carries ring exponents, and this host is blob layout 5: it would play SILENCE');
    }
    if (b.kind === 'rs48' && words[5] !== 32) {
      throw new Error('this is the 48k (NAM_RS48) host and the image is the plain layout: it would play SILENCE');
    }
    if (used > reserved) throw new Error('packed blob (' + used + ' words) exceeds the reservation (' + reserved + ')');
    var out = new Uint8Array(host);
    for (var i = 0; i < reserved; i++) wr32(out, off + 4 * i, words[i] >>> 0);
    wr32(out, 8, zd2Crc(out));
    // verify what we are about to hand over (spec §7.3 step 5)
    zd2CheckEnvelope(out, 'output');
    zd2Chunks(out);
    if (countPattern(out, MAGIC_BYTES) !== 1) throw new Error('output does not contain the NAM magic exactly once');
    for (i = 0; i < reserved; i++) {
      if (rd32(out, off + 4 * i) !== (words[i] >>> 0)) throw new Error('readback of the spliced region differs');
    }
    for (i = 0; i < 8; i++) if (out[i] !== host[i]) throw new Error('header prefix changed');
    for (i = out.length - ZD2_TRAILER; i < out.length; i++) if (out[i] !== host[i]) throw new Error('trailer changed');
    for (i = 12; i < off; i++) if (out[i] !== host[i]) throw new Error('bytes outside the blob region changed');
    for (i = off + reserved * 4; i < out.length; i++) if (out[i] !== host[i]) throw new Error('bytes outside the blob region changed');
    return out;
  }

  function asciiOk(s, lo, hi) {
    if (s.length < lo || s.length > hi) return false;
    for (var i = 0; i < s.length; i++) {
      var c = s.charCodeAt(i);
      if (c < 0x20 || c >= 0x7F) return false;
    }
    return true;
  }

  // nam_pack.set_identity: @89 version, @95 group, @96 id, @100 name, @111 group name
  function setIdentity(raw, o) {
    var out = new Uint8Array(raw);
    var i;
    if (o.group != null) {
      if (!(o.group >= 1 && o.group <= 0x0F)) throw new Error('group byte out of range 1..15');
      if (o.id == null) throw new Error('changing the group needs a new id (its top byte = the group)');
      out[95] = o.group;
    }
    if (o.groupName != null) {
      if (!asciiOk(o.groupName, 1, 10)) throw new Error('group name must be 1-10 printable ASCII characters');
      for (i = 0; i < 11; i++) out[111 + i] = i < o.groupName.length ? o.groupName.charCodeAt(i) : 0;
    }
    if (o.id != null) {
      if (!(o.id >= 0 && o.id <= 0xFFFFFFFF)) throw new Error('id out of range');
      if ((o.id >>> 24) !== out[95]) throw new Error('id top byte must equal the group byte @95');
      wr32(out, 96, o.id >>> 0);
    }
    if (o.name != null) {
      if (!asciiOk(o.name, 1, 11)) throw new Error('name must be 1-11 printable ASCII characters');
      for (i = 0; i < 11; i++) out[100 + i] = i < o.name.length ? o.name.charCodeAt(i) : 0;
    }
    if (o.version != null) {
      if (o.version.length !== 4 || !asciiOk(o.version, 4, 4)) throw new Error('version must be exactly 4 printable ASCII characters');
      for (i = 0; i < 4; i++) out[89 + i] = o.version.charCodeAt(i);
    }
    wr32(out, 8, zd2Crc(out));
    zd2CheckEnvelope(out, 're-identified output');
    zd2Chunks(out);
    var tail0 = o.groupName != null ? 122 : 111;
    for (i = 12; i < 89; i++) if (out[i] !== raw[i]) throw new Error('bytes outside the identity fields changed');
    for (i = tail0; i < raw.length - ZD2_TRAILER; i++) if (out[i] !== raw[i]) throw new Error('bytes outside the identity fields changed');
    return out;
  }

  // tools-pedal/pedal_diy.py check_envelope / check_zic — the upload gate the
  // DIY install wrapper applies (the 2026-07 brick lesson). Same invariants,
  // so a built file that passes here passes there.
  function checkEnvelope(data) {
    var errs = [];
    if (data.length < 144 || data[0] !== 0x5A || data[1] !== 0x44 || data[2] !== 0x4C || data[3] !== 0x46) return ['not a ZD2 container'];
    if (rd32(data, 4) !== 120) errs.push('header @4 is not 120');
    if (rd32(data, 8) !== zd2Crc(data)) errs.push('checksum @8 does not validate');
    if (!(rd32(data, 12) & 0x0080)) errs.push('target lacks the MS-plus family bit 0x0080');
    if (data[93] || data[94]) errs.push('bytes @93..94 are not zero');
    if (data[125] || data[126] || data[127]) errs.push('bytes @125..127 are not zero');
    if (data[95] !== (rd32(data, 96) >>> 24)) errs.push('group byte @95 does not match the id top byte');
    if (data[100] === 0) errs.push('effect name is empty');
    for (var i = 100; i < 111 && data[i]; i++) if (data[i] < 0x20 || data[i] >= 0x7F) { errs.push('effect name not printable ASCII'); break; }
    for (i = 89; i < 93; i++) if (data[i] < 0x20 || data[i] >= 0x7F) { errs.push('version @89 not printable ASCII'); break; }
    var off = 128, end = data.length - 16, tiled = true;
    while (off + 8 <= end) {
      for (var j = 0; j < 4; j++) {
        var c = data[off + j];
        if (!((c >= 0x30 && c <= 0x39) || (c >= 0x41 && c <= 0x5A) || (c >= 0x61 && c <= 0x7A))) {
          errs.push('section walk hit a non-tag at offset ' + off); tiled = false; break;
        }
      }
      if (!tiled) break;
      off += 8 + rd32(data, off + 4);
    }
    if (tiled && off !== end) errs.push('sections do not tile the file');
    return errs;
  }
  function checkZic(data) {
    if (data.length < 12 || data[0] !== 0x5A || data[1] !== 0x42 || data[2] !== 0x4D || data[3] !== 0x50) return ['not a ZIC icon'];
    var dlen = rd32(data, 4);
    if (dlen % 4 || dlen < 8 || dlen > 64) return ['descriptor block length out of range'];
    if (data.length < 8 + dlen) return ['file shorter than its descriptor block'];
    var frames = [];
    for (var i = 0; i < dlen / 4; i++) {
      var w = data[8 + 4 * i] | (data[9 + 4 * i] << 8), h = data[10 + 4 * i] | (data[11 + 4 * i] << 8);
      if (w === 0 || h === 0) break;
      frames.push([w, h]);
    }
    var errs = [];
    if (!frames.length) errs.push('no icon frames');
    if (frames.some(function (f) { return f[0] > 256 || f[1] > 256; })) errs.push('frame dimension out of range');
    var total = 8 + dlen;
    frames.forEach(function (f) { total += f[0] * (((f[1] - 1) >> 3) + 1); });
    if (!errs.length && total !== data.length) errs.push('icon does not tile');
    return errs;
  }

  function readIdentity(raw) {
    function str(a, b) {
      var s = '';
      for (var i = a; i < b && raw[i]; i++) s += String.fromCharCode(raw[i]);
      return s;
    }
    return { version: str(89, 93), group: raw[95], id: rd32(raw, 96), name: str(100, 111), groupName: str(111, 122) };
  }

  // =====================================================================
  // loading + tier validation (spec §3; nam_ref.parse_a2, _pick_submodel)
  // =====================================================================
  function asList(v, n) {
    if (Array.isArray(v)) return v.slice();
    var out = [];
    for (var i = 0; i < n; i++) out.push(v);
    return out;
  }
  function arrEq(a, b) {
    if (!Array.isArray(a) || a.length !== b.length) return false;
    for (var i = 0; i < a.length; i++) if (a[i] !== b[i]) return false;
    return true;
  }
  function refusal(code, failed, extra) {
    var t = REFUSALS[code];
    return { code: code, title: t.title, body: extra || t.body, failed: failed };
  }
  // Wording adapted from app-gui-sketches/project/Refusals.dc.html
  var REFUSALS = {
    'not-nam': { title: "This isn't a NAM capture file",
      body: 'The file could not be read as a NAM capture (.nam is a JSON file written by the NAM trainer).' },
    'a1': { title: 'This is an older NAM capture (A1)',
      body: 'Only A2 captures run on the pedal. Look for an A2 version of this tone, or re-train it with the current NAM trainer.' },
    'no-lite': { title: 'No A2 Lite model in this file',
      body: 'The pedal runs the Lite model that the NAM trainer puts inside every A2 file. This file has no Lite (3-channel) model; the Full model is too big for the pedal.' },
    'not-a2': { title: 'Not a supported NAM model',
      body: 'The pedal runs only the standard A2 Lite WaveNet. This model has a different shape.' },
    'rate': { title: 'Unsupported sample rate',
      body: "The pedal's NAM engines take captures made at 44.1 or 48 kHz." },
    'pack': { title: "This capture doesn't fit the pedal's number format",
      body: "Its weights or levels fall outside what the pedal's fixed-point engine can hold, so the app stops here instead of installing something that plays silence." },
    'fidelity': { title: 'This capture would sound wrong on the pedal',
      body: "We played it through a copy of the pedal's engine. It clips or drifts inside, even with extra headroom, so the app stops here instead of installing something that sounds broken." },
    'error': { title: 'Something went wrong while checking this file',
      body: 'The builder hit an internal error. The file was not changed.' }
  };

  /** Parse + validate. Returns {ok, checks, meta, net?, sampleRate, refusal?}. */
  function parseCapture(text) {
    var checks = [];
    function ck(key, label, ok, detail, status) {
      checks.push({ key: key, label: label, status: status || (ok ? 'pass' : 'fail'), detail: detail || '' });
      return ok;
    }
    var top;
    try {
      top = JSON.parse(text);
    } catch (e) {
      ck('json', 'Readable NAM file (JSON)', false, String(e.message).slice(0, 160));
      return { ok: false, checks: checks, meta: {}, refusal: refusal('not-nam', 'not valid JSON') };
    }
    if (!top || typeof top !== 'object' || Array.isArray(top)) {
      ck('json', 'Readable NAM file (JSON)', false, 'not a JSON object');
      return { ok: false, checks: checks, meta: {}, refusal: refusal('not-nam', 'not a JSON object') };
    }
    ck('json', 'Readable NAM file (JSON)', true, 'NAM file version ' + (top.version || '?'));
    var arch = top.architecture;
    var m = top;
    var meta0 = {};
    try {
      if (arch === 'SlimmableContainer') {
        var subs = (top.config && top.config.submodels) || [];
        var chans = subs.map(function (sm) {
          try { return sm.model.config.layers[0].channels; } catch (e) { return null; }
        });
        m = null;
        for (var i = 0; i < subs.length; i++) {
          if (chans[i] === C) { m = subs[i].model; break; }
        }
        if (!m) {
          ck('lite', 'Contains an A2 Lite (3-channel) model', false,
            'submodels have ' + chans.join(', ') + ' channels');
          return { ok: false, checks: checks, meta: metaOf(top, top), refusal: refusal('no-lite', 'no 3-channel submodel') };
        }
        ck('lite', 'Contains an A2 Lite (3-channel) model', true,
          'container with ' + subs.length + ' models (' + chans.join(', ') + ' channels); using the 3-channel one');
      } else if (arch === 'WaveNet') {
        ck('lite', 'Contains an A2 Lite (3-channel) model', true, 'bare WaveNet model', 'pass');
      } else {
        ck('arch', 'A WaveNet (A2) capture', false, 'architecture ' + arch);
        return { ok: false, checks: checks, meta: metaOf(top, top), refusal: refusal('not-a2', 'architecture is ' + arch) };
      }
      meta0 = metaOf(m, top);
      if (m.architecture !== 'WaveNet') {
        ck('arch', 'A WaveNet (A2) capture', false, 'architecture ' + m.architecture);
        return { ok: false, checks: checks, meta: meta0, refusal: refusal('not-a2', 'architecture is ' + m.architecture) };
      }
      var cfg = m.config;
      if (!cfg || !Array.isArray(cfg.layers) || cfg.layers.length !== 1) {
        var nla = cfg && Array.isArray(cfg.layers) ? cfg.layers.length : 0;
        ck('arch', 'A2 structure (one layer array)', false, nla + ' layer arrays: an A1 "Standard/Lite/Feather" WaveNet');
        return { ok: false, checks: checks, meta: meta0, refusal: refusal('a1', 'architecture is A1 (' + nla + ' layer arrays)') };
      }
      var la = cfg.layers[0];
      var ch = la.channels;
      if (ch !== C) {
        ck('shape', 'A2 Lite shape (3 channels)', false, ch + ' channels');
        return { ok: false, checks: checks, meta: meta0, refusal: refusal('no-lite', 'bare model has ' + ch + ' channels') };
      }
      var bott = la.bottleneck == null ? ch : la.bottleneck;
      if (bott !== ch || la.input_size !== 1 || la.condition_size !== 1) {
        ck('shape', 'A2 Lite shape', false, 'bottleneck/input/condition size');
        return { ok: false, checks: checks, meta: meta0, refusal: refusal('not-a2', 'bottleneck/input/condition not A2') };
      }
      var ks = asList(la.kernel_sizes != null ? la.kernel_sizes : la.kernel_size, NL);
      var dl = la.dilations;
      if (!arrEq(ks, A2_KERNELS) || !arrEq(dl, A2_DILATIONS)) {
        ck('shape', 'A2 kernel sizes and dilations', false, 'not the A2 pattern');
        return { ok: false, checks: checks, meta: meta0, refusal: refusal('not-a2', 'kernel sizes / dilations are not the A2 pattern') };
      }
      var acts = asList(la.activation, NL);
      for (i = 0; i < acts.length; i++) {
        var a = acts[i];
        var t = (a && typeof a === 'object') ? a.type : a;
        var s = (a && typeof a === 'object') ? (a.negative_slope == null ? 0.01 : a.negative_slope) : 0.01;
        if (t !== 'LeakyReLU' || Math.abs(s - SLOPE) > 1e-6) {
          ck('shape', 'Activation LeakyReLU(0.01)', false, 'layer ' + i + ': ' + JSON.stringify(a).slice(0, 60));
          return { ok: false, checks: checks, meta: meta0, refusal: refusal('not-a2', 'activation is not LeakyReLU(0.01)') };
        }
      }
      if (la.gated === true) {
        ck('shape', 'Not gated', false, 'gated');
        return { ok: false, checks: checks, meta: meta0, refusal: refusal('not-a2', 'gated') };
      }
      var head = la.head;
      if (!head || head.out_channels !== 1 || head.kernel_size !== HEAD_K || !head.bias) {
        ck('shape', 'A2 head', false, 'head is not the A2 head');
        return { ok: false, checks: checks, meta: meta0, refusal: refusal('not-a2', 'head is not the A2 head') };
      }
      ck('shape', 'A2 Lite shape (23 layers, kernels, dilations, LeakyReLU, head)', true, '');
      var w = m.weights;
      if (!Array.isArray(w) || w.length !== N_WEIGHTS) {
        ck('weights', 'Weight count 1,871', false, (Array.isArray(w) ? w.length : 'no') + ' weights');
        return { ok: false, checks: checks, meta: meta0, refusal: refusal('not-a2', 'weight stream has ' + (Array.isArray(w) ? w.length : 0) + ' floats, A2 Lite has 1871') };
      }
      for (i = 0; i < w.length; i++) {
        if (typeof w[i] !== 'number' || !isFinite(w[i])) {
          ck('weights', 'Weight count 1,871', false, 'weight ' + i + ' is not a finite number');
          return { ok: false, checks: checks, meta: meta0, refusal: refusal('not-a2', 'non-finite weight') };
        }
      }
      ck('weights', 'Weight count 1,871', true, '1,871 weights consumed exactly');
      var net = weightsToNet(w);
      net.metadata = m.metadata || {};
      net.sampleRate = m.sample_rate != null ? m.sample_rate : top.sample_rate;
      return { ok: true, checks: checks, meta: meta0, net: net, sampleRate: net.sampleRate };
    } catch (e) {
      ck('shape', 'A2 Lite shape', false, String(e && e.message || e).slice(0, 160));
      return { ok: false, checks: checks, meta: meta0, refusal: refusal('not-a2', String(e && e.message || e).slice(0, 120)) };
    }
  }

  // What the file says about itself. A container (TONE3000, the NAM
  // trainer) names the capture in its TOP-LEVEL metadata (name, modeled_by,
  // gear_*, tone_type, the levels, the trainer); each submodel's own
  // metadata holds only its date, loudness and gain. So: the top level,
  // with the chosen submodel's fields on top of it. (Until 2026-10-02 the
  // submodel's block REPLACED the top one, and a real container showed no
  // name, maker or gear at all.)
  function metaOf(m, top) {
    var md = {}, k;
    var tmd = (top && top.metadata) || {}, mmd = (m && m !== top && m.metadata) || {};
    for (k in tmd) if (Object.prototype.hasOwnProperty.call(tmd, k) && tmd[k] != null) md[k] = tmd[k];
    for (k in mmd) if (Object.prototype.hasOwnProperty.call(mmd, k) && mmd[k] != null) md[k] = mmd[k];
    var sr = (m && m.sample_rate != null) ? m.sample_rate : (top ? top.sample_rate : null);
    var d = md.date && typeof md.date === 'object' ? md.date : null;
    function p2(v) { return (v < 10 ? '0' : '') + v; }
    return {
      name: md.name != null ? md.name : null,
      modeled_by: md.modeled_by != null ? md.modeled_by : null,
      gear_type: md.gear_type != null ? md.gear_type : null,
      gear_make: md.gear_make != null ? md.gear_make : null,
      gear_model: md.gear_model != null ? md.gear_model : null,
      tone_type: md.tone_type != null ? md.tone_type : null,
      loudness: md.loudness != null ? md.loudness : null,
      gain: md.gain != null ? md.gain : null,
      input_level_dbu: md.input_level_dbu != null ? md.input_level_dbu : null,
      output_level_dbu: md.output_level_dbu != null ? md.output_level_dbu : null,
      trainer: md.trainer != null ? md.trainer : null,
      date: d && d.year ? d.year + '-' + p2(d.month || 1) + '-' + p2(d.day || 1) : null,
      sample_rate: sr == null ? null : sr,
      nam_version: top && top.version != null ? top.version : null,
      architecture: top ? top.architecture : null
    };
  }

  // the weight walk (spec §4) -> net {rech, layers[{K,d,cw,cb,mx,w1,b1}], hw, hb, headScale}
  function weightsToNet(w) {
    var it = 0;
    function take(n) {
      if (it + n > w.length) throw new Error('weight stream exhausted');
      var v = new Float64Array(n);
      for (var i = 0; i < n; i++) v[i] = w[it + i];
      it += n;
      return v;
    }
    var net = { C: C, layers: [] };
    net.rech = take(C);
    for (var li = 0; li < NL; li++) {
      var K = A2_KERNELS[li];
      var cw = take(C * C * K);     // [o][j][k] -> o*C*K + j*K + k
      var cb = take(C);
      var mx = take(C);
      var w1 = take(C * C);         // [o][j]
      var b1 = take(C);
      net.layers.push({ K: K, d: A2_DILATIONS[li], cw: cw, cb: cb, mx: mx, w1: w1, b1: b1 });
    }
    net.hw = take(C * HEAD_K);      // [j][k] -> j*16 + k
    net.hb = take(1)[0];
    net.headScale = take(1)[0];
    if (it !== w.length) throw new Error((w.length - it) + ' trailing weights');
    return net;
  }

  // nam_ref.rescale_a2 (float function unchanged; f(a z) = a f(z) for LeakyReLU)
  function rescaleA2(net, a) {
    if (!(a > 0 && isFinite(a))) throw new Error('rescale factor must be a positive finite number');
    function mul(v) { var o = new Float64Array(v.length); for (var i = 0; i < v.length; i++) o[i] = v[i] * a; return o; }
    var n = { C: net.C, rech: mul(net.rech), hb: net.hb, headScale: net.headScale,
      metadata: net.metadata, sampleRate: net.sampleRate, layers: [] };
    net.layers.forEach(function (L) {
      n.layers.push({ K: L.K, d: L.d, cw: L.cw, cb: mul(L.cb), mx: mul(L.mx), w1: L.w1, b1: mul(L.b1) });
    });
    var hw = new Float64Array(net.hw.length);
    for (var i = 0; i < hw.length; i++) hw[i] = net.hw[i] / a;
    n.hw = hw;
    n.rescale = a * (net.rescale || 1.0);
    return n;
  }

  // =====================================================================
  // the float model (nam_ref.forward_float), float64, whole-signal per layer
  // =====================================================================
  async function forwardFloat(net, x, stats, yieldFn) {
    yieldFn = yieldFn || noYield;
    var T = x.length;
    var h = [], i, o, t;
    var xmax = [], zmax = [];
    var m0 = 0;
    for (o = 0; o < C; o++) {
      var ho = new Float64Array(T);
      var r = net.rech[o];
      for (t = 0; t < T; t++) { ho[t] = r * x[t]; var av = Math.abs(ho[t]); if (av > m0) m0 = av; }
      h.push(ho);
    }
    xmax.push(m0);
    var head = [new Float64Array(T), new Float64Array(T), new Float64Array(T)];
    var z = [new Float64Array(T), new Float64Array(T), new Float64Array(T)];
    var act = [new Float64Array(T), new Float64Array(T), new Float64Array(T)];
    for (var li = 0; li < net.layers.length; li++) {
      var L = net.layers[li];
      var K = L.K, d = L.d;
      var zm = 0;
      var h0 = h[0], h1 = h[1], h2 = h[2];
      for (o = 0; o < C; o++) {
        var zo = z[o];
        var cb = L.cb[o], mx = L.mx[o];
        for (t = 0; t < T; t++) zo[t] = cb + mx * x[t];
        for (var k = 0; k < K; k++) {
          var lag = d * (K - 1 - k);
          var base = o * C * K;
          var w0 = L.cw[base + k], w1v = L.cw[base + K + k], w2 = L.cw[base + 2 * K + k];
          for (t = lag; t < T; t++) {               // zero history before the first sample
            var idx = t - lag;
            zo[t] = zo[t] + ((w0 * h0[idx] + w1v * h1[idx]) + w2 * h2[idx]);
          }
        }
        var ao = act[o], hdo = head[o];
        for (t = 0; t < T; t++) {
          var zv = zo[t];
          var az = Math.abs(zv); if (az > zm) zm = az;
          var av2 = zv >= 0 ? zv : SLOPE * zv;
          ao[t] = av2;
          hdo[t] = hdo[t] + av2;
        }
      }
      // h = h + w1 @ a + b1
      var xm = 0;
      var nh = [];
      for (o = 0; o < C; o++) {
        var q0 = L.w1[o * C], q1 = L.w1[o * C + 1], q2 = L.w1[o * C + 2], bb = L.b1[o];
        var hn = new Float64Array(T), hoo = h[o];
        var a0 = act[0], a1 = act[1], a2 = act[2];
        for (t = 0; t < T; t++) {
          var v = (hoo[t] + ((q0 * a0[t] + q1 * a1[t]) + q2 * a2[t])) + bb;
          hn[t] = v;
          var avv = Math.abs(v); if (avv > xm) xm = avv;
        }
        nh.push(hn);
      }
      h = nh;
      zmax.push(zm);
      xmax.push(xm);
      await yieldFn(li, NL);
    }
    var y = new Float64Array(T);
    for (t = 0; t < T; t++) y[t] = net.hb;
    for (var kk = 0; kk < HEAD_K; kk++) {
      var lg = HEAD_K - 1 - kk;
      var c0 = net.hw[kk], c1 = net.hw[HEAD_K + kk], c2 = net.hw[2 * HEAD_K + kk];
      var e0 = head[0], e1 = head[1], e2 = head[2];
      for (t = lg; t < T; t++) {
        var id2 = t - lg;
        y[t] = y[t] + ((c0 * e0[id2] + c1 * e1[id2]) + c2 * e2[id2]);
      }
    }
    var ymax = 0, hmax = 0;
    for (t = 0; t < T; t++) {
      y[t] = net.headScale * y[t];
      var ay = Math.abs(y[t]); if (ay > ymax) ymax = ay;
    }
    if (stats) {
      for (o = 0; o < C; o++) for (t = 0; t < T; t++) { var ah = Math.abs(head[o][t]); if (ah > hmax) hmax = ah; }
      stats.zmax = zmax; stats.xmax = xmax.slice(0, -1); stats.headmax = hmax; stats.ymax = ymax;
    }
    return y;
  }

  // =====================================================================
  // quantize (nam_ref.quantize) — the ONE place the integers are made
  // =====================================================================
  function wshift(maxabs, cap) {
    var s = cap == null ? 14 : cap;
    while (s > 0 && roundHalfEven(maxabs * Math.pow(2, s)) > 32767) s -= 1;
    return s;
  }
  function maxAbs(v) { var m = 0; for (var i = 0; i < v.length; i++) { var a = Math.abs(v[i]); if (a > m) m = a; } return m; }

  // levelSteps (spec §5.8): the output level step, -36..+36 in 0.5 dB;
  // `oscale` is then the table word. Absent or 0 = 1.0f, the value every
  // image carried before level-matching.
  function quantize(net, ringExp, levelSteps) {
    var lsteps = levelSteps == null ? 0 : levelSteps;
    var osc = levelOscale(lsteps);                   // refuses a bad step
    for (var i = 0; i < net.rech.length; i++) {
      if (Math.abs(net.rech[i]) >= 2.0) throw new PackError('rechannel weight >= 2 does not fit Q14');
    }
    var e = ringExp ? ringExp.slice() : net.layers.map(function () { return 0; });
    if (e.length !== net.layers.length) throw new PackError('ring_exp must be one exponent per layer');
    for (i = 0; i < e.length; i++) {
      if (e[i] < 0 || (i + 1 < e.length && e[i + 1] < e[i])) throw new PackError('ring_exp must be non-negative and non-decreasing');
    }
    var q = { C: net.C, ringExp: e, rq: [], layers: [] };
    for (i = 0; i < C; i++) q.rq.push(roundHalfEven(net.rech[i] * 16384));
    net.layers.forEach(function (L, li) {
      var el = e[li];
      var s = wshift(Math.max(maxAbs(L.cw), maxAbs(L.mx)));
      var s1 = wshift(maxAbs(L.w1));
      var ps = Math.pow(2, s), ps1 = Math.pow(2, s1);
      var wq = new Array(L.cw.length), mq = [], bq = [], w1q = new Array(L.w1.length), b1q = [];
      for (var j = 0; j < L.cw.length; j++) wq[j] = roundHalfEven(L.cw[j] * ps);
      for (j = 0; j < L.w1.length; j++) w1q[j] = roundHalfEven(L.w1[j] * ps1);
      var pb = Math.pow(2, AQ - el + s), pb1 = Math.pow(2, AQ - el + s1);
      for (j = 0; j < C; j++) {
        mq.push(roundHalfEven(L.mx[j] * ps));
        bq.push(roundHalfEven(L.cb[j] * pb));
        b1q.push(roundHalfEven(L.b1[j] * pb1));
      }
      q.layers.push({ K: L.K, d: L.d, s: s, s1: s1, e: el, wq: wq, mq: mq, bq: bq, w1q: w1q, b1q: b1q });
    });
    // float head, head_scale folded in (v0.05)
    q.hw = new Float32Array(C * HEAD_K);
    for (i = 0; i < C * HEAD_K; i++) q.hw[i] = Math.fround(net.hw[i] * net.headScale / 1024);
    q.hb = Math.fround(net.hb * net.headScale);
    q.oscale = osc;                                  // a float32 value from the table; step 0 = 1.0
    q.levelSteps = lsteps;
    q.iscale = 8192.0;
    return q;
  }

  // =====================================================================
  // the int16 kernel emulation (nam_ref.forward_kernel, aq 10, cond_q 13,
  // dry None, fixd True) — bit-exact to namwn.c v0.10 (spec §6.8)
  // levelSteps (spec §5.8): the network's float32 output is multiplied by
  // the step's `oscale` in float32 before Fix D, as the kernel does
  // (wet = y * oscale * vol). Absent or 0 = oscale 1.0.
  // =====================================================================
  async function forwardKernel(net, x, ringExp, stats, yieldFn, levelSteps) {
    yieldFn = yieldFn || noYield;
    var T = x.length, t, o, j, k;
    var cx = CQ - AQ;
    var qz = quantize(net, ringExp, levelSteps);
    var ex = qz.ringExp;
    var xi = new Float64Array(T);
    for (t = 0; t < T; t++) {
      var xf = Math.fround(Math.fround(x[t]) * 8192);
      if (xf < -32768) xf = -32768; else if (xf > 32767) xf = 32767;
      xi[t] = Math.trunc(xf);
    }
    var h = [];
    for (o = 0; o < C; o++) {
      var ho = new Int32Array(T), rq = qz.rq[o];
      var sh0 = 14 + cx + ex[0];
      for (t = 0; t < T; t++) {
        var v0 = sat16(floorShift(rq * xi[t], sh0));
        ho[t] = v0 < RING_LO ? RING_LO : (v0 > RING_HI ? RING_HI : v0);
      }
      h.push(ho);
    }
    var head = [new Float64Array(T), new Float64Array(T), new Float64Array(T)];
    var act = [new Int32Array(T), new Int32Array(T), new Int32Array(T)];
    var accmax = 0, zsat = 0, xclip = 0;
    var nL = qz.layers.length;
    for (var li = 0; li < nL; li++) {
      var Lq = qz.layers[li];
      var K = Lq.K, d = Lq.d, s = Lq.s, s1 = Lq.s1, el = ex[li];
      var ps = Math.pow(2, s);
      var h0 = h[0], h1 = h[1], h2 = h[2];
      var mxs = cx + el, pmx = Math.pow(2, mxs);
      var pel = Math.pow(2, el);
      for (o = 0; o < C; o++) {
        var bq = Lq.bq[o], mq = Lq.mq[o];
        var ao = act[o], hdo = head[o];
        var ws = [];
        for (k = 0; k < K; k++) {
          var bi = o * C * K;
          ws.push([Lq.wq[bi + k], Lq.wq[bi + K + k], Lq.wq[bi + 2 * K + k], d * (K - 1 - k)]);
        }
        for (t = 0; t < T; t++) {
          var acc = bq + Math.floor((mq * xi[t]) / pmx);
          for (k = 0; k < K; k++) {
            var wk = ws[k];
            var idx = t - wk[3];
            if (idx >= 0) acc += wk[0] * h0[idx] + wk[1] * h1[idx] + wk[2] * h2[idx];
          }
          var aa = acc < 0 ? -acc : acc;
          if (aa > accmax) accmax = aa;
          var zr = Math.floor(acc / ps);
          if (zr > 32767 || zr < -32768) zsat++;
          var z = zr > 32767 ? 32767 : (zr < -32768 ? -32768 : zr);
          var a = z >= 0 ? z : ((z * 655) >> 16);
          ao[t] = a;
          hdo[t] += a * pel;
        }
      }
      var de = (li + 1 < nL) ? (ex[li + 1] - el) : 0;
      var ps1 = Math.pow(2, s1), pde = Math.pow(2, de);
      var nh = [];
      var a0 = act[0], a1 = act[1], a2 = act[2];
      for (o = 0; o < C; o++) {
        var b1 = Lq.b1q[o], q0 = Lq.w1q[o * C], q1 = Lq.w1q[o * C + 1], q2 = Lq.w1q[o * C + 2];
        var hoo = h[o], hn = new Int32Array(T);
        for (t = 0; t < T; t++) {
          var acc1 = b1 + q0 * a0[t] + q1 * a1[t] + q2 * a2[t];
          var ab = acc1 < 0 ? -acc1 : acc1;
          if (ab > accmax) accmax = ab;
          var v = sat16(Math.floor((hoo[t] + Math.floor(acc1 / ps1)) / pde));
          if (v < RING_LO || v > RING_HI) { xclip++; v = v < RING_LO ? RING_LO : RING_HI; }
          hn[t] = v;
        }
        nh.push(hn);
      }
      h = nh;
      await yieldFn(li, nL);
    }
    // float32 head: two partial sums per channel (even/odd taps), channel order
    var fr = Math.fround;
    var hw = qz.hw;
    var yacc = new Float32Array(T);
    for (t = 0; t < T; t++) yacc[t] = qz.hb;
    var hf = new Float32Array(T), s0 = new Float32Array(T), s1v = new Float32Array(T);
    for (o = 0; o < C; o++) {
      var hdd = head[o];
      for (t = 0; t < T; t++) { hf[t] = hdd[t]; s0[t] = 0; s1v[t] = 0; }   // Float32Array store = fround
      for (k = 0; k < HEAD_K; k += 2) {
        var we = hw[o * HEAD_K + k], wo = hw[o * HEAD_K + k + 1];
        var le = HEAD_K - 1 - k, lo = HEAD_K - 2 - k;
        for (t = 0; t < T; t++) {
          var ve = t >= le ? hf[t - le] : 0;
          var vo = t >= lo ? hf[t - lo] : 0;
          s0[t] = fr(s0[t] + fr(we * ve));
          s1v[t] = fr(s1v[t] + fr(wo * vo));
        }
      }
      for (t = 0; t < T; t++) yacc[t] = fr(yacc[t] + fr(s0[t] + s1v[t]));
    }
    var y = new Float32Array(T);
    for (t = 0; t < T; t++) {
      var yy = fr(yacc[t] * qz.oscale);
      y[t] = (yy > -8.0 && yy < 8.0) ? yy : 0.0;           // Fix D
    }
    if (stats) {
      stats.accmax = accmax; stats.accOverflow = accmax >= 2147483648;
      stats.zsat = zsat; stats.xclip = xclip;
      stats.shifts = qz.layers.map(function (L) { return [L.s, L.s1]; });
    }
    return y;
  }

  function esr(ref, test) {
    var e = 0, p = 0;
    for (var i = 0; i < ref.length; i++) {
      var dd = ref[i] - test[i];
      e += dd * dd;
      p += ref[i] * ref[i];
    }
    return p > 0 ? e / p : Infinity;
  }

  // =====================================================================
  // exponents (nam_pack.choose_ring_exp / prepare_rexp, spec §5.6)
  // =====================================================================
  function chooseRingExpFromStats(fs, marginDb) {
    var m = Math.pow(10, marginDb / 20.0);
    var e = [], prev = 0;
    for (var li = 0; li < NL; li++) {
      var need = m * Math.max(fs.xmax[li] / RING_LIMIT, fs.zmax[li] / Z_LIMIT);
      var el = Math.max(prev, need <= 1.0 ? 0 : Math.ceil(Math.log2(need)));
      e.push(el);
      prev = el;
    }
    return e;
  }
  function rechannelRescale(net) {
    var rm = maxAbs(net.rech);
    if (rm >= RECH_LIMIT) {
      var a = RECH_LIMIT / rm * 0.95;
      return { net: rescaleA2(net, a), a: a };
    }
    return { net: net, a: 1.0 };
  }
  function parseRingExp(s) {
    if (typeof s !== 'string' || s.length !== NL || !/^[0-8]+$/.test(s)) throw new Error('need ' + NL + ' digits 0-8');
    var e = s.split('').map(Number);
    for (var i = 0; i + 1 < e.length; i++) if (e[i + 1] < e[i]) throw new Error('exponents must not decrease along the stack');
    return e;
  }

  // =====================================================================
  // the output level (spec §5.8; nam_ref.warm_pluck / level_db /
  // level_choose / level_oscale, nam_pack.prepare_level / level_record).
  // Everything here is float64 arithmetic in a FIXED order, so it gives
  // the reference's result bit for bit GIVEN the same model output. The
  // model output differs from numpy's in its last bits (summation order),
  // and Math.log10 may differ from the C library's in its last bit, so the
  // step is also an explicit input (opts.fixedLevelSteps; the sidecar
  // records it), exactly as the ring exponents are.
  // =====================================================================
  function LevelError(msg) { this.name = 'LevelError'; this.message = msg; this.stack = (new Error(msg)).stack; }
  LevelError.prototype = Object.create(Error.prototype);

  /** The float32 `oscale` VALUE of a level step, from the table. Refuses
   *  anything but an integer in -36..+36. */
  function levelOscale(steps) {
    if (typeof steps !== 'number' || !isFinite(steps) || Math.floor(steps) !== steps) {
      throw new Error('the level step must be an integer, got ' + String(steps));
    }
    if (steps < -LEVEL_MAX_STEPS || steps > LEVEL_MAX_STEPS) {
      throw new Error('level step ' + steps + ' is outside -' + LEVEL_MAX_STEPS + '..+' + LEVEL_MAX_STEPS +
        ' (+-' + (LEVEL_MAX_STEPS * LEVEL_STEP_DB) + ' dB)');
    }
    return LEVEL_OSCALE[steps + LEVEL_MAX_STEPS];
  }

  /** The level signal: the gate's pluck through two one-pole high-passes at
   *  70 Hz, then two one-pole low-passes at 300 Hz, rescaled to peak 0.7.
   *  One operation at a time, in the spec's order (§5.8 step 1). */
  function warmPluck(pluck) {
    var n = pluck.length, y = new Float64Array(n), i, pass, s;
    for (i = 0; i < n; i++) y[i] = pluck[i];
    for (pass = 0; pass < 2; pass++) {               // high-pass: the input minus its own one-pole low-pass
      s = 0.0;
      for (i = 0; i < n; i++) {
        s = s + LEVEL_HP_K * (y[i] - s);
        y[i] = y[i] - s;
      }
    }
    for (pass = 0; pass < 2; pass++) {               // low-pass
      s = 0.0;
      for (i = 0; i < n; i++) {
        s = s + LEVEL_LP_K * (y[i] - s);
        y[i] = s;
      }
    }
    var pk = 0.0;
    for (i = 0; i < n; i++) { var a = Math.abs(y[i]); if (a > pk) pk = a; }
    if (!(pk > 0.0)) throw new Error('the warm pluck is silent (an all-zero pluck?)');
    var g = LEVEL_PEAK / pk;                         // ONE division, then one multiply per sample
    for (i = 0; i < n; i++) y[i] = y[i] * g;
    return y;
  }

  /** RMS level in dB: 20 log10(sqrt(sum(y^2) / N)), the sum in SAMPLE ORDER.
   *  -Infinity for silence. */
  function levelDb(y) {
    var acc = 0.0, n = y.length;
    for (var i = 0; i < n; i++) acc += y[i] * y[i];
    if (!n || !(acc > 0.0)) return -Infinity;
    return 20.0 * Math.log10(Math.sqrt(acc / n));
  }

  /**
   * levelChoose(level, ymaxProbe) — the level step from the two measured
   * numbers (§5.8 step 3): `level`, the float model's levelDb on the warm
   * pluck, and `ymaxProbe`, its largest |output| on the full-scale probe.
   * Returns {rule, how, steps, db, oscaleBits, levelDb, wantDb,
   * stepsUnclamped, clamped, guarded, ymaxProbe, guardProduct,
   * roundMarginDb, guardMarginDb}: the two margins say how far the decision
   * is from flipping (roundMarginDb: 0.25 = the centre of a step, 0 = on a
   * rounding boundary). Throws a LevelError for a level that is not finite
   * (a silent or broken model).
   */
  function levelChoose(level, ymaxProbe) {
    var ymax = ymaxProbe;
    if (typeof level !== 'number' || !isFinite(level)) {
      throw new LevelError('the model\'s level on the level signal is not finite (a silent or broken model): no level step');
    }
    if (typeof ymax !== 'number' || !isFinite(ymax) || !(ymax >= 0.0)) {
      throw new LevelError('the model\'s peak on the full-scale probe is not a finite number');
    }
    var want = LEVEL_TARGET_DB - level;
    var r = want / LEVEL_STEP_DB;
    var n0 = roundHalfEven(r) + 0;                   // half to even, as Python's round(); + 0 turns -0 into 0
    var n1 = Math.max(-LEVEL_MAX_STEPS, Math.min(LEVEL_MAX_STEPS, n0));
    function product(k) { return ymax * levelOscale(k) * LEVEL_VOL_MAX; }   // float64, left to right
    var n = n1;
    while (n > -LEVEL_MAX_STEPS && product(n) > LEVEL_GUARD_CEILING) n -= 1;
    var prod = product(n);
    var gm = prod > 0.0 ? db(LEVEL_GUARD_CEILING / prod) : Infinity;
    if (n !== n1) gm = Math.min(gm, db(product(n + 1) / LEVEL_GUARD_CEILING));
    return { rule: LEVEL_RULE, how: 'measured', steps: n, db: n * LEVEL_STEP_DB,
      oscaleBits: LEVEL_OSCALE_BITS[n + LEVEL_MAX_STEPS],
      levelDb: level, wantDb: want, stepsUnclamped: n0, clamped: n1 !== n0, guarded: n !== n1,
      ymaxProbe: ymax, guardProduct: prod,
      roundMarginDb: (0.5 - Math.abs(r - n0)) * LEVEL_STEP_DB, guardMarginDb: gm };
  }

  /** An explicit step (opts.fixedLevelSteps; the reference's --level-steps N):
   *  nothing is measured. Refuses a bad step. */
  function levelFixed(steps) {
    levelOscale(steps);
    return { rule: LEVEL_RULE, how: 'explicit', steps: steps, db: steps * LEVEL_STEP_DB,
      oscaleBits: LEVEL_OSCALE_BITS[steps + LEVEL_MAX_STEPS] };
  }

  /**
   * measureLevel(net, env, ymaxProbe, yieldFn) — §5.8 steps 2 and 3 for a net
   * AS IT WILL BE PACKED (after the rechannel rescale, which does not change
   * the float function): one float pass on the warm pluck, then levelChoose.
   * ymaxProbe = the float model's largest |output| on the full-scale probe
   * (forwardFloat's stats.ymax on env.signals.probe).
   */
  async function measureLevel(net, env, ymaxProbe, yieldFn) {
    var y = await forwardFloat(net, env.signals.warm, null, yieldFn);
    return levelChoose(levelDb(y), ymaxProbe);
  }

  /** The `level` object of a sidecar (nam_pack.level_record): the rule, the
   *  step, its dB and the oscale word; for a measured step also the numbers
   *  it came from. Keys as the reference writes them. */
  function levelRecord(lv) {
    var rec = { rule: lv.rule, how: lv.how, steps: lv.steps, db: lv.db, oscale: hex8(lv.oscaleBits) };
    if (lv.how === 'measured') {
      var fin = function (v) { return isFinite(v) ? v : null; };
      rec.level_db = fin(lv.levelDb); rec.want_db = fin(lv.wantDb);
      rec.steps_unclamped = lv.stepsUnclamped; rec.clamped = lv.clamped; rec.guarded = lv.guarded;
      rec.ymax_probe = fin(lv.ymaxProbe); rec.guard_product = fin(lv.guardProduct);
      rec.round_margin_db = fin(lv.roundMarginDb); rec.guard_margin_db = fin(lv.guardMarginDb);
    }
    return rec;
  }
  function fmtSigned(v, digits) { return (v < 0 ? '-' : '+') + Math.abs(v).toFixed(digits); }
  function levelLine(lv) {
    var s = fmtSigned(lv.db, 1) + ' dB (step ' + (lv.steps < 0 ? '' : '+') + lv.steps + ', oscale ' + hex8(lv.oscaleBits) + ')';
    if (lv.how !== 'measured') return s + '; step given explicitly, nothing measured';
    s += '; measured ' + lv.levelDb.toFixed(2) + ' dB RMS, target ' + LEVEL_TARGET_DB.toFixed(0) + ' dB';
    if (lv.clamped) s += '; clamped from step ' + (lv.stepsUnclamped < 0 ? '' : '+') + lv.stepsUnclamped;
    if (lv.guarded) s += '; lowered by the peak guard';
    return s;
  }

  // =====================================================================
  // pack (nam_pack.pack) — the 12,288-word blob image (spec §6)
  // levelSteps: the output level step (§5.8); absent or 0 = oscale 1.0.
  // =====================================================================
  function pack(net, rs48, ringExp, levelSteps) {
    var CP = C + (C & 1), CW = CP / 2;
    var q = quantize(net, ringExp, levelSteps);
    var nl = q.layers.length;
    var mir = rs48 ? 32 : MIR;
    var nbmax = rs48 ? 18 : 16;
    var hrsteps = rs48 ? 64 : 32;
    var xsAlloc = Math.floor((2 * nbmax * CW + 31) / 32) * 32;
    var tailWords = C * hrsteps + xsAlloc + (rs48 ? 32 : 0);
    var rings = [], off = 0;
    q.layers.forEach(function (Lq) {
      var need = (Lq.K - 1) * Lq.d + nbmax;
      var steps = Math.floor((need + 15) / 16) * 16;
      rings.push([off, steps - 1]);
      off += (steps + mir) * CW;
    });
    var ringw = off;
    var arenaNeed = ringw * 4 + RALIGN + tailWords * 4;
    var tail = [];
    for (var j = 0; j < C; j++) tail.push(u32(q.rq[j]));
    for (var k = 0; k < HEAD_K; k++) for (var o = 0; o < C; o++) tail.push(f2u(q.hw[o * HEAD_K + k]));
    tail.push(f2u(q.hb));
    var wbase = HDR + nl * DW + tail.length;
    wbase += wbase & 1;
    var words = new Uint32Array(BLOB_WORDS);
    // word 3 = oscale: the table word of the level step (0x3F800000 at step 0)
    words[0] = MAGIC; words[1] = nl; words[2] = ringw; words[3] = f2u(q.oscale); words[4] = f2u(q.iscale);
    words[5] = rs48 ? mir : 0;
    var t0 = HDR + nl * DW;
    for (j = 0; j < tail.length; j++) words[t0 + j] = tail[j];
    var woff = wbase;
    q.layers.forEach(function (Lq, li) {
      var K = Lq.K;
      function wq(oo, jj, kk) { return jj < C ? Lq.wq[oo * C * K + jj * K + kk] : 0; }
      function w1(oo, jj) { return jj < C ? Lq.w1q[oo * C + jj] : 0; }
      var blk = [];
      var oo, kk, jj;
      for (oo = 0; oo < C; oo++) for (kk = 0; kk < K; kk++) for (jj = 0; jj < CW; jj++) blk.push(pair(wq(oo, 2 * jj, kk), wq(oo, 2 * jj + 1, kk)));
      for (oo = 0; oo < C; oo++) {
        var sum = 0;
        for (jj = 0; jj < C; jj++) for (kk = 0; kk < K; kk++) sum += Lq.wq[oo * C * K + jj * K + kk];
        blk.push(u32(Lq.bq[oo] - RBIAS * sum));
      }
      for (oo = 0; oo < C; oo++) {
        if (Lq.mq[oo] < -32768 || Lq.mq[oo] > 32767) throw new PackError('mixin weight does not fit int16');
        blk.push(u32(Lq.mq[oo]));
      }
      for (oo = 0; oo < C; oo++) for (jj = 0; jj < CW; jj++) blk.push(pair(w1(oo, 2 * jj), w1(oo, 2 * jj + 1)));
      for (oo = 0; oo < C; oo++) blk.push(u32(Lq.b1q[oo]));
      var roff = rings[li][0], mask = rings[li][1];
      var d0 = HDR + li * DW;
      if (!(Lq.e >= 0 && Lq.e <= 8)) throw new PackError('ring exponent out of 0..8');
      var desc = [Lq.d, mask, roff, Lq.s | (Lq.e << 8), Lq.s1, woff, K];
      for (jj = 0; jj < DW; jj++) words[d0 + jj] = desc[jj];
      if (woff + blk.length > BLOB_WORDS) throw new PackError('weights overflow the const blob');
      for (jj = 0; jj < blk.length; jj++) words[woff + jj] = blk[jj];
      woff += blk.length;
    });
    if (arenaNeed > ARENA_GRANT) throw new PackError('arena need ' + arenaNeed + ' B > grant ' + ARENA_GRANT + ' B');
    return { words: words, used: woff, ringw: ringw, arenaNeed: arenaNeed, q: q, rs48: rs48, levelSteps: q.levelSteps };
  }

  // =====================================================================
  // what the kernel checks before it will run (spec §6.6, v0.10 additions)
  // — the app validates the same list so the user learns why BEFORE installing
  // =====================================================================
  function kernelValidate(words, rs48) {
    var errs = [];
    var CW = 2;
    if (words[0] !== MAGIC) errs.push('magic');
    var nl = words[1];
    if (!(nl >= 1 && nl <= NL)) errs.push('NL ' + nl);
    var ringw = words[2];
    if (ringw === 0 || ringw % 32) errs.push('ringw ' + ringw);
    _f32buf.setUint32(0, words[3], true); var osc = _f32buf.getFloat32(0, true);
    _f32buf.setUint32(0, words[4], true); var isc = _f32buf.getFloat32(0, true);
    if (!(osc > -1.0e6 && osc < 1.0e6)) errs.push('oscale');   // the kernel's own bound (namwn.c; spec §5.8)
    if (!(isc > 0)) errs.push('iscale');
    var mir = words[5] === 0 ? 16 : words[5];
    var nbmax = rs48 ? 18 : 16;
    if (rs48 && mir !== 32) errs.push('48k host needs 32 mirror rows');
    var hrsteps = rs48 ? 64 : 32;
    var tailWords = C * hrsteps + (rs48 ? 96 : 64) + (rs48 ? 32 : 0);
    if (ringw * 4 + RALIGN + tailWords * 4 > ARENA_GRANT) errs.push('arena over the grant');
    var prevE = 0;
    for (var l = 0; l < nl && l < NL; l++) {
      var dsc = [];
      for (var j = 0; j < DW; j++) dsc.push(words[HDR + l * DW + j]);
      var d = dsc[0], steps = dsc[1] + 1, roff = dsc[2], w3 = dsc[3], s1 = dsc[4], woff = dsc[5], K = dsc[6];
      var s = w3 & 0xFF, e = (w3 >>> 8) & 15;
      if (K !== 6 && K !== 15) errs.push('L' + l + ' K ' + K);
      if (!(d >= 1 && d <= 65536)) errs.push('L' + l + ' dilation ' + d);
      if (steps % 16 || steps < (K - 1) * d + nbmax) errs.push('L' + l + ' ring steps ' + steps);
      if (roff + (steps + mir) * CW > ringw) errs.push('L' + l + ' ring overruns ringw');
      if (s > 30 || s1 > 30) errs.push('L' + l + ' shift');
      if (roff % 2) errs.push('L' + l + ' roff odd');
      if (woff + C * (K * CW + 2 + CW + 1) > BLOB_WORDS) errs.push('L' + l + ' weights overrun the blob');
      if (w3 >>> 12) errs.push('L' + l + ' descriptor word 3 bits 12-31 not zero');
      if (e > 8) errs.push('L' + l + ' exponent ' + e);
      if (e < prevE) errs.push('L' + l + ' exponent decreases');
      if (e - prevE > 8) errs.push('L' + l + ' exponent step');
      prevE = e;
    }
    _f32buf.setUint32(0, words[HDR + NL * DW + C + C * HEAD_K], true);
    var hb = _f32buf.getFloat32(0, true);
    if (!(Math.abs(hb) < 8)) errs.push('|head bias| >= 8');
    return errs;
  }

  // =====================================================================
  // signals + environment
  // =====================================================================
  function b64ToBytes(s) {
    if (typeof atob === 'function') {
      var bin = atob(s), out = new Uint8Array(bin.length);
      for (var i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
      return out;
    }
    return new Uint8Array(Buffer.from(s, 'base64'));   // Node
  }
  function bytesToF64(b) {
    var copy = new Uint8Array(b);                      // aligned
    return new Float64Array(copy.buffer, 0, copy.length / 8);
  }

  // ---------------------------------------------------------------------
  // the stock list (package 3): the stock rules (a capture named like a
  // stock effect gets " NAM"; no id or file name a stock effect has) are
  // never skipped silently. A caller passes the pedal's stock list, or says
  // explicitly that there is none with NO_STOCK ({none: true}); anything
  // else throws STOCK_MISSING. nam_pack.NO_STOCK is the reference's twin.
  // ---------------------------------------------------------------------
  var STOCK_MISSING = 'stock list missing: pass the pedal\'s stock list, or NO_STOCK explicitly';
  var NO_STOCK = Object.freeze({ none: true });
  // makeEnv's data.stock -> the environment's stock maps. A list must hold
  // the three arrays and at least one name or id; an empty list is refused
  // like a missing one (an app that failed to load its list must not build).
  function stockFromData(s) {
    var out = { names: {}, namesLower: {}, ids: {}, bases: {}, none: false };
    if (!s || typeof s !== 'object') throw new Error(STOCK_MISSING);
    if (s.none === true) {
      if ((s.names && s.names.length) || (s.ids && s.ids.length) || (s.bases && s.bases.length)) {
        throw new Error('the stock list is both NO_STOCK and a list: give one');
      }
      out.none = true;
      return out;
    }
    if (!Array.isArray(s.names) || !Array.isArray(s.ids) || !Array.isArray(s.bases)) throw new Error(STOCK_MISSING + ' (a list holds the arrays names, ids and bases)');
    if (!s.names.length && !s.ids.length) throw new Error(STOCK_MISSING + ' (the list given is empty)');
    s.names.forEach(function (n) { out.names[n] = 1; out.namesLower[String(n).toLowerCase()] = 1; });
    s.ids.forEach(function (n) { out.ids[n >>> 0] = 1; });
    s.bases.forEach(function (n) { out.bases[String(n).toUpperCase()] = 1; });
    return out;
  }
  // the stock maps a function reads: env (or the last makeEnv's) .stock;
  // {none: true} there means "explicitly none". No env, or an env with no
  // stock, throws.
  function stockOf(env) {
    var e = env || root.NAMB_ENV, s = e && e.stock;
    if (!s || typeof s !== 'object') throw new Error(STOCK_MISSING);
    if (s.none === true) return { names: {}, namesLower: {}, ids: {}, bases: {}, none: true };
    if (!s.names || !s.ids || !s.bases) throw new Error(STOCK_MISSING);
    if (!s.namesLower) {
      var low = {};
      Object.keys(s.names).forEach(function (n) { low[n.toLowerCase()] = 1; });
      return { names: s.names, namesLower: low, ids: s.ids, bases: s.bases, none: false };
    }
    return s;
  }

  /**
   * Decode + verify the data bundle (data/builder-data.js). Fail-closed.
   * data.stock: the pedal's stock list {files, names, ids, bases}, or
   * NO_STOCK ({none: true}); missing or empty throws (STOCK_MISSING).
   * data.hosts = {a2: {zd2: base64}, r48: {zd2: base64}}: BOTH one-capture
   * hosts (HOSTS, layout 6) or BOTH hosts that take several captures
   * (SET_HOSTS, layout 7), each at its pinned sha256. env.layout says which
   * (6 or 7); a layout-7 host's entry carries its regions and its CAP.
   */
  function makeEnv(data) {
    if (!data || !data.hosts || !data.signals) throw new Error('data bundle missing or incomplete (run tools/make_data.py)');
    var env = { hosts: {}, layout: 0, stock: { names: {}, ids: {}, bases: {} }, signals: {} };
    Object.keys(HOSTS).forEach(function (key) {
      var spec = HOSTS[key], hd = data.hosts[key];
      if (!hd) throw new Error('data bundle has no ' + spec.label + ' host');
      var zd2 = b64ToBytes(hd.zd2);
      var sha = sha256Hex(zd2);
      var layout = sha === spec.sha256 ? LAYOUT_REXP : sha === SET_HOSTS[key].sha256 ? LAYOUT7 : 0;
      if (!layout) throw new Error(spec.label + ' host sha256 ' + sha.slice(0, 16) + '... is not the pinned blank host');
      zd2CheckEnvelope(zd2, spec.label + ' host');
      var h = { spec: spec, zd2: zd2, layout: layout, blank: null, regions: null, cap: 1, identity: readIdentity(zd2), sha256: sha, fileBytes: zd2.length,
        imageKB: layout === LAYOUT7 ? SET_HOSTS[key].imageKB : spec.imageKB };
      if (layout === LAYOUT_REXP) {
        var bi = blankInfo(zd2);
        if (bi.layout !== LAYOUT_REXP || bi.kind !== (spec.rs48 ? 'rs48' : 'plain')) throw new Error(spec.label + ' host sentinel is not layout 6 / ' + (spec.rs48 ? 'rs48' : 'plain'));
        h.blank = bi;
      } else {
        var hr = hostRegions(zd2, 'the ' + spec.label + ' host');
        if (hr.kind !== spec.kind) throw new Error(spec.label + ' host is of the other kind');
        h.regions = hr;
        h.cap = hr.cap;
      }
      env.hosts[key] = h;
    });
    if (env.hosts.a2.layout !== env.hosts.r48.layout) {
      throw new Error('the two blank hosts are not of one layout: give both one-capture hosts (layout 6) or both hosts for several captures (layout 7)');
    }
    env.layout = env.hosts.a2.layout;
    env.signals.probe = bytesToF64(b64ToBytes(data.signals.probe));
    var pluckBytes = b64ToBytes(data.signals.pluck), pluckSha = sha256Hex(pluckBytes);
    env.signals.pluck = bytesToF64(pluckBytes);
    if (data.signals.probeSha256 && sha256Hex(b64ToBytes(data.signals.probe)) !== data.signals.probeSha256) throw new Error('probe signal checksum mismatch');
    if (data.signals.pluckSha256 && pluckSha !== data.signals.pluckSha256) throw new Error('pluck signal checksum mismatch');
    // the level signal (spec §5.8 step 1) is MADE here from the shipped pluck;
    // both are pinned, because they decide the level step and so the built
    // bytes. (The byte view assumes a little-endian machine, as bytesToF64 does.)
    if (pluckSha !== LEVEL_PLUCK_SHA256) throw new Error('pluck signal sha256 ' + pluckSha.slice(0, 16) + '... is not the pinned gate pluck (run tools/make_data.py)');
    env.signals.warm = warmPluck(env.signals.pluck);
    var warmSha = sha256Hex(new Uint8Array(env.signals.warm.buffer, env.signals.warm.byteOffset, env.signals.warm.byteLength));
    if (warmSha !== LEVEL_WARM_SHA256) throw new Error('level signal sha256 ' + warmSha.slice(0, 16) + '... is not the pinned warm pluck (spec §5.8)');
    env.stock = stockFromData(data.stock);
    env.stock.count = (!env.stock.none && data.stock.files) >>> 0;
    env.icons = loadIcons(data.icons);
    root.NAMB_ENV = env;                 // validateName(name) reads the stock names from here
    return env;
  }

  // =====================================================================
  // the whole per-capture pipeline (nam_pack.corpus_one with --ring-exp-db 1
  // --probe-gate --levels 0, plus the prototype's user-facing checks)
  // =====================================================================
  function tick() { return new Promise(function (r) { setTimeout(r, 0); }); }

  function textOf(bytes) {
    if (typeof TextDecoder !== 'undefined') return new TextDecoder('utf-8', { fatal: true }).decode(bytes);
    return Buffer.from(bytes).toString('utf8');
  }

  // The §5.5 gate's numbers on one signal (nam_pack._fid): yf = the float
  // model's output, yk = the int16 emulation's (which already carries
  // `oscale`, applied in float32 as the kernel does). BOTH sides carry the
  // scale: the float side is multiplied here by the same table value, as a
  // float64, before the ESR and before the Fix D test. The ESR is then the
  // same as at step 0; a gate that scaled one side only would read 0.14 at
  // -4 dB. fixdHits counts the float outputs that would reach Fix D with
  // VOL at 100: |y * oscale| * 1.5 >= 8 (it was |y| >= 8 until core 0.4.0,
  // which ignored VOL's x1.5). ymax is of the scaled output. With step 0
  // every number is what it was.
  function fidStats(yf, yk, fs, ks, rexp, levelSteps) {
    var g = levelOscale(levelSteps == null ? 0 : levelSteps);
    var fixd = 0, e = 0, p = 0;
    for (var i = 0; i < yf.length; i++) {
      var r = yf[i] * g;
      if (Math.abs(r) * LEVEL_VOL_MAX >= FIXD_LIMIT) fixd++;
      var dd = r - yk[i];
      e += dd * dd;
      p += r * r;
    }
    var xm = 0;
    for (i = 0; i < fs.xmax.length; i++) xm = Math.max(xm, fs.xmax[i] / Math.pow(2, rexp[i]));
    return { esr: p > 0 ? e / p : Infinity, xclip: ks.xclip, zsat: ks.zsat, accOverflow: ks.accOverflow,
      xmax: xm, ringHeadroomDb: db(RING_LIMIT / Math.max(xm, 1e-12)), ymax: fs.ymax * g, fixdHits: fixd };
  }

  /**
   * processCapture(bytes, fileName, env, onProgress, opts) -> Result (never
   * rejects for a bad capture).
   * opts.fixedRingExp: an exponent array to use instead of choosing (the
   *   vector check of spec §5.6).
   * opts.fixedLevelSteps: FOR TESTS. The output level step (spec §5.8) is
   *   MEASURED by default, always, with no user switch: one capture must
   *   give one effect. A number here (an integer -36..+36) pins the step
   *   instead and nothing is measured, like the reference's --level-steps N.
   *   0 pins oscale 1.0, the bytes from before the rule: that is how a test
   *   compares a build with a reference output cut without a level option.
   *   null or absent = measure.
   */
  async function processCapture(bytes, fileName, env, onProgress, opts) {
    opts = opts || {};
    var t0 = Date.now();
    var prog = onProgress || function () {};
    var res = {
      fileName: fileName, sha256: sha256Hex(bytes), bytes: bytes.length,
      verdict: 'refused', refusal: null, checks: [], meta: {}, engines: null, analysis: null, timings: {}
    };
    var internal = {};
    Object.defineProperty(res, '_internal', { value: internal, enumerable: false });
    function done(ref) {
      res.refusal = ref || null;
      res.verdict = ref ? 'refused' : 'ready';
      res.timings.ms = Date.now() - t0;
      prog(1, ref ? 'refused' : 'ready');
      return res;
    }
    try {
      prog(0.01, 'reading');
      if (opts.fixedLevelSteps != null) levelOscale(opts.fixedLevelSteps);   // a bad pinned step is a caller's error
      var text;
      try { text = textOf(bytes); } catch (e) {
        res.checks.push({ key: 'json', label: 'Readable NAM file (JSON)', status: 'fail', detail: 'not UTF-8 text' });
        return done(refusal('not-nam', 'not UTF-8 text'));
      }
      var p = parseCapture(text);
      res.checks = p.checks;
      res.meta = p.meta;
      if (!p.ok) return done(p.refusal);

      // sample rate -> engines (sketch Step2 + Refusals "rate")
      var sr = p.sampleRate;
      var srNote;
      if (sr == null) { srNote = 'no sample rate in the file; the NAM trainer default is 48 kHz'; sr = 48000; }
      if (sr !== 48000 && sr !== 44100) {
        res.checks.push({ key: 'rate', label: 'Sample rate 44.1 or 48 kHz', status: 'fail', detail: 'sample_rate ' + sr });
        return done(refusal('rate', 'sample_rate ' + sr, 'This capture was made at ' + (sr / 1000) + " kHz. The pedal's NAM engines take captures made at 44.1 or 48 kHz."));
      }
      res.sampleRate = sr;
      res.checks.push({ key: 'rate', label: 'Sample rate 44.1 or 48 kHz', status: srNote ? 'warn' : 'pass',
        detail: srNote || (sr === 48000 ? '48 kHz (the pedal runs at 44.1 kHz)' : '44.1 kHz, the pedal\'s own rate') });
      res.engines = {
        r48: engineInfo(env, 'r48', sr === 48000, sr === 48000,
          sr === 48000 ? 'Resamples inside the effect: truest to a 48 kHz capture, heavier on the DSP' :
            'Only for 48 kHz captures'),
        a2: engineInfo(env, 'a2', true, sr === 44100,
          sr === 48000 ? 'Lighter: runs the 48 kHz model at 44.1 kHz, a slight tonal shift (~8.8 % time stretch)' :
            'Runs the capture at its own rate')
      };

      // v0.10 preparation: rechannel rescale + exponents (spec §5.6)
      prog(0.03, 'measuring headroom');
      var rr = rechannelRescale(p.net);
      var net = rr.net;
      var fsProbe = {};
      var yfProbe = await forwardFloat(net, env.signals.probe, fsProbe, async function (l, n) {
        prog(0.03 + 0.25 * (l + 1) / n, 'measuring headroom'); await tick();
      });
      var rexp = opts.fixedRingExp ? opts.fixedRingExp.slice() : chooseRingExpFromStats(fsProbe, MARGIN_DB);
      res.checks.push({ key: 'rech', label: 'Input weights fit (rechannel < 1.9)', status: rr.a < 1 ? 'warn' : 'pass',
        detail: rr.a < 1 ? 'rescaled by ' + db(rr.a).toFixed(2) + ' dB (the sound is unchanged)' : 'max |rechannel| ' + maxAbs(p.net.rech).toFixed(3) });
      var maxE = Math.max.apply(null, rexp);
      if (maxE > 8) {
        res.checks.push({ key: 'rexp', label: 'Headroom exponents within the kernel\'s 8', status: 'fail', detail: rexp.join('') });
        return done(refusal('pack', 'ring exponents ' + rexp.join('') + ' exceed the kernel\'s 8'));
      }
      res.checks.push({ key: 'rexp', label: 'Per-layer headroom (ring exponents)', status: 'pass', detail: rexp.join('') });

      // the output level step (spec §5.8): measured on the warm pluck, on the
      // net as it will be packed; the peak guard reads the probe pass above.
      // Always on. opts.fixedLevelSteps (tests) pins the step instead.
      var lv;
      if (opts.fixedLevelSteps != null) {
        lv = levelFixed(opts.fixedLevelSteps);
      } else {
        prog(0.28, 'measuring the level');
        try {
          lv = await measureLevel(net, env, fsProbe.ymax, async function (l, n) {
            prog(0.28 + 0.08 * (l + 1) / n, 'measuring the level'); await tick();
          });
        } catch (e) {
          if (!(e instanceof LevelError)) throw e;
          res.checks.push({ key: 'level', label: 'Output level matched', status: 'fail', detail: e.message });
          return done(refusal('pack', 'no level step: ' + e.message));
        }
      }
      res.checks.push({ key: 'level', label: 'Output level matched', status: (lv.clamped || lv.guarded) ? 'warn' : 'pass', detail: levelLine(lv) });

      // pack both layouts, hb guard, kernel validation, splice into both hosts
      prog(0.37, 'packing');
      var pk = {};
      try {
        pk.a2 = pack(net, false, rexp, lv.steps);
        pk.r48 = pack(net, true, rexp, lv.steps);
      } catch (e) {
        res.checks.push({ key: 'pack', label: 'Weights fit the fixed-point format', status: 'fail', detail: e.message });
        return done(refusal('pack', e.message));
      }
      var hbq = pk.a2.q.hb;
      if (!(Math.abs(hbq) < 8)) {
        res.checks.push({ key: 'pack', label: 'Weights fit the fixed-point format', status: 'fail', detail: 'folded head bias ' + hbq.toPrecision(3) });
        return done(refusal('pack', 'folded head bias ' + hbq.toPrecision(3) + ' fails the kernel guard |hb| < 8'));
      }
      var kv = kernelValidate(pk.a2.words, false).concat(kernelValidate(pk.r48.words, true));
      if (kv.length) {
        res.checks.push({ key: 'pack', label: 'Weights fit the fixed-point format', status: 'fail', detail: kv.join('; ') });
        return done(refusal('pack', kv.join('; ')));
      }
      var minShift = Math.min.apply(null, pk.a2.q.layers.map(function (L) { return Math.min(L.s, L.s1); }));
      res.checks.push({ key: 'pack', label: 'Weights fit the fixed-point format', status: 'pass',
        detail: pk.a2.used + ' of ' + BLOB_WORDS + ' blob words; arena ' + (pk.a2.arenaNeed / 1024).toFixed(1) + ' KB; min weight shift ' + minShift });
      // the container check: a splice into the hosts this environment holds.
      // Layout 6: the capture's own effect, kept for buildOutputs. Layout 7:
      // the capture ALONE in each host under the host's identity, a test
      // article that proves the image and the container code on these bytes
      // and is then dropped (buildSetOutputs splices the selection itself).
      var spl = {}, set = env.layout === LAYOUT7;
      try {
        if (set) {
          var ck = res.sha256.slice(0, 32);
          spliceSet(env.hosts.a2.zd2, [imageOfPack(pk.a2, false).words], [ck], [SET_CHECK_LABEL], null);
          spliceSet(env.hosts.r48.zd2, [imageOfPack(pk.r48, true).words], [ck], [SET_CHECK_LABEL], null);
        } else {
          spl.a2 = spliceBytes(env.hosts.a2.zd2, pk.a2.words, pk.a2.used);
          spl.r48 = spliceBytes(env.hosts.r48.zd2, pk.r48.words, pk.r48.used);
        }
      } catch (e) {
        res.checks.push({ key: 'splice', label: 'Splices into the blank hosts', status: 'fail', detail: e.message });
        return done(refusal(e instanceof PackError ? 'pack' : 'error', e.message));
      }
      res.checks.push({ key: 'splice', label: 'Splices into both blank hosts (container checks)', status: 'pass',
        detail: set ? 'alone in each host: envelope, CRC, the index and the image read back, nothing else changed' : 'envelope, CRC, region readback, nothing else changed' });
      internal.net = net; internal.rexp = rexp; internal.rechA = rr.a; internal.packs = pk;
      internal.level = lv; internal.levelSteps = lv.steps;
      // (layout 7: no splice is kept; a capture's files exist only as built)
      internal.splice = set ? null : { a2: { zd2: spl.a2, crc: zd2Crc(spl.a2), sha256: sha256Hex(spl.a2) },
        r48: { zd2: spl.r48, crc: zd2Crc(spl.r48), sha256: sha256Hex(spl.r48) } };

      // the §5.5 gate: pluck (0 dB) + probe (full scale), float vs int16,
      // run AFTER the level step and with `oscale` on both sides (§5.8)
      prog(0.38, 'checking the sound (pluck)');
      var fsP = {}, ksP = {};
      var yfP = await forwardFloat(net, env.signals.pluck, fsP, async function (l, n) {
        prog(0.38 + 0.08 * (l + 1) / n, 'checking the sound (pluck)'); await tick();
      });
      var ykP = await forwardKernel(net, env.signals.pluck, rexp, ksP, async function (l, n) {
        prog(0.46 + 0.12 * (l + 1) / n, 'checking the sound (pluck)'); await tick();
      }, lv.steps);
      var ksR = {};
      var ykR = await forwardKernel(net, env.signals.probe, rexp, ksR, async function (l, n) {
        prog(0.58 + 0.40 * (l + 1) / n, 'checking the sound (full-scale probe)'); await tick();
      }, lv.steps);
      var gP = fidStats(yfP, ykP, fsP, ksP, rexp, lv.steps);
      var gR = fidStats(yfProbe, ykR, fsProbe, ksR, rexp, lv.steps);
      res.analysis = { exponents: rexp.join(''), rechannelA: rr.a, rechannelDb: rr.a < 1 ? db(rr.a) : null,
        // the output level (§5.8): {rule, how, steps, db, oscaleBits} and, for a
        // measured step, levelDb, wantDb, the clamp/guard facts and the margins
        level: lv,
        gate: { pluck: gP, probe: gR }, limitEsr: GATE_ESR, marginDb: MARGIN_DB,
        blobWordsUsed: pk.a2.used, splice: set ? null : { a2: { crcHex: hex8(internal.splice.a2.crc), sha256: internal.splice.a2.sha256 },
          r48: { crcHex: hex8(internal.splice.r48.crc), sha256: internal.splice.r48.sha256 } } };
      var why = [];
      [['probe', gR], ['pluck', gP]].forEach(function (pr) {
        var nm = pr[0], g = pr[1];
        if (g.esr > GATE_ESR) why.push(nm + ' ESR ' + g.esr.toExponential(2) + ' > 0.01');
        if (g.xclip) why.push(g.xclip + ' ring clips on the ' + nm);
        if (g.accOverflow) why.push('int32 accumulator overflow on the ' + nm);
        if (g.fixdHits) why.push(g.fixdHits + ' ' + nm + ' output samples reach Fix D at VOL 100 (|y| x 1.5 >= 8)');
      });
      res.checks.push({ key: 'gate', label: 'Sounds right in the pedal-engine copy (ESR ≤ 0.010, no clipping)',
        status: why.length ? 'fail' : 'pass',
        detail: 'pluck ESR ' + gP.esr.toExponential(2) + ', full-scale probe ESR ' + gR.esr.toExponential(2) + ', ' + (gP.xclip + gR.xclip) + ' clips' });
      if (why.length) return done(refusal('fidelity', why.join('; ')));
      res.checks.push({ key: 'size', label: 'Fits the pedal\'s per-effect load limit', status: 'pass',
        detail: 'NAM 44.1k image ' + env.hosts.a2.imageKB + ' KB, NAM 48k ' + env.hosts.r48.imageKB + ' KB; proven up to ' + LOAD_LIMIT_PROVEN_KB + ' KB' });
      res.checks.push({ key: 'pedal', label: 'Room on the pedal / not already installed', status: 'skip',
        detail: 'not checked: this prototype never talks to the pedal' });
      return done(null);
    } catch (e) {
      res.checks.push({ key: 'error', label: 'Internal error', status: 'fail', detail: String(e && e.message || e) });
      return done(refusal('error', String(e && e.message || e).slice(0, 200)));
    }
  }

  function engineInfo(env, key, available, recommended, reason) {
    var h = HOSTS[key];
    return { key: key, label: h.label, available: available, recommended: recommended, reason: reason,
      dspload: h.dspload, fileKB: +(env.hosts[key].fileBytes / 1024).toFixed(1), imageKB: env.hosts[key].imageKB };
  }
  function hex8(v) { return '0x' + ('00000000' + (v >>> 0).toString(16)).slice(-8); }

  // =====================================================================
  // the capture identity (spec §9, ruled 2026-10-01; the reference is
  // nam_pack.capture_identity / capture_name, the vectors are
  // testvectors/identity_vectors.json):
  //   C = sha256(capture file bytes)        K = C[0:16], the capture key
  //   H = sha256(K || ASCII(host kind))     host kind 'nam-a2' | 'nam-48k'
  //   id   = 0x04001400 + (uint32_be(H[0:4]) & 0x3FF), next free on a clash
  //   file = 'WFN' + 5 characters of uint32_be(H[4:8]) >>> 7, 5 bits each
  //          (0.8.0, ruled 2026-10-11; 'NM' + 6 of >>> 2 before)
  //   name = the capture's file name cut to 11 characters
  //   version = the host's, untouched
  // =====================================================================
  function hexToBytes(hex) {
    var out = new Uint8Array(hex.length >> 1);
    for (var i = 0; i < out.length; i++) out[i] = parseInt(hex.substr(2 * i, 2), 16);
    return out;
  }
  function hostKindOf(k) {
    if (HOSTS[k]) return HOSTS[k].hostKind;
    for (var e in HOSTS) if (HOSTS[e].hostKind === k) return k;
    throw new Error('unknown host kind ' + k);
  }
  /**
   * deriveIdentity(shaHex, hostKind, resident, env) — the id and pedal
   * filename of one capture on one host kind (an engine key works too).
   * shaHex: the capture file's sha256 (64 hex), or its 32-hex key.
   * resident: the pedal's effect list, {FILENAME (8 chars, no extension): id}
   * as a Map or an object; none = "no pedal known".
   *   - the filename is resident: the capture IS installed, its id is the
   *     resident one;
   *   - else the canonical id unless a resident or a stock effect has it,
   *     then the next free id upwards, wrapping inside the band;
   *   - no free id: throws.
   * env (or the last makeEnv's): its stock list is required, or NO_STOCK
   * ({stock: NAMB.NO_STOCK}); without one this throws STOCK_MISSING. The
   * same holds for deriveName, validateName, setName, finalName,
   * deriveSetIdentity, buildOutputs and buildSetOutputs.
   */
  function deriveIdentity(shaHex, hostKind, resident, env) {
    if (typeof shaHex !== 'string' || !/^([0-9a-f]{32}|[0-9a-f]{64})$/i.test(shaHex)) throw new Error('the capture hash must be 32 or 64 hex characters');
    var kind = hostKindOf(hostKind);
    var keyHex = shaHex.slice(0, 32).toLowerCase();
    var key = hexToBytes(keyHex);
    var pre = new Uint8Array(16 + kind.length);
    pre.set(key, 0);
    for (var i = 0; i < kind.length; i++) pre[16 + i] = kind.charCodeAt(i);
    var hashHex = sha256Hex(pre), h = hexToBytes(hashHex);
    var slot = ((h[2] << 8) | h[3]) & (ID_BAND_SIZE - 1);
    var f = ((h[4] * 0x1000000) + ((h[5] << 16) | (h[6] << 8) | h[7])) >>> 7;   // the top 25 bits
    var fn = FILE_PREFIX;
    for (i = 0; i < FILE_CHARS; i++) fn += FILE_ALPHABET.charAt((f >>> (20 - 5 * i)) & 31);
    var base = ((GROUP_PREAMP << 24) | ID_BAND_LO) >>> 0;
    var out = { key: keyHex, hostKind: kind, hashHex: hashHex, slot: slot, canonicalId: base + slot,
      filename: fn, installed: false };
    var res = {}, taken = {};
    function add(name, id) { res[String(name).toUpperCase()] = id >>> 0; taken[id >>> 0] = 1; }
    if (resident && typeof resident.forEach === 'function') resident.forEach(function (id, name) { add(name, id); });
    else if (resident) Object.keys(resident).forEach(function (name) { add(name, resident[name]); });
    var stock = stockOf(env).ids;
    if (Object.prototype.hasOwnProperty.call(res, fn)) {
      out.id = res[fn]; out.installed = true;
    } else {
      var id = -1;
      for (var t = 0; t < ID_BAND_SIZE; t++) {
        var cand = base + ((slot + t) % ID_BAND_SIZE);
        if (!taken[cand] && !stock[cand]) { id = cand; break; }
      }
      if (id < 0) throw new Error('no free id left in the NAM capture band 0x04001400-0x040017FF');
      out.id = id;
    }
    out.idHex = hex8(out.id);
    out.low16 = out.id & 0xFFFF;
    return out;
  }
  /**
   * isCaptureFilename(name) — is this pedal filename (no extension, any case)
   * a generated capture file's? The full 8-character pattern decides, never
   * the 'WFN' prefix: the blank host files WFNAM48 / WFNAM44 are not ones.
   * (The retired v0.12 host WFNAMR48 DOES fit the pattern; the exact-name
   * lookup of deriveIdentity is what decides "installed", not this test.)
   */
  function isCaptureFilename(name) {
    return typeof name === 'string' && FILE_RE.test(name.toUpperCase());
  }
  // spec §9.4 steps 1 to 3 (shared by deriveName and the labels of an effect
  // of several captures; nam_set._clean): the last path component, minus one
  // trailing ".nam"; NFKD, printable ASCII only; runs of spaces to one, trimmed
  function cleanFileName(fileName) {
    var base = String(fileName).replace(/\\/g, '/');
    base = base.slice(base.lastIndexOf('/') + 1);
    if (base.slice(-4).toLowerCase() === '.nam') base = base.slice(0, -4);
    var nf = typeof base.normalize === 'function' ? base.normalize('NFKD') : base;
    var s = '';
    for (var i = 0; i < nf.length; i++) { var c = nf.charCodeAt(i); if (c >= 0x20 && c <= 0x7E) s += nf.charAt(i); }
    return s.split(' ').filter(function (p) { return p; }).join(' ');
  }
  /**
   * deriveName(fileName, pedalFilename, env) — the header name @100: the
   * capture's file name cut to 11 characters (display only, never identity).
   * Last path component, minus one trailing ".nam"; NFKD, printable ASCII
   * only; runs of spaces to one, trimmed; 11 characters, right-trimmed; a
   * stock effect's name (compared without case) becomes 7 characters +
   * " NAM"; empty becomes the pedal filename.
   */
  function deriveName(fileName, pedalFilename, env) {
    var s = cleanFileName(fileName);
    var name = s.slice(0, NAME_MAX).replace(/ +$/, '');
    var stock = stockOf(env).namesLower;
    function isStock(n) { return Object.prototype.hasOwnProperty.call(stock, n.toLowerCase()); }
    if (name && isStock(name)) name = s.slice(0, NAME_MAX - 4).replace(/ +$/, '') + ' NAM';
    if (!name || isStock(name)) name = pedalFilename;
    return name;
  }
  function validateName(name, env) {
    if (typeof name !== 'string' || name.length === 0) return 'The effect has no name';
    if (name.length > 11) return 'At most 11 characters (the pedal header holds 11)';
    if (!asciiOk(name, 1, 11)) return 'Letters, digits, spaces and basic punctuation only (plain ASCII)';
    if (name.trim() !== name) return 'No leading or trailing spaces';
    if (stockOf(env).names[name]) return '"' + name + '" is the name of a stock Zoom effect';
    return null;
  }

  // =====================================================================
  // the icon (spec §9.6, ruled 2026-10-03): two frames, 97x97 then
  // 128x128, dark, invert flag 1. "NAM" left of the LED dot and the
  // engine's rate ("44.1k" / "48k") right of it, four knobs, a name plate
  // with the capture's NAME, the footswitch, the WF badge, and "+CAB" at
  // the bottom left when the capture includes a cabinet (gear_type amp_cab
  // or amp_pedal_cab). A port of the composer in nam_icon.py; the vectors
  // are the icon vectors file. No font is rendered here: everything that
  // does not depend on the name is four finished pictures in the icon
  // data, the name's glyphs are 1-bit strikes in it (rendered once, with
  // Pillow, by nam_icon.py), and everything below is integer logic.
  //   zic = compose(name, host kind, cab; icon data)
  // A frame is kept in the .ZIC's own layout: stripes of 8 pixel rows,
  // byte n = column n % w of stripe n // w, bit k = row k of the stripe;
  // a set bit is a dark pixel.
  // =====================================================================
  function zicParse(data) {
    var errs = checkZic(data);
    if (errs.length) throw new Error('icon out of invariant: ' + errs.join('; '));
    var dlen = rd32(data, 4), frames = [], pos = 8 + dlen;
    for (var i = 0; i < dlen / 4; i++) {
      var w = data[8 + 4 * i] | (data[9 + 4 * i] << 8), h = data[10 + 4 * i] | (data[11 + 4 * i] << 8);
      if (w === 0 || h === 0) break;
      var n = w * (((h - 1) >> 3) + 1);
      frames.push({ w: w, h: h, buf: data.slice(pos, pos + n) });
      pos += n;
    }
    var fo = 8 + 4 * frames.length;
    return { header: data.slice(0, 8 + dlen), frames: frames, invert: fo + 2 <= 8 + dlen ? (data[fo] | (data[fo + 1] << 8)) : null };
  }
  function loadIcons(ic) {
    if (!ic || typeof ic.json !== 'string') throw new Error('data bundle has no icon data (run tools/make_data.py)');
    var raw = new Uint8Array(ic.json.length);
    for (var i = 0; i < raw.length; i++) {
      var c = ic.json.charCodeAt(i);
      if (c > 0x7E) throw new Error('icon data is not ASCII');
      raw[i] = c;
    }
    var sha = sha256Hex(raw);
    if (sha !== ICON_DATA_SHA256) throw new Error('icon data sha256 ' + sha.slice(0, 16) + '... is not the pinned icon data');
    var d = JSON.parse(ic.json);
    if (d.format !== ICON_DATA_FORMAT) throw new Error('icon data format ' + d.format + ', this core reads ' + ICON_DATA_FORMAT);
    if (!d.styles[d.build_style]) throw new Error('icon data: build_style names no style');
    var icons = { sha256: sha, buildStyle: d.build_style, styles: {}, fontData: d.fonts, fonts: {} };
    Object.keys(d.styles).forEach(function (sn) {
      var st = d.styles[sn], art = {};
      Object.keys(HOSTS).forEach(function (hk) {
        ['', ICON_CAB_SUFFIX].forEach(function (sfx) {
          if (!st.art[HOSTS[hk].hostKind + sfx]) throw new Error('icon style ' + sn + ' has no picture ' + HOSTS[hk].hostKind + sfx);
        });
      });
      Object.keys(st.art).forEach(function (key) {
        var a = { header: b64ToBytes(st.art[key].header), frames: st.art[key].frames.map(b64ToBytes) };
        if (a.frames.length !== st.frames.length) throw new Error('icon style ' + sn + ': frame count mismatch');
        var all = [a.header].concat(a.frames), total = 0, whole, off = 0;
        all.forEach(function (b) { total += b.length; });
        whole = new Uint8Array(total);
        all.forEach(function (b) { whole.set(b, off); off += b.length; });
        var z = zicParse(whole);                        // the gate, and the frame sizes
        st.frames.forEach(function (fr, k) {
          if (!z.frames[k] || z.frames[k].w !== fr.w || z.frames[k].h !== fr.h) throw new Error('icon style ' + sn + ': frame sizes differ');
        });
        if (z.invert !== 1) throw new Error('icon style ' + sn + ' picture ' + key + ': the invert flag is not 1');
        art[key] = a;
      });
      st.frames.forEach(function (fr) {
        var r = fr.rule;
        if (r.kind !== 'plan' || r.max_lines !== 3) throw new Error('icon style ' + sn + ': this core lays a name out by the "plan" rule on up to 3 lines');
        if (!(r.smin <= r.thresh && r.thresh <= r.cap2 && r.cap2 <= r.smax)) throw new Error('icon style ' + sn + ': the rule\'s sizes are out of order');
        for (var s = r.smin; s <= r.smax; s++) {
          var f = iconFont(icons, r.glyphs, s);
          if (typeof r.gap[String(s)] !== 'number') throw new Error('icon style ' + sn + ': no line gap for size ' + s);
          if (!(f.bw[0x48 - 0x20] > 0)) throw new Error('icon data: glyph table ' + r.glyphs + ':' + s + ' has no H');
        }
      });
      icons.styles[sn] = { frames: st.frames, art: art };
    });
    return icons;
  }
  function iconFont(icons, glyphs, size) {
    var key = glyphs + ':' + size;
    if (icons.fonts[key]) return icons.fonts[key];
    var set = icons.fontData[glyphs], rec = set && set.sizes[String(size)];
    if (!rec) throw new Error('icon data has no ' + glyphs + ' glyphs of size ' + size);
    var f = { adv: rec.adv, dx: rec.dx, dy: rec.dy, bw: rec.bw, bh: rec.bh, bits: b64ToBytes(rec.bits), off: [] };
    var o = 0;
    for (var i = 0; i < 95; i++) { f.off.push(o); o += f.bh[i] * ((f.bw[i] + 7) >> 3); }
    if (o !== f.bits.length || f.adv.length !== 95) throw new Error('icon data: glyph table ' + key + ' is malformed');
    icons.fonts[key] = f;
    return f;
  }
  // OR one glyph strike into the frame, its pen at (x, y); pixels outside
  // the frame are dropped, and so are pixels outside `clip` ([x0, y0, x1,
  // y1], all inclusive)
  function iconBlit(buf, w, h, f, code, x, y, clip) {
    var i = code - 0x20, gw = f.bw[i], gh = f.bh[i], stride = (gw + 7) >> 3, off = f.off[i];
    var ox = x + f.dx[i], oy = y + f.dy[i];
    for (var gy = 0; gy < gh; gy++) {
      var Y = oy + gy;
      if (Y < 0 || Y >= h || Y < clip[1] || Y > clip[3]) continue;
      var row = off + gy * stride, base = (Y >> 3) * w, bit = 1 << (Y & 7);
      for (var gx = 0; gx < gw; gx++) {
        if (f.bits[row + (gx >> 3)] & (0x80 >> (gx & 7))) {
          var X = ox + gx;
          if (X >= 0 && X < w && X >= clip[0] && X <= clip[2]) buf[base + X] |= bit;
        }
      }
    }
  }
  // one line, glyph by glyph: each struck `strikes` times one pixel apart,
  // the pen moving by advance + (strikes - 1) + tracking
  function iconDrawLine(buf, w, h, f, text, x, y, strikes, tracking, clip) {
    var pen = x;
    for (var i = 0; i < text.length; i++) {
      var code = text.charCodeAt(i);
      for (var k = 0; k < strikes; k++) iconBlit(buf, w, h, f, code, pen + k, y, clip);
      pen += f.adv[code - 0x20] + (strikes - 1) + tracking;
    }
  }
  // ---- the name rule ("plan", rule A; nam_icon.py lay_plan) ----
  //  1. up to three lines, broken at spaces; the largest size that fits the
  //     plate wins, then fewer lines;
  //  2. if that leaves the text below the legible size (rule.thresh), it may
  //     also break after a separator (cost 2), at a letter/digit or
  //     lower/upper change (cost 4) or inside a word (cost 12); such a
  //     layout is taken only when it is at least two sizes larger, counted
  //     up to the legible size, than the space-only one;
  //  3. if nothing fits: the smallest size, the layout that overflows least,
  //     drawn anyway and clipped to the plate.
  function iconAlpha(c) { return (c >= 65 && c <= 90) || (c >= 97 && c <= 122); }
  function iconDigit(c) { return c >= 48 && c <= 57; }
  // where a new line may start: [index, cost, the break eats a space]
  function iconBreakPoints(name) {
    var out = [];
    for (var i = 1; i < name.length; i++) {
      var a = name.charAt(i - 1), b = name.charAt(i), ca = name.charCodeAt(i - 1), cb = name.charCodeAt(i);
      if (b === ' ') out.push([i, 0, true]);
      else if (a === ' ') continue;
      else if (ICON_SEPARATORS.indexOf(a) >= 0) out.push([i, ICON_COST_SEPARATOR, false]);
      else if (ICON_SEPARATORS.indexOf(b) >= 0) continue;          // never start a line with a separator
      else if ((iconAlpha(ca) && iconDigit(cb)) || (iconDigit(ca) && iconAlpha(cb)) ||
               (ca >= 97 && ca <= 122 && cb >= 65 && cb <= 90)) out.push([i, ICON_COST_CHANGE, false]);
      else out.push([i, ICON_COST_WORD, false]);
    }
    return out;
  }
  function iconSplit(name, cuts) {
    var out = [], start = 0;
    cuts.forEach(function (c) { out.push(name.slice(start, c[0])); start = c[0] + (c[2] ? 1 : 0); });
    out.push(name.slice(start));
    return out;
  }
  // ink extents of one struck, tracked line with its pen at (0, 0):
  // [x0, x1, top, bottom], x1 and bottom exclusive; never shorter than a
  // capital H
  function iconLineMetrics(f, text, strikes, tracking) {
    var pen = 0, x0 = null, x1 = null, top = null, bot = null;
    for (var i = 0; i < text.length; i++) {
      var g = text.charCodeAt(i) - 0x20;
      if (f.bw[g] > 0) {
        var l = pen + f.dx[g], r = l + f.bw[g] + strikes - 1, t = f.dy[g], b = t + f.bh[g];
        x0 = x0 === null ? l : Math.min(x0, l);
        x1 = x1 === null ? r : Math.max(x1, r);
        top = top === null ? t : Math.min(top, t);
        bot = bot === null ? b : Math.max(bot, b);
      }
      pen += f.adv[g] + strikes - 1 + tracking;
    }
    var hi = 0x48 - 0x20, capTop = f.dy[hi], base = capTop + f.bh[hi];
    if (x0 === null) { x0 = 0; x1 = 0; top = capTop; bot = base; }
    return [x0, x1, Math.min(top, capTop), Math.max(bot, base)];
  }
  // the stage-2 key: four numbers, then the line lengths, compared the way
  // Python compares tuples
  function iconKeyGreater(a, b) {
    for (var i = 0; i < 4; i++) if (a[i] !== b[i]) return a[i] > b[i];
    var p = a[4], q = b[4];
    for (i = 0; i < p.length && i < q.length; i++) if (p[i] !== q[i]) return p[i] > q[i];
    return p.length > q.length;
  }
  function iconLayPlan(name, rule, icons) {
    var x0 = rule.box[0], y0 = rule.box[1], bw = rule.box[2] - x0 + 1, bh = rule.box[3] - y0 + 1;   // the box is inclusive
    var strikes = rule.strikes, tracking = rule.tracking, smin = rule.smin, smax = rule.smax, thresh = rule.thresh;
    var bps = iconBreakPoints(name), combos = [[]], i, j;
    // every layout of up to three lines, in this order: no cut; one cut,
    // left to right; two cuts, the first left to right, then the second
    for (i = 0; i < bps.length; i++) combos.push([bps[i]]);
    for (i = 0; i < bps.length; i++) for (j = i + 1; j < bps.length; j++) combos.push([bps[i], bps[j]]);
    var layouts = [];
    combos.forEach(function (combo) {
      var lines = iconSplit(name, combo), cost = 0, word = false, shortest = Infinity;
      for (var k = 0; k < lines.length; k++) {
        if (!lines[k]) return;
        shortest = Math.min(shortest, lines[k].length);
      }
      combo.forEach(function (c) { cost += c[1]; if (c[1] >= ICON_COST_WORD) word = true; });
      if (word && shortest < 2) return;                 // no orphan letter from a mid-word break
      layouts.push({ lines: lines, cost: cost });
    });
    var cache = {};
    function measure(lines, size) {
      var f = iconFont(icons, rule.glyphs, size), ms = [], width = 0, height = 0, gap = rule.gap[String(size)];
      lines.forEach(function (t) {
        var key = size + ':' + t;
        if (!cache[key]) cache[key] = iconLineMetrics(f, t, strikes, tracking);
        var m = cache[key];
        ms.push(m);
        width = Math.max(width, m[1] - m[0]);
        height += m[3] - m[2];
      });
      return { lines: lines, size: size, ms: ms, gap: gap, width: width, height: height + gap * (lines.length - 1), fit: false };
    }
    function fit(lines, cap) {
      for (var size = cap; size >= smin; size--) {
        var r = measure(lines, size);
        if (r.width <= bw && r.height <= bh) { r.fit = true; return r; }
      }
      return null;
    }
    function record(r, cost) {
      var y = y0 + Math.floor((bh - r.height) / 2), out = [];   // floor, also when negative
      for (var k = 0; k < r.lines.length; k++) {
        var m = r.ms[k], w = m[1] - m[0];
        out.push([r.lines[k], x0 + Math.floor((bw - w) / 2) - m[0], y - m[2], w]);
        y += (m[3] - m[2]) + r.gap;
      }
      return { rule: 'plan', size: r.size, fit: r.fit, strikes: strikes, tracking: tracking, cost: cost, lines: out };
    }
    // stage 1: breaks at spaces only; the largest size wins, then fewer lines
    var best = null, r, L;
    for (i = 0; i < layouts.length; i++) {
      L = layouts[i];
      if (L.cost) continue;
      r = fit(L.lines, smax);
      if (r && (best === null || r.size > best.size || (r.size === best.size && L.lines.length < best.lines.length))) best = r;
    }
    if (best !== null && best.size >= thresh) return record(best, 0);
    // stage 2: other breaks allowed. Reaching the legible size comes first,
    // then the cheapest breaks, then the largest size, then the narrowest,
    // then the longer first line.
    var best2 = null, key2 = null, cost2 = 0, cap = Math.min(smax, rule.cap2);
    for (i = 0; i < layouts.length; i++) {
      L = layouts[i];
      if (!L.cost) continue;
      r = fit(L.lines, cap);
      if (!r) continue;
      var key = [Math.min(r.size, thresh), -(L.cost + (L.lines.length - 1)), r.size, -r.width,
        L.lines.map(function (t) { return t.length; })];
      if (key2 === null || iconKeyGreater(key, key2)) { best2 = r; key2 = key; cost2 = L.cost; }
    }
    if (best2 !== null && (best === null || key2[0] >= best.size + 2)) return record(best2, cost2);
    if (best !== null) return record(best, 0);
    // nothing fits: the smallest size, the layout that overflows least
    var worst = null;
    for (i = 0; i < layouts.length; i++) {
      L = layouts[i];
      r = measure(L.lines, smin);
      var over = Math.max(0, r.width - bw) + Math.max(0, r.height - bh);
      if (worst === null || over < worst.over) worst = { over: over, r: r, cost: L.cost };
    }
    return record(worst.r, worst.cost);
  }
  /** Does the capture include a cabinet, by its gear_type metadata? Exactly
   *  "amp_cab" and "amp_pedal_cab" (ruled 2026-10-03); nothing else. */
  function iconIncludesCab(gearType) {
    return gearType === 'amp_cab' || gearType === 'amp_pedal_cab';
  }
  /**
   * renderIcon(name, host, env, opts) -> {zic, style, cab, frames, sha256}
   * The .ZIC of one capture: `name` (printable ASCII; what deriveName gives)
   * on the name plate of the icon of `host` (an engine key or a host kind).
   * opts.cab: true draws the "+CAB" mark (iconIncludesCab(gear_type)).
   * frames = one layout record per frame ({rule, size, fit, strikes,
   * tracking, cost, lines: [[text, pen x, pen y, ink width], ...]}), null
   * for an empty name.
   * Byte-identical to nam_icon.py `render` (the icon vectors file).
   */
  function renderIcon(name, host, env, opts) {
    var e = env || root.NAMB_ENV, icons = e && e.icons;
    if (!icons) throw new Error('no icon data loaded');
    var o = opts || {}, kind = hostKindOf(host), sn = o.style || icons.buildStyle, st = icons.styles[sn];
    if (!st) throw new Error('unknown icon style ' + sn);
    var cab = o.cab === true, art = st.art[kind + (cab ? ICON_CAB_SUFFIX : '')];
    if (!art) throw new Error('icon style ' + sn + ' has no picture for host kind ' + kind);
    var s = String(name), i;
    for (i = 0; i < s.length; i++) {
      var c = s.charCodeAt(i);
      if (c < 0x20 || c > 0x7E) throw new Error('icon name must be printable ASCII');
    }
    var clean = s.split(' ').filter(function (p) { return p; }).join(' ');
    var total = art.header.length;
    art.frames.forEach(function (b) { total += b.length; });
    var out = new Uint8Array(total), pos = art.header.length, facts = [];
    out.set(art.header, 0);
    st.frames.forEach(function (fr, k) {
      var buf = new Uint8Array(art.frames[k]), lay = null;
      if (clean) {
        lay = iconLayPlan(clean, fr.rule, icons);
        var f = iconFont(icons, fr.rule.glyphs, lay.size);
        lay.lines.forEach(function (ln) { iconDrawLine(buf, fr.w, fr.h, f, ln[0], ln[1], ln[2], lay.strikes, lay.tracking, fr.rule.box); });
      }
      out.set(buf, pos);
      pos += buf.length;
      facts.push(lay);
    });
    var errs = checkZic(out);
    if (errs.length) throw new Error('icon out of invariant: ' + errs.join('; '));
    return { zic: out, style: sn, cab: cab, frames: facts, sha256: sha256Hex(out) };
  }

  /**
   * Build the effect files for a ready Result. Throws on any failed check.
   * opts.engine: 'a2' | 'r48'. opts.fileName: the capture's file name as the
   * user sees it now (default: the name it was checked under). opts.resident:
   * the pedal's effect list (see deriveIdentity). The id, the pedal filename
   * and the name are DERIVED here (spec §9); a caller cannot choose them.
   */
  async function buildOutputs(result, opts, env) {
    var it = result && result._internal;
    if (!result || result.verdict !== 'ready' || !it || !it.net) throw new Error('this capture is not ready to build');
    if (!env || env.layout !== LAYOUT_REXP || !it.splice) {
      throw new Error('buildOutputs builds from the one-capture hosts (layout 6); with the hosts for several captures use buildSetOutputs, for one capture too');
    }
    var key = opts.engine;
    if (!HOSTS[key]) throw new Error('unknown engine ' + key);
    if (!result.engines[key].available) throw new Error(HOSTS[key].label + ' is not available for this capture');
    var host = env.hosts[key];
    var ident = deriveIdentity(result.sha256, host.spec.hostKind, opts.resident, env);
    var id = ident.id >>> 0, fn = ident.filename;
    var name = deriveName(opts.fileName != null ? opts.fileName : result.fileName, fn, env);
    var err = validateName(name, env);
    if (err) throw new Error(err);
    if ((id >>> 24) !== GROUP_PREAMP || (id & 0x00FF0000) || (id & 0xFFFF) < ID_BAND_LO || (id & 0xFFFF) >= ID_BAND_LO + ID_BAND_SIZE) {
      throw new Error('id ' + hex8(id) + ' is outside the NAM user-capture band 0x04001400-0x040017FF');
    }
    if (!FILE_RE.test(fn)) throw new Error('filename ' + fn + ' is not WFN + 5 characters of the capture alphabet');
    var stock = stockOf(env);
    if (stock.ids[id]) throw new Error('id ' + hex8(id) + ' collides with a stock effect');
    if (stock.bases[fn + '.ZD2'] || stock.bases[fn + '.ZIC']) throw new Error('filename ' + fn + ' matches a stock file');
    var version = host.identity.version;
    // re-pack from the stored network (deterministic), with the exponents and
    // the level step processCapture settled on; re-splice, re-verify
    var lv = it.level;
    if (!lv || lv.steps !== it.levelSteps) throw new Error('this capture has no level step (spec §5.8)');
    var pk = pack(it.net, host.spec.rs48, it.rexp, lv.steps);
    if (pk.words[3] !== lv.oscaleBits) throw new Error('blob word 3 is not the level step\'s oscale word');
    var kv = kernelValidate(pk.words, host.spec.rs48);
    if (kv.length) throw new Error('kernel checks failed: ' + kv.join('; '));
    var spliced = spliceBytes(host.zd2, pk.words, pk.used);
    if (sha256Hex(spliced) !== it.splice[key].sha256) throw new Error('re-splice is not reproducible');
    // the version field @89 is not written: a capture carries its host's version
    var out = setIdentity(spliced, { id: id, name: name, group: GROUP_PREAMP, groupName: GROUP_NAME });
    // the icon (spec §9.6): the name on the plate, the engine's rate, and
    // "+CAB" when the file says the capture includes a cabinet (the .ZIC
    // only; the container's own ICON section is the host's and is not touched)
    var icon = renderIcon(name, key, env, { cab: iconIncludesCab(result.meta && result.meta.gear_type) });
    // final gate, the same the install wrapper applies (envelope + icon + identity)
    zd2CheckEnvelope(out, 'output');
    zd2Chunks(out);
    var env1 = checkEnvelope(out), zic1 = checkZic(icon.zic);
    if (env1.length) throw new Error('container envelope out of invariant: ' + env1.join('; '));
    if (zic1.length) throw new Error('icon out of invariant: ' + zic1.join('; '));
    var idr = readIdentity(out);
    if (idr.id !== id || idr.name !== name || idr.group !== GROUP_PREAMP || idr.groupName !== GROUP_NAME || idr.version !== version) {
      throw new Error('identity readback mismatch');
    }
    var bi = host.blank;
    var region = new Uint32Array(BLOB_WORDS);
    for (var i = 0; i < BLOB_WORDS; i++) region[i] = rd32(out, bi.off + 4 * i);
    for (i = 0; i < BLOB_WORDS; i++) if (region[i] !== pk.words[i]) throw new Error('blob readback mismatch');
    var sha = sha256Hex(out), crc = zd2Crc(out);
    var sidecar = {
      builder: 'NAM capture builder desk prototype ' + VERSION,
      built: new Date().toISOString(),
      source: { file: result.fileName, sha256: result.sha256, bytes: result.bytes, metadata: result.meta },
      engine: { key: key, label: host.spec.label, host_sha256: host.sha256, host_version: host.identity.version, blob_layout: 6, rs48: host.spec.rs48 },
      exponents: it.rexp.join(''),
      rechannel_rescale_a: it.rechA,
      // the output level (spec §5.8), as the reference's `splice --sidecar`
      // writes it: the rule, the step, its dB, the oscale word (blob word 3);
      // for a measured step also the level and the margins
      level: levelRecord(lv),
      identity: { id: hex8(id), canonical_id: hex8(ident.canonicalId), already_in_effect_list: ident.installed,
        group: '0x04 (Preamp)', group_name: GROUP_NAME, name: name, version: version,
        filename: fn + '.ZD2', icon: fn + '.ZIC (the name on the icon\'s plate; NAM and the engine\'s rate at the top' + (icon.cab ? '; +CAB' : '') + ')',
        capture_key: ident.key, host_kind: ident.hostKind, id_hash: ident.hashHex,
        rules: 'the splice specification §9: id, filename, name and version are derived; ' +
          'the icon is composed from the name, the engine and the capture\'s gear_type (§9.6)' },
      // the icon step: which icon data, whether +CAB was drawn (and the
      // gear_type that decided it), and per frame the layout (rule, size,
      // fit, cost, lines as [text, pen x, pen y, ink width])
      icon: { style: icon.style, cab: icon.cab, gear_type: (result.meta && result.meta.gear_type != null) ? result.meta.gear_type : null,
        data_sha256: env.icons.sha256, zic_sha256: icon.sha256, frames: icon.frames },
      // the capture reference (the patch-side reference to a capture)
      reference: { kind: 'nam', capture_sha256: result.sha256, host_kind: ident.hostKind, host_version: version,
        sample_rate: result.sampleRate || null, source: 'user' },
      output: { zd2_crc: hex8(crc), zd2_sha256: sha, zd2_bytes: out.length, zic_bytes: icon.zic.length, zic_sha256: icon.sha256 },
      gate: result.analysis && result.analysis.gate,
      reproduce: 'nam_pack.py splice <host> <capture> <out> --ring-exp ' + it.rexp.join('') +
        ' --level-steps ' + lv.steps +
        ' --id ' + hex8(id) + ' --name "' + name + '" --group 0x04 --group-name PREAMP'
    };
    return { zd2: out, zic: icon.zic, sidecar: sidecar, crcHex: hex8(crc), sha256: sha,
      name: name, identity: ident, icon: { style: icon.style, cab: icon.cab, sha256: icon.sha256, frames: icon.frames },
      level: { steps: lv.steps, db: lv.db, oscaleHex: hex8(lv.oscaleBits) },
      fileName: fn + '.ZD2', zicName: fn + '.ZIC', sidecarName: fn + '.json' };
  }

  /**
   * renderPreview(result, env, onProgress) -> {rate, dry, pedal, model, notes}
   * "Hear it before you build" (the sketches' Later board). Re-runs, on the
   * 8 s synthetic pluck the gate uses:
   *   pedal = the bit-exact int16 engine emulation (the NAM 44.1k kernel at the
   *           pedal's 44.1 kHz, with this capture's exponents),
   *   model = the capture's float model on the same samples,
   *   dry   = the pluck itself.
   * Both pedal and model carry the capture's level step (spec §5.8): the
   * pedal track through the emulation's float32 `oscale`, the model track
   * multiplied by the same value, so the two stay comparable. `level` in
   * the result says which step.
   * All Float32Array at 44.1 kHz. NOT emulated: the 48k engine's resamplers
   * (so a 48 kHz capture previews with the NAM 44.1k engine's ~8.8 % stretch in
   * BOTH pedal and model), the host's VOL knob, the pedal's converters.
   */
  async function renderPreview(result, env, onProgress) {
    var it = result && result._internal;
    if (!result || result.verdict !== 'ready' || !it || !it.net) throw new Error('this capture is not ready to preview');
    var prog = onProgress || function () {};
    var x = env.signals.pluck;
    var steps = it.levelSteps == null ? 0 : it.levelSteps, g = levelOscale(steps);
    var model = await forwardFloat(it.net, x, null, async function (l, n) { prog(0.4 * (l + 1) / n, 'model'); await tick(); });
    var pedal = await forwardKernel(it.net, x, it.rexp, null, async function (l, n) { prog(0.4 + 0.6 * (l + 1) / n, 'pedal engine'); await tick(); }, steps);
    var dry = new Float32Array(x.length), m32 = new Float32Array(model.length);
    for (var i = 0; i < x.length; i++) { model[i] = model[i] * g; dry[i] = x[i]; m32[i] = model[i]; }
    prog(1, 'done');
    return { rate: 44100, dry: dry, pedal: pedal, model: m32,
      esr: esr(model, pedal),
      level: { steps: steps, db: steps * LEVEL_STEP_DB, oscaleHex: hex8(LEVEL_OSCALE_BITS[steps + LEVEL_MAX_STEPS]) },
      notes: 'Synthetic pluck at 44.1 kHz, level-matched (the capture\'s level step is applied). Pedal = bit-exact copy of the NAM 44.1k engine; the 48k engine\'s resampling, the VOL knob and the converters are not included.' };
  }

  // =====================================================================
  // several captures in one effect (multi-profile-contract.md sections 2
  // to 4 and 6.1 to 6.3, ruled 2026-10-04; the reference is
  // ref/nam_set.py, the vectors are testvectors/set_vectors.json):
  //   key    = one capture: its own K; several: the first 16 bytes of
  //            sha256(K_1 || ... || K_N), knob order. Then spec §9 as it is.
  //   labels = the Model knob's values, 1 to 7 characters each, made from
  //            the file names; no two equal in their first 4 characters
  //   name   = the directory's name, else the start the file names share,
  //            else the first file's name; then spec §9.4
  //   blob   = layout 7: a 64-word index ("NAMS") and N images of 1,504
  //            words; image k = the first 1,504 words of pack()'s image
  //   splice = a BLANK layout-7 host + the blob: the reservation, the
  //            knob's label table, the knob's maximum (two words) and the
  //            identity; nothing else, the length unchanged
  // A key is 32 hex characters or 16 bytes here; keys come back as hex.
  //   selection = what a folder contains, whether a selection builds and
  //            on which engine, what the label and name fields give
  //            (contract 6.6); buildSetOutputs goes from processCapture's
  //            Results to the effect file
  // No host of this layout ships yet: nothing below is used by
  // processCapture or buildOutputs.
  // =====================================================================
  var SET_MAX = 8;                 // layout 7 holds at most 8 captures (contract 2.1)
  var LABEL_MAX = 7;               // 7 characters and a NUL in the 8-byte table entry
  var LABEL_SEEN = 4;              // the pedal draws 4 characters at rest
  var NAME_SHARED_MIN = 3;         // a shared start shorter than this is not a name
  var WORD_SEPS = ' _-';           // where a shared start may be cut
  // the characters a label may hold: the ones the PEDAL's font is known to
  // draw on a knob (Thomas, 2026-10-05; the pedal-derived parameter maps of
  // the five MS+ models show exactly these and five note symbols)
  var LABEL_CHARS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789 #+-./:';
  var ORDER_RE = /^([0-9]{1,2})[ _\-.)]+(.*)$/;
  var MAGIC7 = 0x4E414D53;         // "NAMS", the index
  var MAGIC7_BYTES = [0x53, 0x4D, 0x41, 0x4E];
  var LAYOUT7 = 7;
  var IDXW = 64;                   // the index, in words
  var IMGW = 1504;                 // one A2-Lite image: 1,503 used words, made even
  var CAP_MIN = 2, CAP_MAX = SET_MAX;
  var KIND_CODE = { plain: 0, rs48: 1 };
  var MODEL_NAME = 'Model';
  var PARAM_ENTRY_WORDS = 14;
  var ONOFF_BYTES = [0x4F, 0x6E, 0x4F, 0x66, 0x66, 0, 0, 0, 0, 0, 0, 0];   // 'OnOff' + 7 NULs

  function isInt(v) { return typeof v === 'number' && isFinite(v) && Math.floor(v) === v; }
  function setCount(list) {
    if (!Array.isArray(list) || list.length < 1 || list.length > SET_MAX) throw new Error('an effect holds 1 to ' + SET_MAX + ' captures');
    return list.length;
  }
  function keyHexOf(k, what) {            // one capture key -> 32 lower-case hex characters
    if (typeof k === 'string') {
      if (!/^[0-9a-f]{32}$/i.test(k)) throw new Error(what + ' is not 16 bytes (the first half of the sha256, 32 hex characters)');
      return k.toLowerCase();
    }
    if (!k || k.length !== 16) throw new Error(what + ' is not 16 bytes (the first half of the sha256)');
    var s = '';
    for (var i = 0; i < 16; i++) {
      if (!isInt(k[i]) || k[i] < 0 || k[i] > 255) throw new Error(what + ' is not 16 bytes (the first half of the sha256)');
      s += ('0' + k[i].toString(16)).slice(-2);
    }
    return s;
  }

  // ---- identity (contract 6.1; nam_set.set_key, set_identity) ----------
  /** setKey(keys) — the effect's key as 32 hex. One capture: its own K. */
  function setKey(keys) {
    var n = setCount(keys), hex = [];
    for (var i = 0; i < n; i++) hex.push(keyHexOf(keys[i], 'a capture key'));
    if (n === 1) return hex[0];
    return sha256Hex(hexToBytes(hex.join(''))).slice(0, 32);
  }
  /**
   * deriveSetIdentity(keys, hostKind, resident, env) — the id and pedal
   * filename of an effect of these captures: deriveIdentity (spec §9.2,
   * §9.3) unchanged, applied to the effect's key. `captures` in the result
   * are the capture keys, in knob order.
   */
  function deriveSetIdentity(keys, hostKind, resident, env) {
    var out = deriveIdentity(setKey(keys), hostKind, resident, env);
    out.captures = keys.map(function (k) { return keyHexOf(k, 'a capture key'); });
    return out;
  }

  // ---- labels (contract 6.2; nam_set.set_labels, check_labels) ---------
  // every character the pedal does not draw becomes a space; runs of spaces
  // become one; none at the ends
  function drawable(s) {
    var out = '';
    for (var i = 0; i < s.length; i++) out += LABEL_CHARS.indexOf(s.charAt(i)) >= 0 ? s.charAt(i) : ' ';
    return out.split(' ').filter(function (p) { return p; }).join(' ');
  }
  function lstripSeps(s) {
    var i = 0;
    while (i < s.length && WORD_SEPS.indexOf(s.charAt(i)) >= 0) i++;
    return s.slice(i);
  }
  function rstripSeps(s) {
    var n = s.length;
    while (n > 0 && WORD_SEPS.indexOf(s.charAt(n - 1)) >= 0) n--;
    return s.slice(0, n);
  }
  // A leading order number (1 or 2 digits, then one or more of space _ - . ) )
  // is dropped when EVERY name has one, something is left of every name,
  // and (with two or more names) the numbers all differ.
  function dropOrder(bases) {
    var rest = [], nums = [], i, j;
    for (i = 0; i < bases.length; i++) {
      var m = ORDER_RE.exec(bases[i]);
      if (!m) return bases;
      rest.push(m[2].replace(/^ +| +$/g, ''));
      nums.push(parseInt(m[1], 10));
    }
    for (i = 0; i < rest.length; i++) if (!rest[i]) return bases;
    for (i = 1; i < nums.length; i++) for (j = 0; j < i; j++) if (nums[i] === nums[j]) return bases;
    return rest;
  }
  // How many leading characters all the names share AND may be dropped: the
  // longest common start (compared without case) cut back to just behind a
  // space, '_' or '-', such that every name keeps something behind it.
  // 0 when there is none, or with fewer than two names.
  function sharedStart(bases) {
    var i, n = 0, p, ok;
    if (bases.length < 2) return 0;
    for (i = 0; i < bases.length; i++) if (!bases[i]) return 0;
    var low = bases.map(function (b) { return b.toLowerCase(); });
    for (;;) {
      ok = true;
      for (i = 0; i < low.length; i++) if (!(low[i].length > n) || low[i].charAt(n) !== low[0].charAt(n)) { ok = false; break; }
      if (!ok) break;
      n++;
    }
    for (p = n; p > 0; p--) {
      if (WORD_SEPS.indexOf(bases[0].charAt(p - 1)) < 0) continue;
      ok = true;
      for (i = 0; i < bases.length; i++) if (!lstripSeps(bases[i].slice(p))) { ok = false; break; }
      if (ok) return p;
    }
    return 0;
  }
  function labelSeen(label) { return label.slice(0, LABEL_SEEN).toLowerCase(); }
  /**
   * setOrder(fileNames, keys) — "file-name order", the knob order (contract
   * 6.0; nam_set.set_order): the positions of fileNames in NATURAL order.
   * A name is its last path component without one trailing ".nam", in NFC,
   * cut into runs of ASCII digits and runs of anything else. A digit run
   * compares as a number (then the run with fewer leading zeros first);
   * any other run by UTF-16 code units with A-Z folded to a-z; a digit run
   * sorts before any other run; a name that is the start of another sorts
   * first. Ties: the exact name in NFC, then the name as given, then the
   * capture key when keys are given, then the order given.
   */
  function setOrder(fileNames, keys) {
    if (keys != null && keys.length !== fileNames.length) throw new Error('one key per file');
    function cmp(a, b) { return a < b ? -1 : a > b ? 1 : 0; }      // strings compare by UTF-16 code units
    var items = fileNames.map(function (fileName, i) {
      var base = String(fileName).replace(/\\/g, '/');
      base = base.slice(base.lastIndexOf('/') + 1);
      if (base.toLowerCase().slice(-4) === '.nam') base = base.slice(0, -4);
      var nfc = base.normalize('NFC');
      var runs = (nfc.match(/[0-9]+|[^0-9]+/g) || []).map(function (r) {
        var c = r.charCodeAt(0);
        if (c >= 48 && c <= 57) return { digit: true, num: r.replace(/^0+/, ''), len: r.length };
        return { digit: false, low: r.replace(/[A-Z]/g, function (ch) { return String.fromCharCode(ch.charCodeAt(0) + 32); }) };
      });
      return { i: i, runs: runs, nfc: nfc, given: base, key: keys != null ? keyHexOf(keys[i], 'key ' + i) : '' };
    });
    items.sort(function (a, b) {
      var n = Math.min(a.runs.length, b.runs.length), d;
      for (var j = 0; j < n; j++) {
        var x = a.runs[j], y = b.runs[j];
        if (x.digit !== y.digit) return x.digit ? -1 : 1;
        d = x.digit ? (x.num.length - y.num.length || cmp(x.num, y.num) || x.len - y.len) : cmp(x.low, y.low);
        if (d) return d;
      }
      return a.runs.length - b.runs.length || cmp(a.nfc, b.nfc) || cmp(a.given, b.given) || cmp(a.key, b.key) || a.i - b.i;
    });
    return items.map(function (it) { return it.i; });
  }
  /**
   * setLabels(fileNames) — the AUTOMATIC Model-knob labels, in knob order:
   *   1. the name cleaned as spec §9.4 steps 1 to 3;
   *   2. a leading order number dropped (dropOrder);
   *   3. the start that all names share dropped (sharedStart);
   *   3b. every character the pedal does not draw (anything outside
   *      LABEL_CHARS) becomes a space; runs of spaces become one;
   *   4. cut to 7 characters; spaces and '-' at the end trimmed;
   *   5. empty: 'M' and the position, from 1;
   *   6. labels that are equal in their first 4 characters (compared
   *      without case) are numbered: the first 3 characters, trailing
   *      spaces trimmed, and the smallest digit from 1 that makes the label
   *      differ in its first 4 characters from every other label.
   * The result never holds two labels equal in their first 4 characters.
   */
  function setLabels(fileNames) {
    setCount(fileNames);
    var bases = dropOrder(fileNames.map(cleanFileName));
    var p = sharedStart(bases), labels = [], i, j;
    for (i = 0; i < bases.length; i++) {
      var lab = rstripSeps(drawable(lstripSeps(bases[i].slice(p))).slice(0, LABEL_MAX));
      labels.push(lab || 'M' + (i + 1));
    }
    // which labels clash is decided BEFORE any is numbered; they are then
    // numbered in knob order, each against the labels as they are by then
    var seenKeys = [], groups = [], clash = [];
    for (i = 0; i < labels.length; i++) {
      j = seenKeys.indexOf(labelSeen(labels[i]));
      if (j < 0) { seenKeys.push(labelSeen(labels[i])); groups.push([i]); } else groups[j].push(i);
    }
    groups.forEach(function (members) { if (members.length > 1) clash = clash.concat(members); });
    clash.sort(function (a, b) { return a - b; });
    clash.forEach(function (m) {
      var stem = labels[m].slice(0, LABEL_SEEN - 1).replace(/ +$/, '');
      for (var d = 1; d < 10; d++) {
        var cand = stem + d, taken = false;
        for (var o = 0; o < labels.length; o++) if (o !== m && labelSeen(labels[o]) === labelSeen(cand)) { taken = true; break; }
        if (!taken) { labels[m] = cand; break; }
      }
    });
    return labels;
  }
  /**
   * checkLabels(labels) — what the splice and the app's edit fields require
   * of the FINAL labels. Returns the hints (labels that differ but look
   * alike in the 4 characters the pedal draws at rest). Throws on a label
   * that must be refused: not 1 to 7 printable ASCII characters, a space at
   * either end, or identical to another label (compared without case).
   */
  function checkLabels(labels) {
    setCount(labels);
    var i, j, low = [];
    function q(s) { return "'" + s + "'"; }
    for (i = 0; i < labels.length; i++) {
      var lab = labels[i];
      if (typeof lab !== 'string' || lab.length < 1 || lab.length > LABEL_MAX) throw new Error('label ' + (i + 1) + ' (' + q(lab) + '): 1 to ' + LABEL_MAX + ' characters');
      if (!asciiOk(lab, 1, LABEL_MAX)) throw new Error('label ' + (i + 1) + ' (' + q(lab) + '): printable ASCII only');
      for (j = 0; j < lab.length; j++) {
        if (LABEL_CHARS.indexOf(lab.charAt(j)) < 0) {
          throw new Error('label ' + (i + 1) + ' (' + q(lab) + '): only characters the pedal draws: letters, digits, the space and # + - . / :');
        }
      }
      if (lab.charAt(0) === ' ' || lab.charAt(lab.length - 1) === ' ') throw new Error('label ' + (i + 1) + ' (' + q(lab) + '): no space at either end');
    }
    for (i = 0; i < labels.length; i++) {
      low.push(labels[i].toLowerCase());
      j = low.indexOf(low[i]);
      if (j < i) throw new Error('label ' + (i + 1) + ' (' + q(labels[i]) + ') is identical to label ' + (j + 1));
    }
    var hints = [];
    for (i = 0; i < labels.length; i++) {
      var twins = [];
      for (j = 0; j < labels.length; j++) if (j !== i && labelSeen(labels[j]) === labelSeen(labels[i])) twins.push(j + 1);
      if (twins.length) hints.push('label ' + (i + 1) + ' (' + q(labels[i]) + ') reads like label ' + twins.join(', ') + ' at rest');
    }
    return hints;
  }

  // ---- name (contract 6.3; nam_set.set_name) ---------------------------
  /**
   * setName(fileNames, pedalFilename, directory, env) — the effect's header
   * name and icon text:
   *   - one capture: deriveName on the file's name, as today;
   *   - several, all in one directory the app knows: that directory's name
   *     (directory: its name or path; null = not known);
   *   - else the start their names share (after the order numbers are
   *     dropped), without the separators at its end, when it is 3
   *     characters or more;
   *   - else the first file's name.
   * The source then goes through deriveName (spec §9.4: ASCII, 11
   * characters, the stock name rule, the pedal filename when nothing is left).
   */
  function setName(fileNames, pedalFilename, directory, env) {
    setCount(fileNames);
    if (fileNames.length === 1) return deriveName(fileNames[0], pedalFilename, env);
    var src = null;
    if (directory != null) {
      var d = String(directory).replace(/\\/g, '/').replace(/\/+$/, '');
      d = d.slice(d.lastIndexOf('/') + 1);
      if (cleanFileName(d + '.nam')) src = d;
    }
    if (src === null) {
      var bases = dropOrder(fileNames.map(cleanFileName));
      var shared = rstripSeps(bases[0].slice(0, sharedStart(bases)));
      if (shared.length >= NAME_SHARED_MIN) src = shared;
    }
    if (src === null) return deriveName(fileNames[0], pedalFilename, env);
    return deriveName(src + '.nam', pedalFilename, env);
  }

  // ---- blob layout 7 (contract 2; nam_set.check_image, build_blob) -----
  function reservationWords(cap) { return IDXW + cap * IMGW; }
  /**
   * Words 0 to 7 of a blank layout-7 host (contract 2.3): N = 0. reserved:
   * the host's reservation in words, at least 64 + CAP * 1504 (the default
   * when absent); a host may reserve more.
   */
  function blankIndex(cap, kind, modelEntry, reserved) {
    if (modelEntry == null) modelEntry = 2;
    if (!isInt(cap) || cap < CAP_MIN || cap > CAP_MAX) throw new Error('CAP must be ' + CAP_MIN + '..' + CAP_MAX + ' (a host of one position has no knob scale)');
    if (!Object.prototype.hasOwnProperty.call(KIND_CODE, kind)) throw new Error('kind must be plain or rs48');
    if (!isInt(modelEntry) || modelEntry < 2 || modelEntry > 0xFFFFFFFF) throw new Error('the Model knob\'s param-table entry is 2 or more');
    if (reserved == null) reserved = reservationWords(cap);
    if (!isInt(reserved) || reserved < reservationWords(cap) || reserved > 0xFFFFFFFF) {
      throw new Error('a reservation of ' + reserved + ' words does not hold CAP ' + cap + ' images (' + reservationWords(cap) + ')');
    }
    return [MAGIC7, 0, reserved, LAYOUT7, KIND_CODE[kind], cap, modelEntry, 0];
  }
  /** What a blank host's label table holds: M01, M02, ... NUL-padded. */
  function blankLabelTable(cap) {
    var out = new Uint8Array(cap * 8);
    for (var k = 0; k < cap; k++) {
      var s = 'M' + ('0' + (k + 1)).slice(-2);
      for (var i = 0; i < s.length; i++) out[8 * k + i] = s.charCodeAt(i);
    }
    return out;
  }
  // a list of 32-bit words as a Uint32Array (a negative word is read as its
  // two's complement, which is how the blob stores it)
  function wordsOf(im, what) {
    if (im instanceof Uint32Array) return im;
    if (!im || typeof im.length !== 'number') throw new Error(what + ': not a list of words');
    var out = new Uint32Array(im.length);
    for (var i = 0; i < im.length; i++) {
      if (!isInt(im[i]) || im[i] < -2147483648 || im[i] > 0xFFFFFFFF) throw new Error(what + ': word ' + i + ' is not a 32-bit integer');
      out[i] = im[i] >>> 0;
    }
    return out;
  }
  /**
   * packImage(net, rs48, ringExp, levelSteps) — one capture's image for a
   * layout-7 blob: the image pack() makes for a single capture, cut to
   * IMGW words (contract 2.2). net: after the rechannel rescale, as
   * processCapture packs it; the exponents and the level step are the
   * capture's own. Returns {words (IMGW of them), used, levelSteps, rs48}.
   */
  function packImage(net, rs48, ringExp, levelSteps) {
    return imageOfPack(pack(net, rs48, ringExp, levelSteps), rs48);
  }
  // the same cut, from a pack() result already in hand (processCapture's
  // container check in the layout-7 environment)
  function imageOfPack(p, rs48) {
    if (p.used > IMGW) throw new PackError('the capture packs to ' + p.used + ' words, an image holds ' + IMGW);
    for (var i = IMGW; i < p.words.length; i++) if (p.words[i]) throw new PackError('the capture\'s image is not zero behind word ' + IMGW);
    return { words: new Uint32Array(p.words.subarray(0, IMGW)), used: p.used, levelSteps: p.levelSteps, rs48: !!rs48 };
  }
  /**
   * checkImage(im, kind, what) — one image against the kernel's own list
   * (spec §6.6), read with the image's first word as the base and IMGW as
   * the bound, for a host of this kind (0 = plain, 1 = 48k). Returns the
   * image's GEOMETRY (contract 2.2) as a list. Fails closed.
   */
  function checkImage(im, kind, what) {
    function no(msg) { throw new Error(what + ': ' + msg); }
    if (kind !== KIND_CODE.plain && kind !== KIND_CODE.rs48) no('host kind ' + kind + ' is not 0 (plain) or 1 (48k)');
    if (!im || im.length !== IMGW) no((im ? im.length : 0) + ' words, an image is ' + IMGW);
    var w = wordsOf(im, what);
    if (w[0] !== MAGIC) no('it does not start with NAM1');
    var nl = w[1], ringw = w[2], mir = w[5];
    if (!(nl >= 1 && nl <= NL)) no('NL ' + nl + ' is not 1..' + NL);
    if (ringw === 0 || ringw % 32) no('ringw ' + ringw + ' is not a non-zero multiple of 32');
    if ((mir !== 0 && mir !== 32) || w[6] || w[7]) no('header words 5 to 7 are not what the packer writes');
    if (kind === KIND_CODE.rs48 && mir !== 32) {
      no('it is the plain layout (header word 5 != 32) and the host is the 48k one: it would play SILENCE; pack it for the 48k host');
    }
    var osc = u2f(w[3]), isc = u2f(w[4]);
    if (!(osc > -1.0e6 && osc < 1.0e6) || !(isc > 0 && isc < 1.0e6)) {   // the kernel's own bounds
      no('oscale is not inside (-1e6, 1e6) or iscale is not inside (0, 1e6)');
    }
    // the arena the kernel of this host kind needs (as pack() counts it)
    var tail = kind === KIND_CODE.rs48 ? C * 64 + 96 + 32 : C * 32 + 64;
    if (ringw * 4 + RALIGN + tail * 4 > ARENA_GRANT) no('the rings need more arena than the pedal grants');
    var rows = mir || 16, cover = mir === 32 ? 18 : 16, ePrev = 0, CW = 2;
    var geo = [nl, ringw, w[4], mir];
    for (var l = 0; l < nl; l++) {
      var b = HDR + l * DW;
      var d = w[b], m1 = w[b + 1], roff = w[b + 2], w3 = w[b + 3], s1 = w[b + 4], woff = w[b + 5], k = w[b + 6];
      var steps = m1 + 1, s = w3 & 0xFF, e = (w3 >>> 8) & 15;
      if ((k !== 6 && k !== 15) || !(d >= 1 && d <= 65536)) no('layer ' + l + ': kernel size ' + k + ' or dilation ' + d);
      if (steps % 16 || steps < (k - 1) * d + cover) no('layer ' + l + ': a ring of ' + steps + ' steps does not cover its taps');
      if (roff % 2 || roff + (steps + rows) * CW > ringw) no('layer ' + l + ': its ring lies outside ringw');
      if ((w3 >>> 12) || s > 30 || s1 > 30 || e > 8 || e < ePrev) no('layer ' + l + ': shifts or ring exponent out of range');
      ePrev = e;
      if (woff < HDR + nl * DW || woff + C * (k * CW + 2 + CW + 1) > IMGW) no('layer ' + l + ': its weights lie outside the image');
      geo.push(d, m1, roff, k);
    }
    var hb = u2f(w[HDR + nl * DW + C + HEAD_K * C]);
    if (!(Math.abs(hb) < 8)) no('the head bias is not inside (-8, 8)');
    return geo;
  }
  /**
   * buildBlob(images, keys, labels, cap, kind, modelEntry, reserved) — the
   * used part of a layout-7 reservation (contract 2.1, 2.2): the index and
   * N images, IDXW + N * IMGW words (a Uint32Array). kind: 'plain' | 'rs48';
   * modelEntry: the Model knob's param-table entry, 2 when absent;
   * reserved: the host's index word 2, exactly CAP images when absent.
   * Fails closed.
   */
  function buildBlob(images, keys, labels, cap, kind, modelEntry, reserved) {
    var idx = blankIndex(cap, kind, modelEntry, reserved);
    if (!Array.isArray(images)) throw new Error('the images are a list, one per capture');
    var n = images.length, k, i;
    if (!(n >= 1 && n <= cap)) throw new Error(n + ' capture(s): this host takes 1..' + cap);
    if (!Array.isArray(keys) || !Array.isArray(labels) || keys.length !== n || labels.length !== n) throw new Error('one key and one label per capture');
    checkLabels(labels);
    var geos = [], keyHex = [];
    for (k = 0; k < n; k++) geos.push(checkImage(images[k], KIND_CODE[kind], 'image ' + k).join(','));
    for (k = 0; k < n; k++) if (geos[k] !== geos[0]) throw new Error('image ' + k + ' has another geometry than image 0 (contract 2.2)');
    for (k = 0; k < n; k++) keyHex.push(keyHexOf(keys[k], 'key ' + k));
    var words = new Uint32Array(IDXW + n * IMGW);
    for (i = 0; i < 8; i++) words[i] = idx[i];
    words[1] = n;
    for (k = 0; k < n; k++) words[8 + k] = IDXW + k * IMGW;
    // words 16 to 47: the keys, 16 bytes each; words 48 to 63: the label
    // copy, 8 bytes each, NUL-padded; unused entries zero
    var tab = new Uint8Array((IDXW - 16) * 4);
    for (k = 0; k < n; k++) {
      tab.set(hexToBytes(keyHex[k]), 16 * k);
      for (i = 0; i < labels[k].length; i++) tab[128 + 8 * k + i] = labels[k].charCodeAt(i);
    }
    for (i = 16; i < IDXW; i++) words[i] = rd32(tab, 4 * (i - 16));
    for (k = 0; k < n; k++) words.set(wordsOf(images[k], 'image ' + k), IDXW + k * IMGW);
    return words;
  }

  // ---- the splice (contract 3 and 4; nam_set.host_regions, splice_set,
  // read_set). A BLANK layout-7 host + N packed images -> the effect file.
  /**
   * hostRegions(raw, what, labelsAt) — locate and check the regions of a
   * layout-7 host (contract 3.1). labelsAt absent: the host must be BLANK
   * and the label table is found by its blank contents; otherwise the file
   * is a splice being read back and labelsAt says where the table is
   * (-1: not known, not checked). Fails closed.
   */
  function hostRegions(raw, what, labelsAt) {
    zd2CheckEnvelope(raw, what);
    var data = zd2Chunks(raw).filter(function (c) { return c.tag === 'DATA'; });
    if (data.length !== 1) throw new Error(what + ': exactly one DATA chunk is expected');
    var ds = data[0].start, de = ds + data[0].len, i;
    var cnt = countPattern(raw, MAGIC7_BYTES);
    if (cnt !== 1) throw new Error(what + ': the NAMS magic must occur exactly once (found ' + cnt + '); is this a layout-7 host?');
    var off = findPattern(raw, MAGIC7_BYTES);
    if (off < ds || off + 32 > de || (off - ds) % 4) throw new Error(what + ': the NAMS magic is not word-aligned inside the DATA chunk');
    var n = rd32(raw, off + 4), reserved = rd32(raw, off + 8), layout = rd32(raw, off + 12), kind = rd32(raw, off + 16);
    var cap = rd32(raw, off + 20), entry = rd32(raw, off + 24), w7 = rd32(raw, off + 28);
    if (layout !== LAYOUT7) throw new Error(what + ': index layout ' + layout + ', this code writes ' + LAYOUT7);
    if (kind !== 0 && kind !== 1) throw new Error(what + ': host kind ' + kind + ' is not 0 (plain) or 1 (48k)');
    if (!(cap >= CAP_MIN && cap <= CAP_MAX)) throw new Error(what + ': CAP ' + cap + ' is not ' + CAP_MIN + '..' + CAP_MAX);
    if (entry < 2 || w7 !== 0) throw new Error(what + ': index word 6 (' + entry + ') or word 7 (' + w7 + ') is not a host\'s');
    var resEnd = off + reserved * 4;
    if (reservationWords(cap) > reserved || resEnd > de) {
      throw new Error(what + ': the reservation (' + reserved + ' words) does not hold CAP images or overruns the DATA chunk');
    }
    var blank = labelsAt == null, lab;
    if (blank) {
      var dirty = n !== 0;
      for (i = off + 32; i < resEnd && !dirty; i++) if (raw[i]) dirty = true;
      if (dirty) throw new Error(what + ': not BLANK (it holds captures already, or its reservation is not zero): splice into the blank host only');
      if (countPattern(raw, MAGIC_BYTES)) throw new Error(what + ': the NAM1 magic occurs in a blank layout-7 host');
      var tab = blankLabelTable(cap), nTab = countPattern(raw, tab, ds, de);
      if (nTab !== 1) {
        throw new Error(what + ': the blank label table (M01..M' + ('0' + cap).slice(-2) + ') must occur exactly once in the DATA chunk (found ' + nTab + ')');
      }
      lab = findPattern(raw, tab, ds, de);
    } else {
      lab = labelsAt;
    }
    if (lab >= 0 && ((off <= lab && lab < resEnd) || lab < ds || lab + cap * 8 > de)) {
      throw new Error(what + ': the label table lies inside the reservation or outside DATA');
    }
    // the param table: 'OnOff' + 7 NULs, word-aligned, the next entry's word
    // 3 = 0xFFFFFFFF, outside the reservation, exactly once
    var hits = [], pos = ds;
    for (;;) {
      i = findPattern(raw, ONOFF_BYTES, pos, de);
      if (i < 0) break;
      pos = i + 1;
      var j = i + PARAM_ENTRY_WORDS * 4 + 12;
      if ((i - ds) % 4 === 0 && j + 4 <= de && rd32(raw, j) === 0xFFFFFFFF && !(off <= i && i < resEnd)) hits.push(i);
    }
    if (hits.length !== 1) throw new Error(what + ': the param table must be found exactly once (found ' + hits.length + ')');
    var ent = hits[0] + entry * PARAM_ENTRY_WORDS * 4;
    if (ent + PARAM_ENTRY_WORDS * 4 > de || (off <= ent && ent < resEnd)) throw new Error(what + ': the Model entry lies outside the DATA chunk');
    var name = '';
    for (i = ent; i < ent + 12 && raw[i]; i++) name += String.fromCharCode(raw[i]);
    if (name !== MODEL_NAME) throw new Error(what + ': param entry ' + entry + ' is \'' + name + '\', not \'' + MODEL_NAME + '\'');
    var pmax = rd32(raw, ent + 12), pdef = rd32(raw, ent + 16), pw5 = rd32(raw, ent + 20);
    if (blank && (pmax !== cap - 1 || pw5 !== cap - 1 || pdef !== 0)) {
      throw new Error(what + ': the Model knob\'s maximum is ' + pmax + ' / ' + pw5 + ' and its default ' + pdef +
        '; a blank host has ' + (cap - 1) + ' / ' + (cap - 1) + ' and 0');
    }
    return { blob: off, reserved: reserved, n: n, kind: kind, cap: cap, entry: entry, labels: lab,
      param: ent, paramMax: pmax, paramDefault: pdef, paramW5: pw5 };
  }
  /**
   * spliceSet(host, images, keys, labels, identity) -> {zd2, facts} — a
   * BLANK layout-7 host + N images -> the effect file and its facts.
   * identity: null keeps the host's (a test article); else {id, name},
   * written with group 4 / PREAMP as spec §7.4. Throws; never returns a
   * file it could not read back.
   */
  function spliceSet(host, images, keys, labels, identity) {
    var r = hostRegions(host, 'host');
    var kind = r.kind === KIND_CODE.rs48 ? 'rs48' : 'plain';
    var words = buildBlob(images, keys, labels, r.cap, kind, r.entry, r.reserved);
    var n = images.length, cap = r.cap, i, k;
    if (identity != null && (!isInt(identity.id) || typeof identity.name !== 'string')) throw new Error('the identity needs an id and a name');
    var off = r.blob, resB = r.reserved * 4, lab = r.labels, ent = r.param, used = words.length * 4;
    var out = new Uint8Array(host);
    for (i = 0; i < words.length; i++) wr32(out, off + 4 * i, words[i]);
    for (i = off + used; i < off + resB; i++) out[i] = 0;
    for (k = 0; k < n; k++) {                       // the entries from N on stay blank
      for (i = 0; i < 8; i++) out[lab + 8 * k + i] = i < labels[k].length ? labels[k].charCodeAt(i) : 0;
    }
    wr32(out, ent + 12, n - 1);                     // word 3: the maximum
    wr32(out, ent + 20, n - 1);                     // word 5: its copy
    wr32(out, 8, zd2Crc(out));
    if (identity != null) out = setIdentity(out, { id: identity.id, name: identity.name, group: GROUP_PREAMP, groupName: GROUP_NAME });
    // ---- read back what is about to be handed over ----
    var back = hostRegions(out, 'output', lab);
    if (back.blob !== off || back.param !== ent || back.n !== n || out.length !== host.length) throw new Error('output: a region moved, or N reads back wrong');
    if (back.paramMax !== n - 1 || back.paramW5 !== n - 1 || back.paramDefault !== 0) throw new Error('output: the Model knob\'s maximum or default reads back wrong');
    for (i = 0; i < words.length; i++) if (rd32(out, off + 4 * i) !== words[i]) throw new Error('output: the reservation reads back differently');
    for (i = off + used; i < off + resB; i++) if (out[i]) throw new Error('output: the reservation reads back differently');
    var spans = [[off, off + resB], [lab, lab + 8 * n], [ent + 12, ent + 16], [ent + 20, ent + 24]];
    if (identity != null) spans.push([95, 122]);    // group, id, name, group name
    spans.sort(function (a, b) { return a[0] - b[0] || a[1] - b[1]; });
    var edge = 12;                                  // [8:12] is the CRC
    function same(a, b) {
      for (var x = a; x < b; x++) if (out[x] !== host[x]) return false;
      return true;
    }
    for (k = 0; k < spans.length; k++) {
      if (spans[k][0] < edge || !same(edge, spans[k][0])) throw new Error('output: bytes outside the spliced regions changed');
      edge = spans[k][1];
    }
    if (!same(edge, out.length) || !same(0, 8)) throw new Error('output: bytes outside the spliced regions changed');
    var differ = 0;
    for (i = 0; i < out.length; i++) if (out[i] !== host[i]) differ++;
    var facts = { n: n, cap: cap, kind: kind, max: n - 1, labels: labels.slice(),
      blobOffset: off, labelOffset: lab, paramOffset: ent, usedWords: words.length,
      reservedWords: r.reserved, crc: zd2Crc(out), sha256: sha256Hex(out), bytes: out.length, differ: differ };
    return { zd2: out, facts: facts };
  }
  /**
   * readSet(raw) — a SPLICED layout-7 file read back: N, CAP, the keys (hex)
   * and the labels from the index, the Model knob's maximum from the param
   * table. The label table itself cannot be located in a spliced file; the
   * index copy is why (contract 2.1).
   */
  function readSet(raw) {
    zd2CheckEnvelope(raw, 'file');
    if (countPattern(raw, MAGIC7_BYTES) !== 1) throw new Error('file: the NAMS magic must occur exactly once');
    var off = findPattern(raw, MAGIC7_BYTES), i, k;
    if (off + IDXW * 4 > raw.length) throw new Error('file: the index overruns the file');
    var n = rd32(raw, off + 4), layout = rd32(raw, off + 12), cap = rd32(raw, off + 20);
    if (layout !== LAYOUT7 || !(cap >= CAP_MIN && cap <= CAP_MAX) || !(n >= 1 && n <= cap)) {
      throw new Error('file: not a spliced layout-7 effect (layout ' + layout + ', CAP ' + cap + ', N ' + n + ')');
    }
    var keys = [], labels = [], offsets = [], agree = true;
    for (k = 0; k < n; k++) {
      var kh = '', s = '', kb = off + 64 + 16 * k, lb = off + 192 + 8 * k;
      for (i = 0; i < 16; i++) kh += ('0' + raw[kb + i].toString(16)).slice(-2);
      // (a byte that is not ASCII reads as U+FFFD, as the reference's decode does)
      for (i = 0; i < 8 && raw[lb + i]; i++) s += String.fromCharCode(raw[lb + i] < 0x80 ? raw[lb + i] : 0xFFFD);
      keys.push(kh); labels.push(s);
      offsets.push(rd32(raw, off + 32 + 4 * k));
      if (offsets[k] !== IDXW + k * IMGW) agree = false;
    }
    var r = hostRegions(raw, 'file', -1);
    return { n: n, cap: cap, kind: rd32(raw, off + 16), keys: keys, labels: labels, key: setKey(keys),
      offsets: offsets, paramMax: r.paramMax, paramW5: r.paramW5,
      agree: agree && r.paramMax === n - 1 && r.paramW5 === n - 1 };
  }

  // ---- the selection (contract 6.6; nam_set.folder_files, check_selection,
  // final_labels, final_name): what the app decides BEFORE it builds. Nothing
  // here reads a file: the caller says of each capture whether it can be
  // used and at which rate.
  var RATES = [44100, 48000];
  var SELECTION_CODES = ['empty', 'too-many', 'unusable', 'duplicate', 'mixed-rates'];
  var FIELD_CODES = ['characters', 'length', 'identical'];
  var KIND_HOST = { plain: 'nam-a2', rs48: 'nam-48k' };
  /**
   * folderFiles(paths) — what a folder the user gave contains (ruled
   * 2026-10-05): its top-level '.nam' files, the extension in any case.
   * Files in subfolders are not included, and a name that starts with a dot
   * is skipped (hidden files; the '._name' companions macOS writes).
   * paths: every file under the folder, each as its path FROM THE FOLDER'S
   * PARENT, the folder's own name first ('Amps/1 Clean.nam'): what
   * webkitRelativePath holds. A '\' counts as '/', and one leading '/' is
   * dropped (a dropped folder's fullPath). Returns {directory (the folder's
   * name; null when no path was given), keep (the positions kept)}.
   */
  function folderFiles(paths) {
    var directory = null, keep = [];
    for (var i = 0; i < paths.length; i++) {
      var q = String(paths[i]).replace(/\\/g, '/');
      if (q.charAt(0) === '/') q = q.slice(1);
      var parts = q.split('/'), ok = parts.length >= 2;
      for (var j = 0; j < parts.length; j++) if (!parts[j]) ok = false;
      if (!ok) throw new Error(JSON.stringify(paths[i]) + ' is not the path of a file inside a folder');
      if (directory === null) directory = parts[0];
      else if (parts[0] !== directory) throw new Error(JSON.stringify(paths[i]) + ' is not in the folder ' + JSON.stringify(directory));
      var name = parts[parts.length - 1];
      if (parts.length === 2 && name.charAt(0) !== '.' && name.slice(-4).toLowerCase() === '.nam') keep.push(i);
    }
    return { directory: directory, keep: keep };
  }

  // ---- a zip the user gives (contract 6.6 "A zip"; nam_zip.py; ruled by
  // Thomas on 2026-10-14). A zip is like a folder: its captures make one
  // effect and the zip's name is the directory. The reader REFUSES what it
  // does not take and never repairs: no zip64, no multi-disk, no encryption,
  // only stored and deflate, at most ZIP_MAX_ENTRIES entries, ZIP_ENTRY_MAX
  // bytes per capture and ZIP_TOTAL_MAX in all (uncompressed; the core has
  // no file-size limit of its own, so these are the zip's), every local
  // header agreeing with its central record. A refusal is an Error whose
  // message starts with a stable code ('zip-corrupt: ...'). Entry names and
  // the zip's name are USER TEXT: they go only through the name cleaning.
  var ZIP_MAX_ENTRIES = 1024;
  var ZIP_ENTRY_MAX = 16 * 1024 * 1024;
  var ZIP_TOTAL_MAX = 4 * ZIP_ENTRY_MAX;
  var ZIP_EOCD_SPAN = 22 + 0xFFFF;        // the end record and the longest comment: 65557 bytes
  var ZIP_NAME_MAX = 1024;                // an entry name, raw bytes, checked before it is decoded
  var ZIP_CODES = ['zip-not-a-zip', 'zip-multi-disk', 'zip-zip64', 'zip-too-many-entries', 'zip-corrupt',
    'zip-name', 'zip-encrypted', 'zip-method', 'zip-too-large', 'zip-length', 'zip-crc'];
  var PICK_CODES = ['zip-several', 'zip-mixed'];
  // CP437, bytes 0x80..0xFF (0x00..0x7F are ASCII): the names of an entry
  // without the UTF-8 flag (bit 11). The vectors carry Python's table.
  var CP437_HIGH =
    'ÇüéâäàåçêëèïîìÄÅ' +
    'ÉæÆôöòûùÿÖÜ¢£¥₧ƒ' +
    'áíóúñÑªº¿⌐¬½¼¡«»' +
    '░▒▓│┤╡╢╖╕╣║╗╝╜╛┐' +
    '└┴┬├─┼╞╟╚╔╩╦╠═╬╧' +
    '╨╤╥╙╘╒╓╫╪┘┌█▄▌▐▀' +
    'αßΓπΣσµτΦΘΩδ∞φε∩' +
    '≡±≥≤⌠⌡÷≈°∙·√ⁿ²■ ';
  function zipNo(code, detail) { return new Error(code + ': ' + detail); }
  function rd16(b, o) { return b[o] | (b[o + 1] << 8); }

  // inflateRaw(src, start, end, max) — a raw DEFLATE stream (RFC 1951) in
  // src[start:end] that must inflate to AT MOST max bytes and end exactly
  // at end. In the manner of zlib's puff.c: small and slow, every malformed
  // stream refused ('zip-corrupt'), and output past max refused at once
  // ('zip-length'), so it neither loops forever nor grows without bound.
  var INF_LBASE = [3, 4, 5, 6, 7, 8, 9, 10, 11, 13, 15, 17, 19, 23, 27, 31, 35, 43, 51, 59, 67, 83, 99,
    115, 131, 163, 195, 227, 258];
  var INF_LEXT = [0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 2, 2, 2, 2, 3, 3, 3, 3, 4, 4, 4, 4, 5, 5, 5, 5, 0];
  var INF_DBASE = [1, 2, 3, 4, 5, 7, 9, 13, 17, 25, 33, 49, 65, 97, 129, 193, 257, 385, 513, 769, 1025,
    1537, 2049, 3073, 4097, 6145, 8193, 12289, 16385, 24577];
  var INF_DEXT = [0, 0, 0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6, 7, 7, 8, 8, 9, 9, 10, 10, 11, 11, 12,
    12, 13, 13];
  var INF_ORDER = [16, 17, 18, 0, 8, 7, 9, 6, 10, 5, 11, 4, 12, 3, 13, 2, 14, 1, 15];
  function inflateRaw(src, start, end, max) {
    var pos = start, buf = 0, cnt = 0, out = new Uint8Array(max), n = 0;
    function bad(why) { return zipNo('zip-corrupt', 'the deflate stream ' + why); }
    function bits(k) {
      while (cnt < k) {
        if (pos >= end) throw bad('ends early');
        buf |= src[pos++] << cnt; cnt += 8;
      }
      var v = buf & ((1 << k) - 1);
      buf >>>= k; cnt -= k;
      return v;
    }
    // a canonical Huffman code from code lengths: {count, symbol, left}
    // (left > 0: incomplete, < 0: over-subscribed)
    function huff(lengths, from, num) {
      var count = new Array(16), offs = new Array(16), symbol = new Array(num), i, left = 1;
      for (i = 0; i < 16; i++) count[i] = 0;
      for (i = 0; i < num; i++) count[lengths[from + i]]++;
      for (i = 1; i < 16; i++) { left = left * 2 - count[i]; if (left < 0) break; }
      offs[1] = 0;
      for (i = 1; i < 15; i++) offs[i + 1] = offs[i] + count[i];
      for (i = 0; i < num; i++) if (lengths[from + i]) symbol[offs[lengths[from + i]]++] = i;
      return { count: count, symbol: symbol, left: left };
    }
    function decode(h) {
      var code = 0, first = 0, index = 0;
      for (var len = 1; len < 16; len++) {
        code |= bits(1);
        var c = h.count[len];
        if (code - c < first) return h.symbol[index + (code - first)];
        index += c; first = (first + c) * 2; code *= 2;
      }
      throw bad('holds a code that is not in its table');
    }
    function put(v) {
      if (n >= max) throw zipNo('zip-length', 'the entry inflates to more than its declared ' + max + ' bytes');
      out[n++] = v;
    }
    function codes(lc, dc) {
      for (;;) {
        var sym = decode(lc);
        if (sym < 256) { put(sym); continue; }
        if (sym === 256) return;
        sym -= 257;
        if (sym >= 29) throw bad('holds an invalid length symbol');
        var len = INF_LBASE[sym] + bits(INF_LEXT[sym]);
        sym = decode(dc);
        if (sym >= 30) throw bad('holds an invalid distance symbol');
        var dist = INF_DBASE[sym] + bits(INF_DEXT[sym]);
        if (dist > n) throw bad('reaches back before its start');
        for (var k = 0; k < len; k++) put(out[n - dist]);
      }
    }
    var fixed = null, last;
    do {
      last = bits(1);
      var type = bits(2);
      if (type === 0) {
        buf = 0; cnt = 0;                 // to the byte boundary
        if (pos + 4 > end) throw bad('ends early');
        var len = rd16(src, pos), nlen = rd16(src, pos + 2);
        pos += 4;
        if (len !== (~nlen & 0xFFFF)) throw bad('has a stored block whose lengths disagree');
        if (pos + len > end) throw bad('ends early');
        for (var k = 0; k < len; k++) put(src[pos + k]);
        pos += len;
      } else if (type === 1) {
        if (!fixed) {
          var fl = [], i;
          for (i = 0; i < 144; i++) fl.push(8);
          for (; i < 256; i++) fl.push(9);
          for (; i < 280; i++) fl.push(7);
          for (; i < 288; i++) fl.push(8);
          for (i = 0; i < 30; i++) fl.push(5);
          fixed = { l: huff(fl, 0, 288), d: huff(fl, 288, 30) };
        }
        codes(fixed.l, fixed.d);
      } else if (type === 2) {
        var nl = bits(5) + 257, nd = bits(5) + 1, nc = bits(4) + 4, lengths = [], j;
        if (nl > 286 || nd > 30) throw bad('has too many codes');
        for (j = 0; j < 19; j++) lengths[j] = 0;
        for (j = 0; j < nc; j++) lengths[INF_ORDER[j]] = bits(3);
        var cl = huff(lengths, 0, 19);
        if (cl.left !== 0) throw bad('has an incomplete code-length code');
        lengths = [];
        while (lengths.length < nl + nd) {
          var s = decode(cl), rep, val = 0;
          if (s < 16) { lengths.push(s); continue; }
          if (s === 16) {
            if (!lengths.length) throw bad('repeats a length that does not exist');
            val = lengths[lengths.length - 1]; rep = 3 + bits(2);
          } else if (s === 17) rep = 3 + bits(3);
          else rep = 11 + bits(7);
          if (lengths.length + rep > nl + nd) throw bad('repeats past its lengths');
          while (rep--) lengths.push(val);
        }
        if (!lengths[256]) throw bad('has no end-of-block code');
        var lc = huff(lengths, 0, nl);
        if (lc.left < 0 || (lc.left > 0 && nl !== lc.count[0] + lc.count[1])) throw bad('has an incomplete literal/length code');
        var dc = huff(lengths, nl, nd);
        if (dc.left < 0 || (dc.left > 0 && nd !== dc.count[0] + dc.count[1])) throw bad('has an incomplete distance code');
        codes(lc, dc);
      } else throw bad('has an invalid block type');
    } while (!last);
    if (pos !== end) throw bad('is followed by more bytes');
    return n === max ? out : out.subarray(0, n);
  }

  // code units to a string in linear time (chunks keep apply's argument count small)
  function zipUnits(u) {
    var parts = [];
    for (var i = 0; i < u.length; i += 4096) parts.push(String.fromCharCode.apply(null, u.slice(i, i + 4096)));
    return parts.join('');
  }
  function utf8Strict(b, s, e) {          // null: not valid UTF-8 (Python's strict decoding)
    var out = [], i = s;
    while (i < e) {
      var c = b[i], k, cp, min;
      if (c < 0x80) { out.push(c); i++; continue; }
      if (c >= 0xC2 && c <= 0xDF) { k = 1; cp = c & 0x1F; min = 0x80; }
      else if (c >= 0xE0 && c <= 0xEF) { k = 2; cp = c & 0x0F; min = 0x800; }
      else if (c >= 0xF0 && c <= 0xF4) { k = 3; cp = c & 0x07; min = 0x10000; }
      else return null;
      if (i + k >= e) return null;
      for (var j = 1; j <= k; j++) {
        if ((b[i + j] & 0xC0) !== 0x80) return null;
        cp = (cp << 6) | (b[i + j] & 0x3F);
      }
      if (cp < min || cp > 0x10FFFF || (cp >= 0xD800 && cp <= 0xDFFF)) return null;
      if (cp < 0x10000) out.push(cp);
      else { cp -= 0x10000; out.push(0xD800 + (cp >> 10), 0xDC00 + (cp & 0x3FF)); }
      i += k + 1;
    }
    return zipUnits(out);
  }
  function zipNameText(b, s, e, utf8) {
    var t;
    if (utf8) {
      t = utf8Strict(b, s, e);
      if (t === null) throw zipNo('zip-name', 'an entry name is not valid UTF-8');
    } else {
      var u = [];
      for (var i = s; i < e; i++) u.push(b[i] < 0x80 ? b[i] : CP437_HIGH.charCodeAt(b[i] - 0x80));
      t = zipUnits(u);
    }
    if (t.indexOf('\u0000') >= 0) throw zipNo('zip-name', 'an entry name holds a NUL');
    return t;
  }
  function zipHasZip64Extra(b, p, end) {
    while (p + 4 <= end) {
      if (rd16(b, p) === 0x0001) return true;
      p += 4 + rd16(b, p + 2);
    }
    return false;
  }
  function zipLast(name) { var q = String(name).replace(/\\/g, '/').split('/'); return q[q.length - 1]; }
  function zipIsCapture(name) { return name.charAt(0) !== '.' && name.slice(-4).toLowerCase() === '.nam'; }
  // the central directory, every record; then which are kept (ruling R3);
  // then the checks of every kept entry (nam_zip._scan)
  function zipScan(b) {
    var n = b.length, eocd = -1, off, i;
    if (n < 22) throw zipNo('zip-not-a-zip', 'too short to be a zip');
    for (off = n - 22; off >= Math.max(0, n - ZIP_EOCD_SPAN); off--)
      if (rd32(b, off) === 0x06054B50 && off + 22 + rd16(b, off + 20) === n) { eocd = off; break; }
    if (eocd < 0) throw zipNo('zip-not-a-zip', 'no end-of-central-directory record');
    var disk = rd16(b, eocd + 4), cdDisk = rd16(b, eocd + 6), onDisk = rd16(b, eocd + 8),
      total = rd16(b, eocd + 10), cdSize = rd32(b, eocd + 12), cdOff = rd32(b, eocd + 16);
    if (eocd >= 20 && rd32(b, eocd - 20) === 0x07064B50) throw zipNo('zip-zip64', 'a zip64 locator');
    if (disk === 0xFFFF || cdDisk === 0xFFFF || onDisk === 0xFFFF || total === 0xFFFF ||
        cdSize === 0xFFFFFFFF || cdOff === 0xFFFFFFFF) throw zipNo('zip-zip64', 'the end record is a zip64 marker');
    if (disk !== 0 || cdDisk !== 0 || onDisk !== total) throw zipNo('zip-multi-disk', 'the zip spans several disks');
    if (total > ZIP_MAX_ENTRIES) throw zipNo('zip-too-many-entries', total + ' entries (at most ' + ZIP_MAX_ENTRIES + ')');
    if (cdOff + cdSize !== eocd) throw zipNo('zip-corrupt', 'the central directory does not end where the end record starts');
    var recs = [], p = cdOff;
    for (i = 0; i < total; i++) {
      var rec = zipCentral(b, p, i, eocd);
      recs.push(rec);
      p = rec.end;
    }
    if (p !== eocd) throw zipNo('zip-corrupt', 'the central directory holds more than its records');
    function partsOf(r) {
      var isDir = r.path.slice(-1) === '/', parts = r.path.split('/');
      if (isDir) parts.pop();
      return { parts: parts, isDir: isDir };
    }
    var top = [], folders = [], loose = false, kept, wrapper = null;
    for (i = 0; i < recs.length; i++) {
      var pp = partsOf(recs[i]), first = pp.parts[0];
      if (first.toLowerCase() === '__macosx' || first.charAt(0) === '.') continue;
      if (pp.parts.length === 1 && !pp.isDir) {
        loose = true;
        if (zipIsCapture(first)) top.push(recs[i]);
      } else if (folders.indexOf(first) < 0) folders.push(first);
    }
    if (top.length) kept = top;
    else if (!loose && folders.length === 1 && folders[0] !== '') {
      wrapper = folders[0]; kept = [];
      for (i = 0; i < recs.length; i++) {
        var q = partsOf(recs[i]);
        if (!q.isDir && q.parts.length === 2 && q.parts[0] === wrapper && zipIsCapture(q.parts[1])) kept.push(recs[i]);
      }
    } else kept = [];
    var sum = 0;
    for (i = 0; i < kept.length; i++) {
      kept[i].start = zipCheckKept(b, kept[i], cdOff);
      kept[i].cdStart = cdOff;
      sum += kept[i].usize;
      if (sum > ZIP_TOTAL_MAX) throw zipNo('zip-too-large', 'the captures are more than ' + ZIP_TOTAL_MAX + ' bytes together');
    }
    return { kept: kept, wrapper: wrapper };
  }
  // central record i at offset p, ending by bound; the name is capped
  // (ZIP_NAME_MAX raw bytes) before it is decoded (nam_zip._central)
  function zipCentral(b, p, i, bound) {
    if (p < 0 || p + 46 > bound || rd32(b, p) !== 0x02014B50) throw zipNo('zip-corrupt', 'central record ' + i + ' is out of bounds or has no signature');
    var flags = rd16(b, p + 8), nlen = rd16(b, p + 28), xlen = rd16(b, p + 30), clen = rd16(b, p + 32);
    var end = p + 46 + nlen + xlen + clen;
    if (end > bound) throw zipNo('zip-corrupt', 'central record ' + i + ' overruns the central directory');
    if (nlen > ZIP_NAME_MAX) throw zipNo('zip-name', 'the name of entry ' + i + ' is ' + nlen + ' bytes (at most ' + ZIP_NAME_MAX + ')');
    var name = zipNameText(b, p + 46, p + 46 + nlen, (flags & 0x0800) !== 0);
    return { index: i, flags: flags, method: rd16(b, p + 10), crc: rd32(b, p + 16), csize: rd32(b, p + 20),
      usize: rd32(b, p + 24), rawStart: p + 46, rawLen: nlen, path: name.replace(/\\/g, '/'),
      disk: rd16(b, p + 34), local: rd32(b, p + 42), central: p, end: end,
      z64: zipHasZip64Extra(b, p + 46 + nlen, p + 46 + nlen + xlen) };
  }
  // the checks of one kept entry against its local header; returns where its
  // data starts (zipScan: every kept entry; zipRead: that entry alone)
  function zipCheckKept(b, r, cdOff) {
    var what = 'entry ' + r.index + ' (' + JSON.stringify(r.path) + ')';
    if (r.flags & 0x0041) throw zipNo('zip-encrypted', what + ' is encrypted');
    if (r.method !== 0 && r.method !== 8) throw zipNo('zip-method', what + ' uses method ' + r.method + ' (only stored and deflate)');
    if (r.z64 || r.csize === 0xFFFFFFFF || r.usize === 0xFFFFFFFF || r.local === 0xFFFFFFFF) throw zipNo('zip-zip64', what + ' has zip64 fields');
    if (r.usize > ZIP_ENTRY_MAX) throw zipNo('zip-too-large', what + ' is ' + r.usize + ' bytes (at most ' + ZIP_ENTRY_MAX + ')');
    if (r.method === 0 && r.csize !== r.usize) throw zipNo('zip-corrupt', what + ' is stored with two different sizes');
    if (r.disk !== 0) throw zipNo('zip-multi-disk', what + ' starts on another disk');
    var lo = r.local;
    if (lo + 30 > cdOff || rd32(b, lo) !== 0x04034B50) throw zipNo('zip-corrupt', what + ': its local header is out of bounds or has no signature');
    var lflags = rd16(b, lo + 6), lnlen = rd16(b, lo + 26), lxlen = rd16(b, lo + 28);
    if (lflags & 0x0041) throw zipNo('zip-encrypted', what + ' is encrypted (local header)');
    var start = lo + 30 + lnlen + lxlen, same = start <= cdOff && lnlen === r.rawLen && rd16(b, lo + 8) === r.method;
    for (var k = 0; same && k < lnlen; k++) if (b[lo + 30 + k] !== b[r.rawStart + k]) same = false;
    if (!same) throw zipNo('zip-corrupt', what + ': its local header does not match the central record');
    if (zipHasZip64Extra(b, lo + 30 + lnlen, start)) throw zipNo('zip-zip64', what + ' has a zip64 extra (local header)');
    if (!(lflags & 0x0008) && (rd32(b, lo + 14) !== r.crc || rd32(b, lo + 18) !== r.csize || rd32(b, lo + 22) !== r.usize))
      throw zipNo('zip-corrupt', what + ': its local sizes or CRC differ from the central record');
    if (start + r.csize > cdOff) throw zipNo('zip-corrupt', what + ': its data overruns the central directory');
    return start;
  }
  /**
   * pickKind(names) — what the user picked or dropped, by the files' names
   * (ruled 2026-10-14, R2): {ok: true, kind: 'files'} (loose files, as
   * before; also an empty pick), {ok: true, kind: 'zip', index} (one zip
   * alone), or {ok: false, code}: 'zip-several' (two or more zips),
   * 'zip-mixed' (a zip and other files). A name is a zip when its last path
   * component ends with '.zip' in any case. A folder pick uses folderFiles.
   */
  function pickKind(names) {
    var zips = [];
    for (var i = 0; i < names.length; i++) if (zipLast(names[i]).toLowerCase().slice(-4) === '.zip') zips.push(i);
    if (!zips.length) return { ok: true, kind: 'files' };
    if (zips.length > 1) return { ok: false, code: 'zip-several' };
    if (names.length > 1) return { ok: false, code: 'zip-mixed' };
    return { ok: true, kind: 'zip', index: zips[0] };
  }
  /**
   * zipFiles(bytes, zipName) — the captures in a zip (ruled 2026-10-14, R1
   * and R3). bytes: the whole zip (Uint8Array); zipName: its file name as
   * picked. Returns {directory (the last path component of zipName without
   * '.zip' in any case; null when nothing is left), entries ([{path, name,
   * index, size, central, cdStart}] of the KEPT captures in central-directory
   * order; name is the last component, the capture's file name; size is
   * uncompressed; central is the offset of its central record and cdStart
   * that of the central directory, which zipRead uses instead of a new
   * scan), wrapper (null, or the one folder the captures lie in, whose name
   * is NOT used)}. ONE scan of the archive. Kept: the top-level '.nam' files
   * (any case, not starting with '.'); with none, when every other entry
   * lies under exactly one top-level folder, that folder's direct '.nam'
   * children. Never deeper. '__MACOSX' (any case) and top-level entries
   * starting with '.' are ignored. Names longer than 1024 bytes are refused
   * ('zip-name'). An empty list is not an error here. Throws
   * Error('zip-<code>: ...') for a refusal.
   */
  function zipFiles(bytes, zipName) {
    var s = zipScan(bytes), entries = [];
    for (var i = 0; i < s.kept.length; i++) {
      var r = s.kept[i];
      entries.push({ path: r.path, name: r.path.split('/').pop(), index: r.index, size: r.usize,
        central: r.central, cdStart: r.cdStart });
    }
    var dir = zipLast(zipName);
    if (dir.toLowerCase().slice(-4) === '.zip') dir = dir.slice(0, -4);
    return { directory: dir || null, entries: entries, wrapper: s.wrapper };
  }
  /**
   * zipRead(bytes, entry) — the bytes (Uint8Array) of one entry zipFiles
   * returned for these same bytes, verified, WITHOUT a new scan: its central
   * record (at entry.central) and its local header are read and checked
   * again, alone; then inflated with output bounded by the declared size,
   * the length equal to it ('zip-length'), the CRC-32 equal to the central
   * record's ('zip-crc'). Cost: that entry's size. Throws
   * Error('zip-<code>: ...') for a refusal; a plain Error (no code) for an
   * entry zipFiles did not return for these bytes.
   */
  function zipRead(bytes, entry) {
    var idx = entry && entry.index, at = entry && entry.central, cd = entry && entry.cdStart;
    if (!isInt(idx) || !isInt(at) || !isInt(cd)) throw new Error('the entry is not one zipFiles returned (index, central, cdStart)');
    if (!(cd >= 0 && cd <= at && at <= bytes.length - 22)) throw new Error('entry ' + idx + ' is not one zipFiles returned for these bytes');
    var r = zipCentral(bytes, at, idx, bytes.length - 22);
    if (r.path !== entry.path || r.usize !== entry.size) throw new Error('entry ' + idx + ' is not one zipFiles returned for these bytes');
    r.start = zipCheckKept(bytes, r, cd);
    var what = 'entry ' + r.index + ' (' + JSON.stringify(r.path) + ')', out;
    if (r.method === 0) {
      out = new Uint8Array(r.csize);
      for (var k = 0; k < r.csize; k++) out[k] = bytes[r.start + k];
    } else out = inflateRaw(bytes, r.start, r.start + r.csize, r.usize);
    if (out.length !== r.usize) throw zipNo('zip-length', what + ' inflates to ' + out.length + ' bytes, not the declared ' + r.usize);
    if (crc32(out, 0, out.length) !== r.crc) throw zipNo('zip-crc', what + ': the CRC-32 does not match');
    return out;
  }
  /**
   * checkSelection(captures, caps, lighter) — may this selection become ONE
   * effect, and on which engine?
   * captures: one object per file, in any order: {fileName, key (32 hex or
   *   16 bytes), usable (false: not an A2-Lite capture, or it failed the
   *   fidelity gate), sampleRate (44100 or 48000 for a usable capture)}.
   * caps: the CAP of the blank host of each engine, by kind: {plain, rs48}
   *   (NAM 44.1k, NAM 48k); with a family of hosts, the largest. An engine
   *   without a host is left out. lighter: "Lighter version" is ticked.
   * Returns {ok: true, kind, hostKind, order (the positions of captures in
   * knob order)} or {ok: false, code, ...}. The checks, in this order; the
   * first that fails is the answer:
   *   empty        no file
   *   too-many     more files than the largest host takes {count, maximum, kind: null}
   *   unusable     {files}: every unusable file, in knob order
   *   duplicate    {groups}: the files of each key that occurs twice or more
   *   mixed-rates  {files44k, files48k}: both rates, "Lighter version" not ticked
   *   too-many     more files than the engine's host takes {count, maximum, kind}
   * The engine: "Lighter version" or only 44.1 kHz captures: plain; only
   * 48 kHz captures: rs48. Throws on a caller's error (no host, a usable
   * capture without a rate).
   */
  function checkSelection(captures, caps, lighter) {
    var kinds = caps ? Object.keys(caps) : [], i, top = 0;
    if (!kinds.length) throw new Error('caps: the CAP (' + CAP_MIN + '..' + CAP_MAX + ') of the host of plain and/or rs48');
    kinds.forEach(function (k) {
      if (!Object.prototype.hasOwnProperty.call(KIND_CODE, k) || !isInt(caps[k]) || caps[k] < CAP_MIN || caps[k] > CAP_MAX) {
        throw new Error('caps: the CAP (' + CAP_MIN + '..' + CAP_MAX + ') of the host of plain and/or rs48');
      }
      if (caps[k] > top) top = caps[k];
    });
    if (!Array.isArray(captures)) throw new Error('the captures are a list');
    var names = [], keys = [];
    captures.forEach(function (c) {
      keys.push(keyHexOf(c.key, 'a capture key'));
      if (c.usable && RATES.indexOf(c.sampleRate) < 0) throw new Error('a usable capture has a sample rate of 44100 or 48000');
      names.push(String(c.fileName));
    });
    var n = captures.length, order = setOrder(names, keys);
    function no(code, more) { more = more || {}; more.ok = false; more.code = code; return more; }
    if (n === 0) return no('empty');
    if (n > top) return no('too-many', { count: n, maximum: top, kind: null });
    var bad = order.filter(function (j) { return !captures[j].usable; }).map(function (j) { return names[j]; });
    if (bad.length) return no('unusable', { files: bad });
    var seen = [], groups = [];
    order.forEach(function (j) {
      var g = seen.indexOf(keys[j]);
      if (g < 0) { seen.push(keys[j]); groups.push([names[j]]); } else groups[g].push(names[j]);
    });
    var twins = groups.filter(function (g) { return g.length > 1; });
    if (twins.length) return no('duplicate', { groups: twins });
    function atRate(rate) { return order.filter(function (j) { return captures[j].sampleRate === rate; }).map(function (j) { return names[j]; }); }
    var r44 = atRate(44100), r48 = atRate(48000), kind;
    if (lighter || !r48.length) kind = 'plain';
    else if (!r44.length) kind = 'rs48';
    else return no('mixed-rates', { files44k: r44, files48k: r48 });
    if (!Object.prototype.hasOwnProperty.call(caps, kind)) throw new Error('caps names no host for the ' + kind + ' engine');
    if (n > caps[kind]) return no('too-many', { count: n, maximum: caps[kind], kind: kind });
    return { ok: true, kind: kind, hostKind: KIND_HOST[kind], order: order };
  }
  /**
   * finalLabels(fileNames, fields) — the labels of an effect from its edit
   * fields (contract 6.2). fileNames and fields are in KNOB order; fields[k]
   * is what the field of capture k holds (null: never touched; fields
   * absent: none was).
   * A field's spaces at its ends are dropped; a field that is then empty
   * gets the AUTOMATIC label, which depends on the file names alone. A typed
   * label is never changed. It is REFUSED, each field with one code, when it
   * holds a character outside the label alphabet ('characters'), is longer
   * than 7 ('length'), or is identical to another label of the effect,
   * compared without case ('identical'; of an automatic and a typed label
   * that are identical, the typed one is refused).
   * Returns {labels, automatic, typed (which are the user's), refused
   * ([{at, code}]; empty = the labels may be built), hints (the positions
   * that read like another in the 4 characters the pedal draws at rest;
   * only when nothing is refused)}.
   */
  function finalLabels(fileNames, fields) {
    var auto = setLabels(fileNames), n = auto.length, i, j;
    if (fields != null && (!Array.isArray(fields) || fields.length !== n)) throw new Error('one label field per capture');
    var labels = [], mine = [], low = [], refused = [], hints = [];
    for (i = 0; i < n; i++) {
      var t = fields == null || fields[i] == null ? '' : String(fields[i]).replace(/^ +| +$/g, '');
      labels.push(t || auto[i]);
      mine.push(!!t);
      low.push(labels[i].toLowerCase());
    }
    for (i = 0; i < n; i++) {
      if (!mine[i]) continue;
      var lab = labels[i], foreign = false, twins = 0;
      for (j = 0; j < lab.length; j++) if (LABEL_CHARS.indexOf(lab.charAt(j)) < 0) foreign = true;
      for (j = 0; j < n; j++) if (low[j] === low[i]) twins++;
      if (foreign) refused.push({ at: i, code: 'characters' });
      else if (lab.length > LABEL_MAX) refused.push({ at: i, code: 'length' });
      else if (twins > 1) refused.push({ at: i, code: 'identical' });
    }
    if (!refused.length) {
      for (i = 0; i < n; i++) {
        for (j = 0; j < n; j++) if (j !== i && labelSeen(labels[j]) === labelSeen(labels[i])) { hints.push(i); break; }
      }
    }
    return { labels: labels, automatic: auto, typed: mine, refused: refused, hints: hints };
  }
  /**
   * finalName(fileNames, field, pedalFilename, directory, env) — the effect's
   * name from its edit field (contract 6.3). field: what the field holds
   * (null: never touched). What the user typed goes through spec §9.4 steps
   * 2 to 6 (NFKD, printable ASCII, one space between words, 11 characters,
   * the stock-name rule); it is NOT cut at a '/' and loses no '.nam'. A
   * field of which nothing is left gets the automatic name (setName).
   */
  function finalName(fileNames, field, pedalFilename, directory, env) {
    var auto = setName(fileNames, pedalFilename, directory, env);
    if (field == null) return auto;
    var nf = String(field).normalize('NFKD'), s = '';
    for (var i = 0; i < nf.length; i++) { var c = nf.charCodeAt(i); if (c >= 0x20 && c <= 0x7E) s += nf.charAt(i); }
    s = s.split(' ').filter(function (p) { return p; }).join(' ');
    if (!s) return auto;
    var name = s.slice(0, NAME_MAX).replace(/ +$/, '');
    var stock = stockOf(env).namesLower;
    function isStock(x) { return Object.prototype.hasOwnProperty.call(stock, x.toLowerCase()); }
    if (isStock(name)) name = s.slice(0, NAME_MAX - 4).replace(/ +$/, '') + ' NAM';
    if (isStock(name)) name = pedalFilename;
    return name;
  }

  /**
   * buildSetOutputs(results, opts, env) — the Results of processCapture, in
   * any order, -> ONE effect with a Model knob (contract sections 3 and 6).
   *   opts.hosts     {a2, r48}: the BLANK layout-7 host of each engine, as
   *                  bytes; an engine without a host is left out. CAP is
   *                  read from the host. Absent: the two hosts of env, when
   *                  env was made from the layout-7 hosts (0.7.1); in any
   *                  other environment a build without opts.hosts throws.
   *   opts.lighter   "Lighter version" is ticked
   *   opts.labels    the label fields, one per Result IN THE ORDER OF
   *                  results (null: never touched); absent: none
   *   opts.name      the name field (null or absent: never touched)
   *   opts.directory the folder the user gave, when there is one
   *   opts.resident  the pedal's effect list (see deriveIdentity)
   *   opts.icon      false: FOR TESTS, no icon is rendered (zic null)
   * Returns {ok: true, zd2, zic, fileName, zicName, name, labels, order,
   * hints, engine, identity, facts, sha256, crcHex}; order, and the
   * positions in hints, index results. Or {ok: false, refusal}: what the
   * user can put right, never thrown:
   *   checkSelection's refusals;
   *   {code: 'labels', fields: [{at (a position in results), code}]};
   *   {code: 'installed', filename, id}: these captures in this order are
   *   on the pedal already. Labels and the name are not in the identity,
   *   so the file is never written over: uninstall first (ruled 2026-10-05).
   * Throws on anything else: a host that is not a blank layout-7 host of
   * its engine, an identity outside its rules, a failed read-back.
   */
  function buildSetOutputs(results, opts, env) {
    opts = opts || {};
    if (!Array.isArray(results)) throw new Error('the captures are a list of processCapture results');
    // the hosts: opts.hosts when given; else those of the environment handed
    // in, when it was made from the hosts that take several captures
    var caps = {}, ek, i;
    var hosts = opts.hosts || (env && env.layout === LAYOUT7 && env.hosts ? { a2: env.hosts.a2.zd2, r48: env.hosts.r48.zd2 } : {});
    for (ek in HOSTS) {
      if (!hosts[ek]) continue;
      var hr = hostRegions(hosts[ek], 'the ' + HOSTS[ek].label + ' host');
      if (hr.kind !== HOSTS[ek].kind) throw new Error('the host given for ' + HOSTS[ek].label + ' is of the other kind');
      caps[HOSTS[ek].rs48 ? 'rs48' : 'plain'] = hr.cap;
    }
    function ready(r) { return !!(r && r.verdict === 'ready' && r._internal && r._internal.net); }
    var sel = checkSelection(results.map(function (r) {
      return { fileName: r.fileName, key: String(r.sha256).slice(0, 32), usable: ready(r), sampleRate: r.sampleRate };
    }), caps, !!opts.lighter);
    if (!sel.ok) return { ok: false, refusal: sel };
    var engine = sel.kind === 'rs48' ? 'r48' : 'a2', host = hosts[engine], rs48 = HOSTS[engine].rs48, order = sel.order;
    var ordered = order.map(function (j) { return results[j]; });
    var names = ordered.map(function (r) { return r.fileName; });
    var keys = ordered.map(function (r) { return r.sha256.slice(0, 32); });
    if (opts.labels != null && (!Array.isArray(opts.labels) || opts.labels.length !== results.length)) throw new Error('one label field per capture');
    var fl = finalLabels(names, opts.labels == null ? null : order.map(function (j) { return opts.labels[j]; }));
    if (fl.refused.length) {
      return { ok: false, refusal: { ok: false, code: 'labels', fields: fl.refused.map(function (f) { return { at: order[f.at], code: f.code }; }) } };
    }
    var ident = deriveSetIdentity(keys, HOSTS[engine].hostKind, opts.resident, env);
    if (ident.installed) return { ok: false, refusal: { ok: false, code: 'installed', filename: ident.filename, id: ident.id } };
    var id = ident.id >>> 0, fn = ident.filename, stock = stockOf(env);
    if ((id >>> 24) !== GROUP_PREAMP || (id & 0x00FF0000) || (id & 0xFFFF) < ID_BAND_LO || (id & 0xFFFF) >= ID_BAND_LO + ID_BAND_SIZE) {
      throw new Error('id ' + hex8(id) + ' is outside the NAM user-capture band 0x04001400-0x040017FF');
    }
    if (!FILE_RE.test(fn)) throw new Error('filename ' + fn + ' is not WFN + 5 characters of the capture alphabet');
    if (stock.ids[id]) throw new Error('id ' + hex8(id) + ' collides with a stock effect');
    if (stock.bases[fn + '.ZD2'] || stock.bases[fn + '.ZIC']) throw new Error('filename ' + fn + ' matches a stock file');
    var name = finalName(names, opts.name, fn, opts.directory, env);
    var err = validateName(name, env);
    if (err) throw new Error(err);
    // each capture packed again from its stored network, with the exponents
    // and the level step processCapture settled on (deterministic)
    var images = ordered.map(function (r) {
      var it = r._internal;
      if (!it.level || it.level.steps !== it.levelSteps) throw new Error(r.fileName + ': this capture has no level step (spec §5.8)');
      return packImage(it.net, rs48, it.rexp, it.levelSteps).words;
    });
    var sp = spliceSet(host, images, keys, fl.labels, { id: id, name: name });
    var out = sp.zd2, icon = null;
    if (opts.icon !== false) {
      var first = ordered[0];
      icon = renderIcon(name, engine, env, { cab: iconIncludesCab(first.meta && first.meta.gear_type) });
      var zic1 = checkZic(icon.zic);
      if (zic1.length) throw new Error('icon out of invariant: ' + zic1.join('; '));
    }
    // the final gate, as for one capture: the envelope, the identity and the
    // effect read back
    var env1 = checkEnvelope(out);
    if (env1.length) throw new Error('container envelope out of invariant: ' + env1.join('; '));
    var idr = readIdentity(out), back = readSet(out);
    if (idr.id !== id || idr.name !== name || idr.group !== GROUP_PREAMP || idr.groupName !== GROUP_NAME || idr.version !== readIdentity(host).version) {
      throw new Error('identity readback mismatch');
    }
    if (!back.agree || back.n !== keys.length || back.key !== ident.key) throw new Error('the effect reads back wrong');
    for (i = 0; i < keys.length; i++) if (back.keys[i] !== keys[i] || back.labels[i] !== fl.labels[i]) throw new Error('the effect reads back wrong');
    return { ok: true, zd2: out, zic: icon ? icon.zic : null, fileName: fn + '.ZD2', zicName: fn + '.ZIC', name: name,
      labels: fl.labels, automaticLabels: fl.automatic, typedLabels: fl.typed, order: order,
      hints: fl.hints.map(function (k) { return order[k]; }), engine: engine, identity: ident, facts: sp.facts,
      sha256: sp.facts.sha256, crcHex: hex8(sp.facts.crc),
      icon: icon ? { style: icon.style, cab: icon.cab, sha256: icon.sha256 } : null };
  }

  var NAMB = {
    VERSION: VERSION,
    HOSTS: HOSTS, SET_HOSTS: SET_HOSTS, LOAD_LIMIT_PROVEN_KB: LOAD_LIMIT_PROVEN_KB, GATE_ESR: GATE_ESR,
    makeEnv: makeEnv,
    // the explicit "no stock list" (makeEnv's data.stock, or {stock: NO_STOCK})
    NO_STOCK: NO_STOCK, STOCK_MISSING: STOCK_MISSING,
    processCapture: processCapture,
    deriveIdentity: deriveIdentity,
    isCaptureFilename: isCaptureFilename,
    deriveName: deriveName,
    validateName: validateName,
    renderIcon: renderIcon,
    iconIncludesCab: iconIncludesCab,
    buildOutputs: buildOutputs,
    renderPreview: renderPreview,
    // several captures in one effect (multi-profile-contract.md; layout 7)
    setKey: setKey,
    deriveSetIdentity: deriveSetIdentity,
    setOrder: setOrder,
    setLabels: setLabels,
    checkLabels: checkLabels,
    setName: setName,
    packImage: packImage,
    checkImage: checkImage,
    buildBlob: buildBlob,
    hostRegions: hostRegions,
    spliceSet: spliceSet,
    readSet: readSet,
    // the selection (contract 6.6) and the build from checked captures
    folderFiles: folderFiles,
    pickKind: pickKind,
    zipFiles: zipFiles,
    zipRead: zipRead,
    checkSelection: checkSelection,
    finalLabels: finalLabels,
    finalName: finalName,
    buildSetOutputs: buildSetOutputs,
    // exposed for the tests
    _: {
      sha256Hex: sha256Hex, crc32: crc32, zd2Crc: zd2Crc, zd2CheckEnvelope: zd2CheckEnvelope,
      zd2Chunks: zd2Chunks, blankInfo: blankInfo, spliceBytes: spliceBytes, setIdentity: setIdentity,
      readIdentity: readIdentity, checkEnvelope: checkEnvelope, checkZic: checkZic, zicParse: zicParse, loadIcons: loadIcons,
      ICON_DATA_SHA256: ICON_DATA_SHA256, parseCapture: parseCapture, weightsToNet: weightsToNet,
      rescaleA2: rescaleA2, forwardFloat: forwardFloat, forwardKernel: forwardKernel, quantize: quantize,
      pack: pack, kernelValidate: kernelValidate, chooseRingExpFromStats: chooseRingExpFromStats,
      rechannelRescale: rechannelRescale, parseRingExp: parseRingExp, roundHalfEven: roundHalfEven,
      esr: esr, hex8: hex8, b64ToBytes: b64ToBytes,
      // the output level (spec §5.8)
      level: { RULE: LEVEL_RULE, TARGET_DB: LEVEL_TARGET_DB, STEP_DB: LEVEL_STEP_DB, MAX_STEPS: LEVEL_MAX_STEPS,
        VOL_MAX: LEVEL_VOL_MAX, GUARD_CEILING: LEVEL_GUARD_CEILING, FIXD: FIXD_LIMIT, PEAK: LEVEL_PEAK,
        HP_K: LEVEL_HP_K, LP_K: LEVEL_LP_K, PLUCK_SHA256: LEVEL_PLUCK_SHA256, WARM_SHA256: LEVEL_WARM_SHA256,
        OSCALE_BITS: LEVEL_OSCALE_BITS },
      levelOscale: levelOscale, warmPluck: warmPluck, levelDb: levelDb, levelChoose: levelChoose,
      levelFixed: levelFixed, measureLevel: measureLevel, levelRecord: levelRecord, fidStats: fidStats,
      // several captures in one effect (contract sections 2 to 4, 6.1 to 6.3)
      set: { SET_MAX: SET_MAX, LABEL_MAX: LABEL_MAX, LABEL_SEEN: LABEL_SEEN, LABEL_CHARS: LABEL_CHARS, NAME_SHARED_MIN: NAME_SHARED_MIN,
        WORD_SEPS: WORD_SEPS, ORDER_RE: ORDER_RE, MAGIC7: MAGIC7, LAYOUT7: LAYOUT7, IDXW: IDXW, IMGW: IMGW,
        CAP_MIN: CAP_MIN, CAP_MAX: CAP_MAX, KIND_CODE: KIND_CODE, MODEL_NAME: MODEL_NAME,
        RATES: RATES, SELECTION_CODES: SELECTION_CODES, FIELD_CODES: FIELD_CODES, KIND_HOST: KIND_HOST },
      // a zip the user gives (contract 6.6 "A zip")
      zip: { MAX_ENTRIES: ZIP_MAX_ENTRIES, ENTRY_MAX: ZIP_ENTRY_MAX, TOTAL_MAX: ZIP_TOTAL_MAX, EOCD_SPAN: ZIP_EOCD_SPAN, NAME_MAX: ZIP_NAME_MAX,
        CODES: ZIP_CODES, PICK_CODES: PICK_CODES, CP437_HIGH: CP437_HIGH, inflateRaw: inflateRaw, utf8Strict: utf8Strict },
      blankIndex: blankIndex, blankLabelTable: blankLabelTable, reservationWords: reservationWords,
      cleanFileName: cleanFileName
    }
  };
  if (typeof module !== 'undefined' && module.exports) module.exports = NAMB;
  else root.NAMB = NAMB;
})(typeof window !== 'undefined' ? window : globalThis);
