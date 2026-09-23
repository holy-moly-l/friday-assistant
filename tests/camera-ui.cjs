const {chromium,expect}=require('@playwright/test');
const {spawn}=require('node:child_process');
const fs=require('node:fs');const path=require('node:path');
(async()=>{
 if(!fs.existsSync('data/right_hands.jpg')){
  const response=await fetch('https://storage.googleapis.com/mediapipe-assets/right_hands.jpg');
  if(!response.ok)throw Error('Could not download official hand fixture');
  fs.mkdirSync('data',{recursive:true});fs.writeFileSync('data/right_hands.jpg',Buffer.from(await response.arrayBuffer()));
 }
 const server=spawn(path.resolve('.venv/Scripts/python.exe'),['tests/gesture_server.py'],{windowsHide:true,env:{...process.env,PYTHONUTF8:'1'}});
 let browser,logs='';server.stderr.on('data',b=>logs+=b.toString());
 try{
  await expect.poll(async()=>{try{return(await fetch('http://127.0.0.1:17843/api/health')).ok}catch{return false}},{timeout:15000}).toBe(true);
  const runtime=JSON.parse(fs.readFileSync('data/gesture-runtime.json','utf8'));
  browser=await chromium.launch({channel:'msedge',headless:true,args:['--use-fake-ui-for-media-stream','--use-fake-device-for-media-stream']});
  const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[],external=[];
  page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(!r.url().startsWith('http://127.0.0.1:17843')&&!r.url().startsWith('blob:'))external.push(r.url());});
  page.on('console',m=>{if(m.type()==='error')console.log('BROWSER',m.text().slice(0,350));});
  await page.addInitScript(()=>{
    localStorage.setItem('friday-prefs',JSON.stringify({voice:false,wake:false}));
    navigator.mediaDevices.getUserMedia=async()=>{
      const img=new Image();img.src='/test-hands.jpg';await img.decode();
      const canvas=document.createElement('canvas');canvas.width=640;canvas.height=480;
      const ctx=canvas.getContext('2d');ctx.drawImage(img,0,0,640,480);
      const stream=canvas.captureStream(20);window.testStream=stream;
      const interval=setInterval(()=>ctx.drawImage(img,0,0,640,480),50);
      stream.getTracks()[0].addEventListener('ended',()=>clearInterval(interval));
      return stream;
    };
  });
  await page.goto(`http://127.0.0.1:17843/#token=${runtime.token}`);
  await page.getByRole('button',{name:'Камера и жесты',exact:true}).click();
  await expect(page.getByRole('button',{name:'Включить управление',exact:true})).toBeDisabled();
  await page.screenshot({path:'data/camera-off-ui.png'});
  await page.getByRole('button',{name:'Включить камеру',exact:true}).click();
  await expect(page.locator('.camera-live')).toBeVisible({timeout:35000});
  await expect(page.locator('.camera-badges')).toContainText('2 / 2 руки',{timeout:20000});
  await page.screenshot({path:'data/camera-hands-ui.png'});
  await page.getByLabel('Окно для жестов',{exact:true}).selectOption(String(runtime.hwnd));
  await page.getByRole('button',{name:'Включить управление',exact:true}).click();
  await expect(page.getByRole('button',{name:'Остановить управление',exact:true})).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(page.getByRole('button',{name:'Включить управление',exact:true})).toBeVisible();
  await page.getByRole('button',{name:'Включить управление',exact:true}).click();
  await expect(page.getByRole('button',{name:'Остановить управление',exact:true})).toBeVisible();
  await page.evaluate(async()=>fetch('/api/desktop/stop',{method:'POST',headers:{'X-Friday-Token':sessionStorage.getItem('friday-token')}}));
  await expect(page.getByRole('button',{name:'Включить управление',exact:true})).toBeVisible();
  await page.getByRole('button',{name:'Помощник',exact:true}).click();
  expect(await page.evaluate(()=>window.testStream.getTracks().every(t=>t.readyState==='ended'))).toBe(true);
  await page.getByRole('button',{name:'Камера и жесты',exact:true}).click();
  await page.evaluate(()=>{navigator.mediaDevices.getUserMedia=async()=>{throw new DOMException('denied','NotAllowedError')};});
  await page.getByRole('button',{name:'Включить камеру',exact:true}).click();
  await expect(page.getByRole('alert')).toContainText('Доступ к камере запрещён');
  expect(errors).toEqual([]);expect(external).toEqual([]);
  console.log('CAMERA UI PASS: local worker/WASM, real model detects two hands, no external requests, arm, Esc, voice-stop endpoint, camera cleanup, denied permission');
 }catch(e){console.error(logs);throw e;}finally{if(browser)await browser.close();server.kill();}
})().catch(e=>{console.error(e);process.exitCode=1});
