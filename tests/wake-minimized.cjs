const {_electron:electron,expect}=require('@playwright/test');const fs=require('node:fs');const path=require('node:path');const {spawn,execFile}=require('node:child_process');const {promisify}=require('node:util');
(async()=>{
 try{await fetch('http://127.0.0.1:17835/api/health');throw new Error('Close Friday before this isolated native test');}catch(e){if(e.message.includes('Close Friday'))throw e;}
 const oldRuntime=fs.existsSync('data/runtime.json')?fs.readFileSync('data/runtime.json'):null;
 const server=spawn(path.resolve('.venv/Scripts/python.exe'),['-u','tests/wake_server.py'],{windowsHide:true,env:{...process.env,PYTHONUTF8:'1',FRIDAY_DESKTOP_PID:String(process.pid),WAKE_TEST_PORT:'17835',WAKE_NATIVE_TEST:'1'}});
 let logs='';server.stderr.on('data',b=>logs+=b.toString());let app,page,oldPrefs;
 try{
  await expect.poll(async()=>{try{return(await fetch('http://127.0.0.1:17835/api/health')).ok}catch{return false}},{timeout:45000}).toBe(true);
  const protocol=await promisify(execFile)(path.resolve('.venv/Scripts/python.exe'),['tests/wake_protocol.py'],{env:{...process.env,PYTHONUTF8:'1'},windowsHide:true});console.log(protocol.stdout);
  app=await electron.launch({executablePath:path.resolve('release/Friday-win32-x64/Friday.exe'),args:[...(process.env.FRIDAY_TEST_PROFILE?[`--user-data-dir=${process.env.FRIDAY_TEST_PROFILE}`]:[]),'--use-fake-device-for-media-stream',`--use-file-for-fake-audio-capture=${path.resolve('data/wake-minimized.wav')}%noloop`],timeout:60000});
  page=await app.firstWindow();
  // firstWindow can resolve before main's loadURL; reloading then aborts startup.
  await page.waitForLoadState('domcontentloaded');
  await expect(page.getByRole('button',{name:'Настройки',exact:true})).toBeVisible({timeout:15000});
  oldPrefs=await page.evaluate(()=>localStorage.getItem('friday-prefs'));
  await page.evaluate(()=>{const prefs=JSON.parse(localStorage.getItem('friday-prefs')||'{}');localStorage.setItem('friday-prefs',JSON.stringify({...prefs,voice:false,wake:true}));});
  await page.reload();
  await expect(page.locator('.wake-badge')).toContainText('Жду обращения',{timeout:15000});
  const window=await app.browserWindow(page);await window.evaluate(win=>win.minimize());
  await expect.poll(()=>window.evaluate(win=>win.isMinimized())).toBe(true);
  await expect(page.locator('.message.assistant .message-text')).toContainText('Сейчас',{timeout:35000});
  await expect(page.locator('.message.user .message-text')).toContainText('час');
  await expect(page.locator('.message.user')).toHaveCount(1);
  if(!await window.evaluate(win=>win.isMinimized()))throw new Error('Window restored unexpectedly');
  await window.evaluate(win=>win.restore());
  await page.keyboard.press('Escape');
  await expect(page.locator('.wake-badge')).toHaveCount(0);
  await page.getByRole('button',{name:'Настройки',exact:true}).click();
  await page.locator('.wake-card').screenshot({path:'data/wake-native-settings.png'});
  console.log('NATIVE MINIMIZED PASS: actual Friday.exe, real Vosk + Whisper, selected microphone pipeline, one command and reply while window stayed minimized');
 }catch(e){console.error(logs);throw e;}finally{
  if(page&&oldPrefs!==undefined)await page.evaluate(value=>value===null?localStorage.removeItem('friday-prefs'):localStorage.setItem('friday-prefs',value),oldPrefs).catch(()=>{});
  await app?.close().catch(()=>{});server.kill();
  if(oldRuntime)fs.writeFileSync('data/runtime.json',oldRuntime);else fs.rmSync('data/runtime.json',{force:true});
 }
})().catch(e=>{console.error(e);process.exitCode=1});
