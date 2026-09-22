// Compile the selected SVG without changing its design. ICO offsets refer to
// actual PNG bytes, with a separate rendered image for each Windows size.
const { chromium } = require('@playwright/test');
const fs = require('node:fs');

(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  try {
    const page = await browser.newPage({ deviceScaleFactor: 1 });
    await page.setContent('<style>html,body{margin:0;background:transparent}svg{display:block;width:100vw;height:100vh}</style>' + fs.readFileSync('public/friday.svg', 'utf8'));
    const sizes = [16, 24, 32, 48, 64, 128, 256];
    const images = [];
    for (const size of sizes) {
      await page.setViewportSize({ width: size, height: size });
      images.push(await page.screenshot({ omitBackground: true }));
    }
    const header = Buffer.alloc(6 + sizes.length * 16);
    header.writeUInt16LE(1, 2);
    header.writeUInt16LE(sizes.length, 4);
    let offset = header.length;
    sizes.forEach((size, i) => {
      const entry = 6 + i * 16;
      header[entry] = header[entry + 1] = size % 256;
      header.writeUInt16LE(1, entry + 4);
      header.writeUInt16LE(32, entry + 6);
      header.writeUInt32LE(images[i].length, entry + 8);
      header.writeUInt32LE(offset, entry + 12);
      offset += images[i].length;
    });
    fs.writeFileSync('public/friday.png', images.at(-1));
    fs.writeFileSync('public/friday.ico', Buffer.concat([header, ...images]));
    console.log('Friday icon compiled at 16–256 px from public/friday.svg');
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
