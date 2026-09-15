const {chromium,expect}=require('@playwright/test');
const {spawn}=require('node:child_process');
const fs=require('node:fs');
const path=require('node:path');
(async()=>{
 const server=spawn(path.resolve('.venv/Scripts/python.exe'),['tests/telegram_ui_server.py'],{windowsHide:true,env:{...process.env,PYTHONUTF8:'1',FRIDAY_DESKTOP_PID:String(process.pid)}});
 let browser,logs='';server.stderr.on('data',b=>logs+=b.toString());
 try{
  await expect.poll(async()=>{try{return(await fetch('http://127.0.0.1:17841/api/health')).ok}catch{return false}},{timeout:30000}).toBe(true);
  const runtime=JSON.parse(fs.readFileSync('data/telegram-ui-runtime.json','utf8'));
  const state=async()=>await(await fetch('http://127.0.0.1:17841/api/test-telegram',{headers:{'X-Friday-Token':runtime.token}})).json();
  browser=await chromium.launch({channel:'msedge',headless:true});
  const page=await browser.newPage({viewport:{width:1280,height:900}});const errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  await page.addInitScript(()=>localStorage.setItem('friday-prefs',JSON.stringify({voice:false,wake:false})));
  await page.goto(`http://127.0.0.1:17841/#token=${runtime.token}`);
  await page.getByRole('button',{name:'Только чат',exact:true}).click();
  async function send(text){await page.getByRole('textbox',{name:'Сообщение Пятнице'}).fill(text);await page.getByRole('button',{name:'Отправить',exact:true}).click();}
  const answer=()=>page.locator('.message.assistant .message-text').last();
  await send('Напиши Насте');await expect(answer()).toContainText('Что написать Насте?');
  await send('Привет, я задержусь на час');
  await expect(page.getByRole('button',{name:'Отправить сообщение',exact:true})).toBeVisible();
  await expect(page.locator('.desktop-approval blockquote')).toHaveText('Привет, я задержусь на час');
  expect((await state()).sent).toBe(0);expect((await state()).draft_length).toBeGreaterThan(0);
  await page.screenshot({path:'data/telegram-approval-ui.png'});
  await page.getByRole('button',{name:'Нет',exact:true}).click();
  await expect(answer()).toContainText('не отправляла');
  await expect.poll(async()=>(await state()).draft_length).toBe(0);
  await send('Отправь Насте сообщение привет');
  await page.getByRole('button',{name:'Отправить сообщение',exact:true}).click();
  await expect(answer()).toHaveText('Отправила Насте.');expect((await state()).sent).toBe(1);
  await send('Ответь ей, что буду позже');
  await expect(page.getByRole('button',{name:'Отправить сообщение',exact:true})).toBeVisible();
  await page.getByRole('button',{name:'Стоп',exact:true}).click();
  await expect(page.getByRole('button',{name:'Отправить сообщение',exact:true})).toHaveCount(0);
  await expect.poll(async()=>(await state()).draft_length).toBe(0);expect((await state()).sent).toBe(1);
  expect(errors).toEqual([]);
  console.log('TELEGRAM UI PASS: literal draft, confirmation, No, stop, context, no unapproved send');
 }catch(e){console.error(logs);throw e;}
 finally{if(browser)await browser.close();server.kill();}
})().catch(e=>{console.error(e);process.exit(1)});
