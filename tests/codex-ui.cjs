const {chromium,expect}=require('@playwright/test');
const {spawn}=require('node:child_process');const fs=require('node:fs');const path=require('node:path');const os=require('node:os');
(async()=>{
 const temp=fs.mkdtempSync(path.join(os.tmpdir(),'friday-codex-ui-'));
 const server=spawn(path.resolve('.venv/Scripts/python.exe'),['-u','tests/catalog_server.py'],{windowsHide:true,env:{...process.env,PYTHONUTF8:'1',FRIDAY_DATA_DIR:temp,FRIDAY_DESKTOP_PID:String(process.pid)}});
 let browser;let logs='';server.stderr.on('data',b=>logs+=b.toString());
 try{
  await expect.poll(async()=>{try{return(await fetch('http://127.0.0.1:17839/api/health')).ok}catch{return false}},{timeout:30000}).toBe(true);
  const runtime=JSON.parse(fs.readFileSync('data/catalog-test-runtime.json'));
  browser=await chromium.launch({channel:'msedge',headless:true});const page=await browser.newPage({viewport:{width:1440,height:960}});
  await page.addInitScript(()=>localStorage.setItem('friday-prefs',JSON.stringify({voice:false,wake:false})));
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto(`http://127.0.0.1:${runtime.port}/#token=${runtime.token}`);
  await page.getByRole('button',{name:'Настройки',exact:true}).click();
  await page.getByRole('tab',{name:'Система',exact:true}).click();
  const mode=page.getByRole('combobox',{name:'Режим AI'}),model=page.getByRole('combobox',{name:'Облачная модель'});
  await expect(mode).toHaveValue('hybrid');await expect(model).toHaveValue('gpt-5.6-luna');
  const vision=page.getByRole('combobox',{name:'Провайдер анализа экрана'});
  await expect(vision).toHaveValue('ollama');await vision.selectOption('codex');await expect(vision).toBeEnabled();
  await expect(vision).toHaveValue('codex');await vision.selectOption('ollama');await expect(vision).toBeEnabled();
  await expect(page.getByText('Codex: Подключён через ChatGPT',{exact:false})).toBeVisible();
  await expect(page.getByText(/API.?key|OPENAI_API_KEY/i)).toHaveCount(0);
  await model.selectOption('gpt-5.6-terra');await expect(model).toBeEnabled();
  await mode.selectOption('local');await expect(model).toHaveCount(0);
  await expect(mode).toBeEnabled();await mode.selectOption('codex_vision');await expect(model).toHaveValue('gpt-5.6-terra');
  await model.selectOption('gpt-5.6-luna');await expect(model).toBeEnabled();await mode.selectOption('hybrid');
  await expect(mode).toBeEnabled();
  await page.screenshot({path:'data/codex-settings.png',fullPage:true});
  await page.reload();await page.getByRole('button',{name:'Настройки',exact:true}).click();await page.getByRole('tab',{name:'Система',exact:true}).click();
  await expect(mode).toHaveValue('hybrid');await expect(model).toHaveValue('gpt-5.6-luna');
  await expect(vision).toHaveValue('ollama');
  expect(errors).toEqual([]);console.log('CODEX_SETTINGS_UI_PASS');
 }catch(e){console.error(logs);throw e;}
 finally{if(browser)await browser.close();server.kill();}
})().catch(e=>{console.error(e);process.exit(1)});
