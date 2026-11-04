// Local adapter for Thomas Hammer's MIT-licensed NAM core. No MIDI or network.
'use strict';
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const root = path.resolve(__dirname, '../..');
const vendor = path.join(root, 'third_party/waveformer-nam');
const pins = JSON.parse(fs.readFileSync(path.join(vendor, 'pins.json'), 'utf8'));
function read(name) {
  const bytes = fs.readFileSync(path.join(vendor, name));
  if (crypto.createHash('sha256').update(bytes).digest('hex') !== pins.files[name])
    throw Error('Waveformer resource checksum mismatch: ' + name);
  return bytes;
}
read('nam-core.cjs');
const core = require(path.join(vendor, 'nam-core.cjs'));
const host = read('WFNAM44.ZD2');
const regions = core.hostRegions(host, 'pinned 44.1 kHz host');
const chunks = core._.zd2Chunks(host);
const iconChunk = chunks.find(c => c.tag === 'ICON');

function bankIcon() {
  return read('nam2zoom-artwork.bin');
}

function replaceIcon(zd2, bitmap) {
  const chunk = core._.zd2Chunks(zd2).find(c => c.tag === 'ICON');
  const length = Buffer.alloc(4); length.writeUInt32LE(bitmap.length);
  const out = Buffer.concat([zd2.subarray(0, chunk.start - 4), length, bitmap,
    zd2.subarray(chunk.start + chunk.len)]);
  out.writeUInt32LE(core._.zd2Crc(out) >>> 0, 8);
  return out;
}

function validate(zd2, zic) {
  const back = core.readSet(zd2);
  const identity = core._.readIdentity(zd2);
  const legacy = bankIcon(), frameStart = 8 + legacy.readUInt32LE(4);
  const frameBytes = legacy.readUInt16LE(8) * Math.ceil(legacy.readUInt16LE(10) / 8);
  if (!zic.equals(legacy)) throw Error('Original nam2zoom artwork must be preserved byte-for-byte');
  const actualIcon = core._.zd2Chunks(zd2).find(c => c.tag === 'ICON');
  if (actualIcon.len !== frameBytes || !zd2.subarray(actualIcon.start, actualIcon.start + frameBytes)
      .equals(legacy.subarray(frameStart, frameStart + frameBytes))) throw Error('Original embedded artwork differs');
  // Normalize only the container icon length for comparison. This shifts the
  // DATA chunk in the file, but never changes any ELF byte or loaded address.
  const normalized = replaceIcon(zd2, host.subarray(iconChunk.start, iconChunk.start + iconChunk.len));
  const actualRegions = core.hostRegions(zd2, 'built effect', -1);
  if (normalized.length !== host.length || identity.id !== 0x04001787 || identity.name !== 'N2Z Bank'
      || identity.group !== 4 || identity.groupName !== 'PREAMP' || back.kind !== 0
      || back.n < 1 || back.n > 3 || !back.agree) throw Error('Optimized bank identity/index is invalid');
  core.checkLabels(back.labels);
  const words = new Uint32Array(pins.imageWords);
  for (let n = 0; n < back.n; n++) {
    for (let i = 0; i < words.length; i++) words[i] = zd2.readUInt32LE(actualRegions.blob + 4 * (back.offsets[n] + i));
    if (words[1] !== 23) throw Error('Full 23-layer A2 Lite image required');
    core.checkImage(words, 0, 'model ' + (n + 1));
  }
  // Allow exactly the upstream splice regions, the fixed N2Z identity, CRC,
  // and the first icon frame. DSP instructions and DSP reservation stay pinned.
  const spans = [[8,12], [95,122], [regions.blob, regions.blob + regions.reserved * 4],
    [regions.labels, regions.labels + back.n * 8], [regions.param + 12, regions.param + 16],
    [regions.param + 20, regions.param + 24]];
  for (let i = 0; i < host.length; i++) {
    if (normalized[i] !== host[i] && !spans.some(([a,b]) => i >= a && i < b))
      throw Error('Optimized host changed outside permitted data at byte ' + i);
  }
  const errors = core._.checkEnvelope(zd2).concat(core._.checkZic(zic));
  if (errors.length) throw Error(errors.join('; '));
  return back;
}

async function main() {
  const request = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
  if (request.validate) {
    const back = validate(fs.readFileSync(request.validate), fs.readFileSync(request.icon));
    console.log('Verified optimized 44.1 kHz host, model index, icon and unchanged DSP instructions (' + back.n + ' models)');
    return;
  }
  if (!Array.isArray(request.models) || request.models.length < 1 || request.models.length > 3)
    throw Error('Choose 1–3 A2 Lite 44.1 kHz models');
  core.checkLabels(request.models.map(m => m.label));
  const env = core.makeEnv({
    hosts: { a2: {zd2: host.toString('base64')}, r48: {zd2: read('WFNAM48.ZD2').toString('base64')} },
    signals: { probe: read('probe.f64').toString('base64'), pluck: read('pluck.f64').toString('base64') },
    icons: {json: read('icon-data.json').toString('utf8')},
    // Builds keep the app's existing identity. Live stock/id/name collision
    // checks remain mandatory in the guarded Python installer.
    stock: core.NO_STOCK
  });
  const results = [], images = [];
  for (const model of request.models) {
    const bytes = fs.readFileSync(model.path);
    const parsed = core._.parseCapture(bytes.toString('utf8'));
    if (!parsed.ok || parsed.sampleRate !== 44100)
      throw Error(path.basename(model.path) + ': full A2 Lite at an explicit 44100 Hz is required; retrain this capture first');
    let stage = '';
    const result = await core.processCapture(bytes, path.basename(model.path), env, (p,s) => {
      if (s !== stage) { stage = s; console.log(model.label + ': ' + s); }
    });
    if (result.verdict !== 'ready') throw Error(model.label + ': ' + JSON.stringify(result.refusal));
    const it = result._internal;
    images.push(core.packImage(it.net, false, it.rexp, it.levelSteps).words);
    results.push(result);
  }
  const labels = request.models.map(m => m.label);
  const spliced = core.spliceSet(host, images, results.map(r => r.sha256.slice(0,32)), labels,
    {id: 0x04001787, name: 'N2Z Bank'});
  const icon = bankIcon();
  const zicStart = 8 + icon.readUInt32LE(4);
  const frameBytes = icon.readUInt16LE(8) * Math.ceil(icon.readUInt16LE(10) / 8);
  const effect = replaceIcon(Buffer.from(spliced.zd2), icon.subarray(zicStart, zicStart + frameBytes));
  validate(effect, icon);
  fs.mkdirSync(request.output, {recursive: true});
  fs.writeFileSync(path.join(request.output, 'N2ZBANK.ZD2'), effect);
  fs.writeFileSync(path.join(request.output, 'N2ZBANK.ZIC'), icon);
  const report = {engine: 'waveformer-a2-44100-v0.21', coreVersion: core.VERSION,
    sampleRate: 44100, modelProfile: 'lite', declaredDspLoad: 134.5, patchBudget: 270,
    measuredDspPercent: null, hostSha256: pins.files['WFNAM44.ZD2'], labels,
    captures: results.map((r,i) => ({label: labels[i], name: r.fileName, sha256: r.sha256, analysis: r.analysis}))};
  fs.writeFileSync(path.join(request.output, 'engine-report.json'), JSON.stringify(report, null, 2) + '\n');
  console.log('Built full A2 Lite 44.1 kHz effect using Waveformer v0.21; declared DSP reservation 134.5 / 270 (49.8%). Actual DSP use requires pedal testing.');
}
main().catch(e => { console.error(e.stack || e); process.exitCode = 1; });
