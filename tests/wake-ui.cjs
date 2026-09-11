const {chromium,expect}=require('@playwright/test');const fs=require('node:fs');const path=require('node:path');const {spawn}=require('node:child_process');
(async()=>{
 const server=spawn(path.resolve('.venv/Scripts/python.exe'),['-u','tests/wake_server.py'],{windowsHide:true,env:{...process.env,PYTHONUTF8:'1',FRIDAY_DESKTOP_PID:String(process.pid)}});
 let logs='';server.stderr.on('data',b=>logs+=b.toString());let browser;
 try{
  await expect.poll(async()=>{try{return(await fetch('http://127.0.0.1:17839/api/health')).ok}catch{return false}},{timeout:45000}).toBe(true);
  const runtime=JSON.parse(fs.readFileSync('data/wake-test-runtime.json','utf8'));
  browser=await chromium.launch({channel:'msedge',headless:true,args:['--use-fake-ui-for-media-stream','--use-fake-device-for-media-stream','--autoplay-policy=no-user-gesture-required',`--use-file-for-fake-audio-capture=${path.resolve('data/wake-minimized.wav')}%noloop`]});
  const context=await browser.newContext({permissions:['microphone'],viewport:{width:1440,height:960}});
  await context.addInitScript(()=>localStorage.setItem('friday-prefs',JSON.stringify({voice:false,wake:true})));
  const page=await context.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto(`http://127.0.0.1:${runtime.port}/#token=${runtime.token}`);
  await expect(page.locator('.wake-badge')).toContainText('Жду обращения',{timeout:15000});
  await expect(page.locator('.message.user .message-text')).toContainText('который час',{ignoreCase:true,timeout:35000});
  await expect(page.locator('.message.assistant .message-text')).toContainText('Сейчас',{timeout:10000});
  await expect(page.locator('.message.user')).toHaveCount(1);
  await page.keyboard.press('Escape');
  await expect(page.locator('.wake-badge')).toHaveCount(0);
  await page.getByRole('button',{name:'Настройки',exact:true}).click();
  await expect(page.getByRole('switch',{name:'Активация по слову Пятница'})).toHaveAttribute('aria-checked','false');
  // Re-enabling is tested through the actual switch, not injected state.
  await page.getByRole('switch',{name:'Активация по слову Пятница'}).click();
  await expect(page.locator('.wake-state')).toContainText('Жду обращения',{timeout:10000});
  await page.locator('.wake-card').screenshot({path:'data/wake-settings.png'});
  await page.getByRole('button',{name:'Проверить микрофон',exact:true}).click();
  await expect(page.locator('.wake-state')).toContainText('на паузе');
  await page.getByRole('button',{name:'Остановить проверку',exact:true}).click();
  await expect(page.locator('.wake-state')).toContainText('Жду обращения',{timeout:10000});
  await page.getByRole('switch',{name:'Активация по слову Пятница'}).click();
  await expect(page.locator('.wake-state')).toContainText('выключена');
  if(errors.length)throw new Error(errors.join('\n'));
  console.log('WAKE UI PASS: AudioWorklet -> authenticated websocket -> real Vosk -> real Whisper -> command -> reply; Esc/off/re-enable');
 }catch(e){console.error(logs);throw e;}finally{await browser?.close();server.kill();}
})().catch(e=>{console.error(e);process.exitCode=1});
