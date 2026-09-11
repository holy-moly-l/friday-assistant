const {_electron:electron,expect}=require('@playwright/test');
const fs=require('node:fs');const path=require('node:path');const {execFileSync}=require('node:child_process');
(async()=>{
  const app=await electron.launch({executablePath:path.resolve('release/Friday-win32-x64/Friday.exe'),timeout:60000});
  try {
    const page=await app.firstWindow();
    await expect.poll(()=>page.evaluate(()=>fetch('/api/health').then(r=>r.json()).then(h=>Object.values(h.services).every(s=>s==='ready'))),{timeout:120000}).toBe(true);
    const runtime=JSON.parse(fs.readFileSync('data/runtime.json','utf8'));
    const origin=`http://127.0.0.1:${runtime.port}/api`;
    const headers={'X-Friday-Token':runtime.token,'Content-Type':'application/json'};
    const started=Date.now();
    const response=await fetch(origin+'/speech',{method:'POST',headers,body:JSON.stringify({text:'Все системы готовы.',speaker:'qwen-sohee'}),signal:AbortSignal.timeout(230000)});
    if(!response.ok)throw new Error(await response.text());
    const wav=Buffer.from(await response.arrayBuffer());
    if(wav.toString('ascii',0,4)!=='RIFF'||wav.length<10000)throw new Error('Invalid speech WAV');
    fs.writeFileSync('data/qwen-api-sample.wav',wav);
    const form=new FormData();form.append('audio',new Blob([wav],{type:'audio/wav'}),'voice.wav');
    const transcript=await (await fetch(origin+'/transcribe',{method:'POST',headers:{'X-Friday-Token':runtime.token},body:form})).json();
    if(!transcript.text?.toLowerCase().includes('готов'))throw new Error('Incorrect Russian speech: '+JSON.stringify(transcript));
    console.log('QWEN API PASS',JSON.stringify({seconds:(Date.now()-started)/1000,transcript:transcript.text}));
    await page.getByRole('button',{name:'Настройки',exact:true}).click();
    await expect(page.getByRole('heading',{name:'Микрофон',exact:true})).toBeVisible();
    await page.getByRole('combobox',{name:'Тембр голоса'}).selectOption('qwen-sohee');
    await page.getByRole('tab',{name:'Система',exact:true}).click();
    await page.getByRole('button',{name:'Обновить состояние моделей'}).click();
    await expect(page.getByText('Qwen3-TTS 0.6B',{exact:true})).toBeVisible();
    await page.screenshot({path:'data/friday-settings.png',fullPage:true});
    // Leave the fast voice selected so opening the app gives immediate spoken feedback.
    await page.getByRole('tab',{name:'Голос и микрофон',exact:true}).click();
    await page.getByRole('combobox',{name:'Тембр голоса'}).selectOption('xenia');
    const children=JSON.parse(execFileSync(path.resolve('.venv/Scripts/python.exe'),['-c',`import psutil,json; print(json.dumps([p.pid for p in psutil.Process(${runtime.pid}).children(recursive=True)]))`],{encoding:'utf8'}));
    if(children.length<2)throw new Error('Expected the CUDA voice worker and Windows redirector');
    await app.close();
    const alive=pid=>{try{process.kill(pid,0);return true;}catch{return false;}};
    await expect.poll(()=>[runtime.pid,...children].filter(alive),{timeout:15000}).toEqual([]);
    console.log('LIFECYCLE PASS: backend and CUDA worker exited with desktop');
  } finally {await app.close().catch(()=>{});}
})().catch(e=>{console.error(e);process.exit(1)});
