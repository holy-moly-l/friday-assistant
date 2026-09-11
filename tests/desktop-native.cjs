const {_electron:electron,expect}=require('@playwright/test');const {spawn}=require('node:child_process');const fs=require('node:fs');const path=require('node:path');
(async()=>{
 try{await fetch('http://127.0.0.1:17835/api/health');throw Error('Close Friday before isolated desktop test');}catch(e){if(e.message.startsWith('Close Friday'))throw e;}
 const oldRuntime=fs.existsSync('data/runtime.json')?fs.readFileSync('data/runtime.json'):null;
 const profile=fs.mkdtempSync(path.resolve('data/native-desktop-profile-'));
 const server=spawn(path.resolve('.venv/Scripts/python.exe'),['-u','tests/desktop_server.py'],{windowsHide:true,env:{...process.env,PYTHONUTF8:'1',FRIDAY_DESKTOP_PID:String(process.pid)}});
 let logs='',app;server.stderr.on('data',b=>logs+=b.toString());
 try{
  await expect.poll(async()=>{try{return(await(await fetch('http://127.0.0.1:17835/api/health')).json()).services.stt==='ready'}catch{return false}},{timeout:60000}).toBe(true);
  app=await electron.launch({executablePath:path.resolve('release/Friday-win32-x64/Friday.exe'),args:[`--user-data-dir=${profile}`,'--use-fake-device-for-media-stream',`--use-file-for-fake-audio-capture=${path.resolve('data/desktop-stop.wav')}%noloop`],timeout:60000});
  const page=await app.firstWindow();await page.waitForLoadState('load');await expect(page.getByRole('button',{name:'Настройки',exact:true})).toBeVisible();
  const win=await app.browserWindow(page);await expect.poll(()=>win.evaluate(w=>w.isVisible())).toBe(true);
  await page.evaluate(()=>localStorage.setItem('friday-prefs',JSON.stringify({voice:false,wake:false})));await page.reload();
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.getByRole('button',{name:'Только чат',exact:true}).click();
  async function send(text){await page.getByRole('textbox',{name:'Сообщение Пятнице'}).fill(text);await page.getByRole('button',{name:'Отправить',exact:true}).click();}
  await send('Нажми продолжить');await expect(page.getByRole('button',{name:'Подтвердить действие'})).toBeVisible({timeout:12000});
  await page.screenshot({path:'data/desktop-approval.png'});
  await page.getByRole('button',{name:'Подтвердить действие'}).click();
  await expect(page.locator('.message.assistant .message-text').last()).toContainText('подтверждено',{timeout:12000});
  await send('Нажми отправить');await expect(page.getByRole('button',{name:'Подтвердить действие'})).toBeVisible({timeout:12000});
  await page.getByRole('button',{name:'Отмена',exact:true}).click();
  await expect(page.locator('.message.assistant .message-text').last()).toContainText('не подтверждено',{timeout:12000});
  await send('Что за ошибка вылезла?');
  // The fixture's label was changed by Continue. The model should describe the actual current UI.
  await expect(page.locator('.message.assistant .message-text').last()).not.toHaveText('',{timeout:60000});
  await expect(page.getByRole('button',{name:'Отправить',exact:true})).toBeVisible({timeout:60000});
  await page.getByRole('button',{name:'Настройки',exact:true}).click();await page.getByRole('tab',{name:'Система',exact:true}).click();
  await expect(page.getByRole('combobox',{name:'Модель понимания'})).toHaveValue('qwen3.5:4b');
  await page.screenshot({path:'data/desktop-settings.png'});
  await page.getByRole('tab',{name:'Голос и микрофон',exact:true}).click();await page.getByRole('switch',{name:'Активация по слову Пятница'}).click();
  await page.getByRole('button',{name:'Помощник',exact:true}).click();
  await send('Нажми отправить');await expect(page.getByRole('button',{name:'Подтвердить действие'})).toBeVisible({timeout:12000});
  await win.evaluate(w=>w.minimize());
  await expect(page.getByRole('button',{name:'Подтвердить действие'})).toHaveCount(0,{timeout:20000});
  const runtime=JSON.parse(fs.readFileSync('data/desktop-test-runtime.json'));
  const expired=await fetch('http://127.0.0.1:17835/api/desktop/approve',{method:'POST',headers:{'X-Friday-Token':runtime.token,'Content-Type':'application/json'},body:JSON.stringify({nonce:'invalid',allow:true})});expect(expired.status).toBe(409);
  expect(await win.evaluate(w=>w.isMinimized())).toBe(true);
  expect(await page.locator('.wake-badge').count()).toBe(1);
  if(errors.length)throw Error(errors.join('\n'));
  console.log('DESKTOP NATIVE PASS: UIA click, approval/refusal, local reasoning, model settings, real Vosk STOP while minimized, expired approval rejected');
 }catch(e){console.error(logs);throw e;}
 finally{
  if(app)await app.close();server.kill();await new Promise(r=>setTimeout(r,1200));
  if(oldRuntime)fs.writeFileSync('data/runtime.json',oldRuntime);else if(fs.existsSync('data/runtime.json'))fs.unlinkSync('data/runtime.json');
  if(profile.startsWith(path.resolve('data')+path.sep))fs.rmSync(profile,{recursive:true,force:true});
 }
})().catch(e=>{console.error(e);process.exit(1)});
