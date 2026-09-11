const {chromium,expect}=require('@playwright/test');const {spawn}=require('node:child_process');const fs=require('node:fs');const path=require('node:path');
(async()=>{
 const server=spawn(path.resolve('.venv/Scripts/python.exe'),['-u','tests/voice_server.py'],{windowsHide:true,env:{...process.env,PYTHONUTF8:'1',FRIDAY_DESKTOP_PID:String(process.pid)}});
 let logs='',browser;server.stderr.on('data',b=>logs+=b.toString());
 try{
  await expect.poll(async()=>{try{return Object.values((await(await fetch('http://127.0.0.1:17840/api/health')).json()).services).every(x=>x==='ready')}catch{return false}},{timeout:120000}).toBe(true);
  const runtime=JSON.parse(fs.readFileSync('data/voice-test-runtime.json'));const base='http://127.0.0.1:17840';const headers={'X-Friday-Token':runtime.token,'Content-Type':'application/json'};
  browser=await chromium.launch({channel:'msedge',headless:true,args:['--autoplay-policy=no-user-gesture-required']});
  const context=await browser.newContext({viewport:{width:1440,height:960}});
  await context.addInitScript(()=>{
    localStorage.setItem('friday-prefs',JSON.stringify({voice:true,wake:false,speaker:'qwen-serena'}));
    window.voiceEvents=[];const play=HTMLMediaElement.prototype.play;
    window.speechSizes=[];const originalFetch=window.fetch;
    window.fetch=async(...args)=>{const response=await originalFetch(...args);if(String(args[0]).endsWith('/speech')&&response.ok){void response.clone().arrayBuffer().then(b=>window.speechSizes.push(b.byteLength));}return response;};
    HTMLMediaElement.prototype.play=function(){this.addEventListener('ended',()=>window.voiceEvents.push({type:'ended',duration:this.duration}),{once:true});return play.call(this).then(()=>{window.voiceEvents.push({type:'play',duration:this.duration});});};
  });
  const page=await context.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
  const recordings=[];
  page.on('response',async response=>{
    if(response.url().endsWith('/api/speech')&&response.ok()){
      const body=response.request().postDataJSON();
      recordings.push({body});
    }
  });
  await page.goto(`${base}/#token=${runtime.token}`);
  for(const speaker of ['qwen-serena','qwen-sohee','qwen-anna']){
    await page.getByRole('button',{name:'Настройки',exact:true}).click();
    await page.getByRole('combobox',{name:'Тембр голоса'}).selectOption(speaker);
    const before=await page.evaluate(()=>window.voiceEvents.filter(x=>x.type==='play').length);const start=Date.now();
    await page.getByRole('button',{name:'Послушать голос',exact:true}).click();
    await expect.poll(()=>page.evaluate(()=>window.voiceEvents.filter(x=>x.type==='play').length),{timeout:5000}).toBe(before+1);
    console.log('PREVIEW',speaker,Date.now()-start,'ms');
    await expect(page.locator('.voice-progress')).toHaveCount(0,{timeout:15000});
    await expect(page.getByRole('switch',{name:'Озвучивать ответы',exact:true})).toHaveAttribute('aria-checked','true');
    await page.getByRole('button',{name:'Помощник',exact:true}).click();
    await page.getByRole('textbox',{name:'Сообщение Пятнице'}).fill('Который час?');
    const began=Date.now();await page.getByRole('button',{name:'Отправить',exact:true}).click();
    await expect(page.locator('.message.assistant .message-text').last()).toContainText('Сейчас');
    await expect.poll(()=>page.evaluate(()=>window.voiceEvents.filter(x=>x.type==='play').length),{timeout:155000}).toBe(before+2);
    console.log('SPOKEN COMMAND',speaker,Date.now()-began,'ms');
    await expect.poll(()=>page.evaluate(()=>window.voiceEvents.filter(x=>x.type==='ended').length),{timeout:20000}).toBe((before+2));
  }
  // Abort an actual CUDA request and confirm that the worker stops instead of
  // leaving the following preview/command behind an abandoned queue entry.
  const controller=new AbortController();
  const pending=fetch(base+'/api/speech',{method:'POST',headers,body:JSON.stringify({text:'Это длинная проверка отмены. Эта запись должна быть остановлена до окончания синтеза.',speaker:'qwen-serena'}),signal:controller.signal}).catch(e=>e);
  await expect.poll(async()=>(await(await fetch(base+'/api/health')).json()).expressive_voice,{timeout:10000}).toBe('synthesizing');
  controller.abort();await pending;
  await expect.poll(async()=>(await(await fetch(base+'/api/health')).json()).expressive_voice,{timeout:10000}).toBe('available');
  const resumed=await fetch(base+'/api/speech',{method:'POST',headers,body:JSON.stringify({text:'ignored',speaker:'qwen-serena',preview:true}),signal:AbortSignal.timeout(3000)});
  if(!resumed.ok)throw Error('Preview blocked after cancellation');
  console.log('CANCEL PASS: disconnected request stopped CUDA; preview available immediately');
  const sizes=await page.evaluate(()=>window.speechSizes);if(sizes.length!==6||sizes.some(n=>n<1000))throw Error('Empty audio received in browser');
  for(const recording of recordings){
    // Reuse the exact generated phrase from the server cache; Chromium's CDP
    // response.body() can be empty for a body consumed as a playback blob.
    const cached=await fetch(base+'/api/speech',{method:'POST',headers,body:JSON.stringify(recording.body)});
    if(!cached.ok)throw Error('Cannot retrieve generated speech');
    const wav=Buffer.from(await cached.arrayBuffer());
    fs.writeFileSync(`data/verified-${recording.body.speaker}-${recording.body.preview?'preview':'command'}.wav`,wav);
    const form=new FormData();form.append('audio',new Blob([wav],{type:'audio/wav'}),'test.wav');
    const response=await fetch(base+'/api/transcribe',{method:'POST',headers:{'X-Friday-Token':runtime.token},body:form});
    if(!response.ok)throw Error('Speech verification failed '+response.status+': '+await response.text());const {text}=await response.json();
    const expected=recording.body.preview?'пятниц':'сейчас';
    if(!text.toLowerCase().includes(expected))throw Error('Unexpected spoken text: '+text);
    console.log('TRANSCRIPT',recording.body.speaker,recording.body.preview?'preview':'command',text);
  }
  if(errors.length)throw Error(errors.join('\n'));
  await page.getByRole('button',{name:'Настройки',exact:true}).click();await page.locator('.voice-card').screenshot({path:'data/voice-fixed-settings.png'});
  console.log('VOICE REGRESSION PASS');
 }catch(e){console.error(logs);throw e;}finally{await browser?.close();server.kill();}
})().catch(e=>{console.error(e);process.exitCode=1});
