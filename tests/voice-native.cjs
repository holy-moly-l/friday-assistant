const {_electron:electron,expect}=require('@playwright/test');const {spawn}=require('node:child_process');const fs=require('node:fs');const path=require('node:path');
(async()=>{
 try{await fetch('http://127.0.0.1:17835/api/health');throw Error('Close Friday before the isolated desktop test');}catch(e){if(e.message.startsWith('Close Friday'))throw e;}
 const oldRuntime=fs.existsSync('data/runtime.json')?fs.readFileSync('data/runtime.json'):null;
 const profile=fs.mkdtempSync(path.resolve('data/native-voice-profile-'));
 const server=spawn(path.resolve('.venv/Scripts/python.exe'),['-u','tests/voice_server.py'],{windowsHide:true,env:{...process.env,PYTHONUTF8:'1',FRIDAY_DESKTOP_PID:String(process.pid),VOICE_TEST_PORT:'17835',VOICE_NATIVE_TEST:'1'}});
 let logs='',app;server.stderr.on('data',b=>logs+=b.toString());
 try{
  await expect.poll(async()=>{try{return Object.values((await(await fetch('http://127.0.0.1:17835/api/health')).json()).services).every(x=>x==='ready')}catch{return false}},{timeout:120000}).toBe(true);
  app=await electron.launch({executablePath:path.resolve('release/Friday-win32-x64/Friday.exe'),args:[`--user-data-dir=${profile}`,'--use-fake-device-for-media-stream',`--use-file-for-fake-audio-capture=${path.resolve('data/wake-plain.wav')}%noloop`],timeout:60000});
  const page=await app.firstWindow();await page.waitForLoadState('load');
  await expect(page.getByRole('button',{name:'Настройки',exact:true})).toBeVisible();
  const win=await app.browserWindow(page);await expect.poll(()=>win.evaluate(w=>w.isVisible())).toBe(true);
  await page.evaluate(()=>localStorage.setItem('friday-prefs',JSON.stringify({voice:true,wake:false,speaker:'qwen-serena'})));await page.reload();
  await page.evaluate(()=>{
    window.voiceEvents=[];const play=HTMLMediaElement.prototype.play;
    HTMLMediaElement.prototype.play=function(){this.addEventListener('ended',()=>window.voiceEvents.push({type:'ended',duration:this.duration}),{once:true});return play.call(this).then(()=>window.voiceEvents.push({type:'play',duration:this.duration}));};
  });
  await page.getByRole('button',{name:'Настройки',exact:true}).click();
  for(const [i,speaker] of ['qwen-serena','qwen-sohee','qwen-anna'].entries()){
    await page.getByRole('combobox',{name:'Тембр голоса'}).selectOption(speaker);await page.getByRole('button',{name:'Послушать голос',exact:true}).click();
    await expect.poll(()=>page.evaluate(()=>window.voiceEvents.filter(e=>e.type==='play').length),{timeout:5000}).toBe(i+1);
    await expect.poll(()=>page.evaluate(()=>window.voiceEvents.filter(e=>e.type==='ended').length),{timeout:15000}).toBe(i+1);
  }
  await page.getByRole('combobox',{name:'Тембр голоса'}).selectOption('qwen-serena');
  await page.getByRole('button',{name:'Помощник',exact:true}).click();await page.getByRole('textbox',{name:'Сообщение Пятнице'}).fill('Который час?');await page.getByRole('button',{name:'Отправить',exact:true}).click();
  await win.evaluate(w=>w.minimize());
  await expect.poll(()=>page.evaluate(()=>window.voiceEvents.filter(e=>e.type==='ended').length),{timeout:90000}).toBe(4);
  if(!await win.evaluate(w=>w.isMinimized()))throw Error('Window unexpectedly restored');
  const events=await page.evaluate(()=>window.voiceEvents);if(events.some(e=>!Number.isFinite(e.duration)||e.duration<.2))throw Error('Invalid playback duration');
  console.log('NATIVE VOICE PASS: all 3 previews played to completion; typed command was spoken while minimized',JSON.stringify(events));
 }catch(e){console.error(logs);throw e;}finally{
  await app?.close().catch(()=>{});server.kill();
  if(oldRuntime)fs.writeFileSync('data/runtime.json',oldRuntime);else fs.rmSync('data/runtime.json',{force:true});
  const resolved=path.resolve(profile);if(!resolved.startsWith(path.resolve('data')+path.sep)||!path.basename(resolved).startsWith('native-voice-profile-'))throw Error('Unsafe test profile path');
  fs.rmSync(resolved,{recursive:true,force:true,maxRetries:5,retryDelay:200});
 }
})().catch(e=>{console.error(e);process.exitCode=1;});
