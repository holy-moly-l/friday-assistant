const {_electron:electron,expect}=require('@playwright/test');const path=require('node:path');
(async()=>{
  const app=await electron.launch({executablePath:path.resolve('release/Friday-win32-x64/Friday.exe'),args:process.env.FRIDAY_TEST_PROFILE?[`--user-data-dir=${process.env.FRIDAY_TEST_PROFILE}`]:[],timeout:60000});
  const page=await app.firstWindow();
  await expect.poll(()=>page.evaluate(()=>fetch('/api/health').then(r=>r.json()).then(h=>Object.values(h.services).every(s=>s==='ready'))),{timeout:120000}).toBe(true);
  await expect(page.locator('.error-banner')).toHaveCount(0);
  await page.screenshot({path:'data/friday-preview.png'});
  await page.getByRole('button',{name:'Настройки',exact:true}).click();
  await page.getByRole('tab',{name:'Система',exact:true}).click();
  await expect(page.getByText('Распознавание русской речи · NVIDIA GPU')).toBeVisible();
  await page.screenshot({path:'data/friday-settings.png'});
  await app.close();
  console.log('STARTUP PASS: exe automatically launched backend, all 3 local models ready, NVIDIA recognition, clean exit');
})().catch(e=>{console.error(e);process.exit(1)});
