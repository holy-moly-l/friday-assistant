const {spawn}=require('node:child_process');const fs=require('node:fs');const path=require('node:path');
(async()=>{
 const server=spawn(path.resolve('.venv/Scripts/python.exe'),['-u','tests/voice_server.py'],{windowsHide:true,env:{...process.env,PYTHONUTF8:'1',FRIDAY_DESKTOP_PID:String(process.pid)}});
 server.stderr.on('data',b=>process.stderr.write(b));
 try{
  let health;for(let i=0;i<120;i++){try{health=await(await fetch('http://127.0.0.1:17840/api/health')).json();if(Object.values(health.services).every(x=>x==='ready'))break;}catch{}await new Promise(r=>setTimeout(r,1000));}
  if(!health||!Object.values(health.services).every(x=>x==='ready'))throw Error('Models unavailable');
  console.log('ALL MODELS READY');const runtime=JSON.parse(fs.readFileSync('data/voice-test-runtime.json'));
  const started=Date.now();const res=await fetch('http://127.0.0.1:17840/api/speech',{method:'POST',headers:{'Content-Type':'application/json','X-Friday-Token':runtime.token},body:JSON.stringify({text:'Привет. Я Пятница, ваша персональная помощница. Все системы готовы. С чего начнём?',speaker:'qwen-serena'}),signal:AbortSignal.timeout(220000)});
  console.log('SYNTHESIS',res.status,Math.round((Date.now()-started)/1000)+'s');if(!res.ok)throw Error(await res.text());fs.writeFileSync('data/voice-diagnose.wav',Buffer.from(await res.arrayBuffer()));
 }finally{server.kill();}
})().catch(e=>{console.error(e);process.exitCode=1;});
