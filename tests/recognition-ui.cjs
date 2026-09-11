const {chromium,expect}=require('@playwright/test');const fs=require('node:fs');const path=require('node:path');const {spawn}=require('node:child_process');
(async()=>{
 const server=spawn(path.resolve('.venv/Scripts/python.exe'),['-u','tests/wake_server.py'],{windowsHide:true,env:{...process.env,PYTHONUTF8:'1',FRIDAY_DESKTOP_PID:String(process.pid)}});
 let browser,logs='';server.stderr.on('data',b=>logs+=b.toString());
 try{
  await expect.poll(async()=>{try{return(await fetch('http://127.0.0.1:17839/api/health')).ok}catch{return false}},{timeout:60000}).toBe(true);
  const runtime=JSON.parse(fs.readFileSync('data/wake-test-runtime.json'));
  browser=await chromium.launch({channel:'msedge',headless:true,args:['--use-fake-ui-for-media-stream','--use-fake-device-for-media-stream','--autoplay-policy=no-user-gesture-required',`--use-file-for-fake-audio-capture=${path.resolve('data/wake-command.wav')}%noloop`]});
  const context=await browser.newContext({permissions:['microphone'],viewport:{width:1440,height:960}});
  await context.addInitScript(()=>localStorage.setItem('friday-prefs',JSON.stringify({voice:false,wake:false})));
  const page=await context.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto(`http://127.0.0.1:${runtime.port}/#token=${runtime.token}`);
  await page.getByRole('button',{name:'Настройки',exact:true}).click();
  await page.getByRole('button',{name:'Проверить распознавание',exact:true}).click();
  await expect(page.getByRole('button',{name:'Проверить микрофон',exact:true})).toBeDisabled();
  await expect(page.getByLabel('Результат распознавания')).toContainText('час',{timeout:35000});
  await expect(page.getByLabel('Прослушать запись микрофона')).toBeVisible();
  const sessions=await(await fetch(`http://127.0.0.1:${runtime.port}/api/sessions`,{headers:{'X-Friday-Token':runtime.token}})).json();
  expect(sessions).toHaveLength(0);
  await page.getByLabel('Результат распознавания').scrollIntoViewIfNeeded();await page.screenshot({path:'data/recognition-settings.png'});
  await page.getByRole('tab',{name:'Система',exact:true}).click();await expect(page.getByText('Whisper Large v3 Turbo',{exact:true})).toBeVisible();
  await page.getByRole('button',{name:'Помощник',exact:true}).click();
  await page.getByRole('button',{name:'Начать запись',exact:true}).click();
  await expect(page.locator('.message.user .message-text')).toContainText('час',{timeout:25000});
  await expect(page.locator('.message.assistant .message-text')).toContainText('Сейчас',{timeout:10000});
  expect(errors).toHaveLength(0);console.log('RECOGNITION UI PASS: diagnostic does not execute commands; manual microphone -> auto-stop -> Turbo -> actual clock command; playback and cleanup');
 }catch(e){console.error(logs);throw e;}finally{await browser?.close();server.kill();}
})().catch(e=>{console.error(e);process.exitCode=1});
