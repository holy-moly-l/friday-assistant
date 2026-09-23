// Own silent audio session only; never acts on the user's Telegram/browser media.
const {chromium,expect}=require('@playwright/test');const {spawn}=require('node:child_process');const fs=require('node:fs');const path=require('node:path');
(async()=>{
 const server=spawn(path.resolve('.venv/Scripts/python.exe'),['tests/gesture_server.py'],{windowsHide:true,env:{...process.env,PYTHONUTF8:'1'}});
 let browser,logs='';server.stderr.on('data',b=>logs+=b);
 try{
  await expect.poll(async()=>{try{return(await fetch('http://127.0.0.1:17843/api/health')).ok}catch{return false}},{timeout:15000}).toBe(true);
  const runtime=JSON.parse(fs.readFileSync('data/gesture-runtime.json','utf8'));
  const api=async(route,body)=>{const r=await fetch('http://127.0.0.1:17843/api/gestures/'+route,{method:body?'POST':'GET',headers:{'X-Friday-Token':runtime.token,'Content-Type':'application/json'},body:body?JSON.stringify(body):undefined});const data=await r.json();if(!r.ok)throw Error(JSON.stringify(data));return data;};
  browser=await chromium.launch({channel:'msedge',headless:false,args:['--autoplay-policy=no-user-gesture-required']});
  const page=await browser.newPage();
  const size=44100*60*2,wav=Buffer.alloc(44+size);wav.write('RIFF');wav.writeUInt32LE(size+36,4);wav.write('WAVEfmt ',8);wav.writeUInt32LE(16,16);wav.writeUInt16LE(1,20);wav.writeUInt16LE(1,22);wav.writeUInt32LE(44100,24);wav.writeUInt32LE(88200,28);wav.writeUInt16LE(2,32);wav.writeUInt16LE(16,34);wav.write('data',36);wav.writeUInt32LE(size,40);
  await page.route('**/test-tone.wav',r=>{
    const range=r.request().headers().range;
    if(!range)return r.fulfill({contentType:'audio/wav',body:wav,headers:{'Accept-Ranges':'bytes'}});
    const match=/bytes=(\d+)-(\d*)/.exec(range),start=Number(match[1]),end=match[2]?Math.min(Number(match[2]),wav.length-1):wav.length-1;
    return r.fulfill({status:206,contentType:'audio/wav',body:wav.subarray(start,end+1),headers:{'Accept-Ranges':'bytes','Content-Range':`bytes ${start}-${end}/${wav.length}`}});
  });
  await page.route('**/test-player',r=>r.fulfill({contentType:'text/html',body:'<!doctype html><title>Friday gesture media test</title><h1>Friday · Silent media test</h1><audio controls src="/test-tone.wav"></audio>'}));
  await page.goto('http://127.0.0.1:17843/test-player');
  await page.evaluate(async()=>{
    const a=document.querySelector('audio');navigator.mediaSession.metadata=new MediaMetadata({title:'Friday Gesture Test ONLY',artist:'Disposable test'});
    const update=()=>{if(a.duration)navigator.mediaSession.setPositionState({duration:a.duration,playbackRate:1,position:a.currentTime});};
    navigator.mediaSession.setActionHandler('play',()=>{void a.play();navigator.mediaSession.playbackState='playing';});
    navigator.mediaSession.setActionHandler('pause',()=>{a.pause();navigator.mediaSession.playbackState='paused';});
    navigator.mediaSession.setActionHandler('seekto',d=>{a.currentTime=d.seekTime;update();});
    a.addEventListener('timeupdate',update);a.addEventListener('seeked',update);await a.play();navigator.mediaSession.playbackState='playing';a.currentTime=15;update();
  });
  await expect.poll(()=>page.locator('audio').evaluate(a=>a.currentTime),{timeout:5000}).toBeGreaterThan(14);
  let target;
  await expect.poll(async()=>{const t=await api('targets');target=t.media.find(s=>s.title==='Friday Gesture Test ONLY');return !!target;},{timeout:20000}).toBe(true);
  if(!target.seek)throw Error('Test browser session did not publish seek support');
  const {token}=await api('arm',{mode:'media',media:target.id});let sequence=0;
  const beat=setInterval(()=>api('heartbeat',{token}).catch(()=>{}),400);
  try{
    console.log('MEDIA pause');
    await api('action',{token,sequence:++sequence,kind:'play_pause'}).catch(async e=>{console.log('paused actual:',await page.locator('audio').evaluate(a=>a.paused));throw e;});
    expect(await page.locator('audio').evaluate(a=>a.paused)).toBe(true);
    await new Promise(r=>setTimeout(r,1050));
    const before=await page.locator('audio').evaluate(a=>a.currentTime);
    console.log('MEDIA seek forward');
    await api('action',{token,sequence:++sequence,kind:'seek_forward'}).catch(async e=>{console.log('seek actual:',await page.locator('audio').evaluate(a=>a.currentTime),'before:',before);throw e;});
    expect(await page.locator('audio').evaluate(a=>a.currentTime)).toBeCloseTo(before+5,0);
    await new Promise(r=>setTimeout(r,1050));
    await api('action',{token,sequence:++sequence,kind:'seek_backward'});
    expect(await page.locator('audio').evaluate(a=>a.currentTime)).toBeCloseTo(before,0);
    await new Promise(r=>setTimeout(r,1050));
    await api('action',{token,sequence:++sequence,kind:'play_pause'});
    expect(await page.locator('audio').evaluate(a=>a.paused)).toBe(false);
    await api('stop',{});
    console.log('REAL WINDOWS MEDIA PASS: own Edge session, pause/play, seek +5/-5 seconds, verified state');
  }finally{clearInterval(beat);}
 }catch(e){console.error(logs);throw e;}finally{if(browser)await browser.close();server.kill();}
})().catch(e=>{console.error(e);process.exitCode=1});
