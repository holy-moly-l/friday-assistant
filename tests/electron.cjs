const {_electron:electron,expect}=require('@playwright/test');const path=require('node:path');
(async()=>{
  const app=await electron.launch({executablePath:path.resolve('release/Friday-win32-x64/Friday.exe'),args:['--use-fake-device-for-media-stream',`--use-file-for-fake-audio-capture=${path.resolve('data/voice-sample.wav')}%noloop`],timeout:60000});
  const window=await app.firstWindow();
  await expect(window.getByRole('heading',{name:'Чем могу помочь?'})).toBeVisible({timeout:45000});
  await expect.poll(()=>window.evaluate(()=>fetch('/api/health').then(r=>r.json()).then(h=>Object.values(h.services).every(s=>s==='ready'))),{timeout:120000}).toBe(true);
  await window.screenshot({path:'data/friday-desktop.png'});
  await window.getByRole('switch',{name:'Голосовые ответы',exact:true}).click();
  await window.getByRole('button',{name:'Начать запись',exact:true}).click();
  await expect(window.locator('.message.user .message-text')).toContainText('умеешь',{timeout:30000});
  await expect(window.locator('.message.assistant .message-text')).not.toBeEmpty({timeout:20000});
  await expect(window.getByRole('button',{name:'Начать запись',exact:true})).toBeEnabled({timeout:15000});
  await window.getByRole('switch',{name:'Голосовые ответы',exact:true}).click();
  await window.getByRole('button',{name:'Новый разговор',exact:true}).click();
  await app.close();
  console.log('DESKTOP PASS: packaged exe launch, trusted microphone permission, recording, transcription, response, clean exit');
})().catch(e=>{console.error(e);process.exit(1)});
