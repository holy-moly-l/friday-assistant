// Real webcam in Electron, isolated app profile; no frames are saved or printed.
const {_electron:electron,expect}=require('@playwright/test');
const fs=require('node:fs');const os=require('node:os');const path=require('node:path');
(async()=>{
 const profile=fs.mkdtempSync(path.join(os.tmpdir(),'friday-camera-check-'));let app;
 try{
  app=await electron.launch({args:[path.resolve('.'),'--user-data-dir='+profile],env:{...process.env,PYTHONUTF8:'1'},timeout:60000});
  const page=await app.firstWindow();await page.waitForLoadState('domcontentloaded');
  await page.getByRole('button',{name:'Камера и жесты',exact:true}).click();
  const cameras=await page.evaluate(async()=> (await navigator.mediaDevices.enumerateDevices()).filter(d=>d.kind==='videoinput').map(d=>d.label||'camera'));
  console.log('Physical camera candidates:',cameras);
  if(!cameras.length)throw Error('No webcam available');
  await page.getByRole('button',{name:'Включить камеру',exact:true}).click();
  await expect(page.locator('.camera-live')).toBeVisible({timeout:35000});
  await expect.poll(()=>page.locator('video').evaluate(v=>v.currentTime),{timeout:10000}).toBeGreaterThan(5);
  const state=await page.locator('video').evaluate(v=>({width:v.videoWidth,height:v.videoHeight,state:v.srcObject.getVideoTracks()[0].readyState}));
  const tracking=await page.locator('.camera-badges').innerText();
  expect(state.state).toBe('live');expect(state.width).toBeGreaterThan(100);
  // Keep a reference solely to check track release, never retain pixels.
  await page.evaluate(()=>window.cameraTestTrack=document.querySelector('video').srcObject.getVideoTracks()[0]);
  await app.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows()[0].minimize());
  await expect.poll(()=>page.evaluate(()=>window.cameraTestTrack.readyState)).toBe('ended');
  await app.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows()[0].restore());
  await expect(page.getByRole('button',{name:'Включить камеру',exact:true})).toBeVisible();
  expect(await page.evaluate(()=>window.cameraTestTrack.readyState)).toBe('ended');
  console.log('REAL ELECTRON WEBCAM PASS:',JSON.stringify(state),tracking.replaceAll('\n',' · '),'minimize releases camera, restore does not restart');
 }finally{
  if(app)await app.close();
  // Only the fresh, resolved test-profile directory is removed.
  const resolved=path.resolve(profile);if(path.dirname(resolved)!==path.resolve(os.tmpdir())||!path.basename(resolved).startsWith('friday-camera-check-'))throw Error('Unsafe temp path');
  fs.rmSync(resolved,{recursive:true,force:true,maxRetries:5,retryDelay:200});
 }
})().catch(e=>{console.error(e);process.exitCode=1});
