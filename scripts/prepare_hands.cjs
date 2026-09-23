// Runtime assets are served locally. No CDN or model downloads while using the camera.
const fs = require('node:fs/promises');
const path = require('node:path');
const crypto = require('node:crypto');
const root = path.resolve(__dirname, '..');
const url = 'https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task';
(async () => {
  const dest = path.join(root, 'public', 'hand-tracking');
  await fs.mkdir(dest, {recursive: true});
  await fs.cp(path.join(root, 'node_modules/@mediapipe/tasks-vision/wasm'), path.join(dest, 'wasm'), {recursive: true});
  const model = path.join(dest, 'hand_landmarker.task');
  if (!(await fs.stat(model).catch(() => null))?.size) {
    const response = await fetch(url, {signal: AbortSignal.timeout(120000)});
    if (!response.ok) throw new Error(`Hand model download: ${response.status}`);
    const data = Buffer.from(await response.arrayBuffer());
    const header = data.indexOf(Buffer.from('PK\x03\x04'));
    if (data.length < 1000000 || header < 0 || header > 16) throw new Error('Invalid hand model');
    await fs.writeFile(model + '.partial', data); await fs.rename(model + '.partial', model);
  }
  const data = await fs.readFile(model);
  const sha = crypto.createHash('sha256').update(data).digest('hex');
  if (sha !== 'fbc2a30080c3c557093b5ddfc334698132eb341044ccee322ccf8bcf3607cde1') throw new Error('Hand model checksum mismatch');
  const runtime = JSON.parse(await fs.readFile(path.join(root, 'node_modules/@mediapipe/tasks-vision/package.json'), 'utf8')).version;
  await fs.writeFile(path.join(dest, 'source.json'), JSON.stringify({url, sha256: sha, runtime}, null, 2));
  console.log(`Local hand model ready: ${(data.length/1024/1024).toFixed(1)} MB, sha256=${sha}`);
})().catch(e => {console.error(e); process.exit(1);});
