const { app, BrowserWindow, session, shell, dialog } = require('electron');
const { spawn } = require('node:child_process');
const path = require('node:path');
const fs = require('node:fs');
const crypto = require('node:crypto');

const root = app.isPackaged ? path.resolve(path.dirname(process.execPath), '../..') : path.resolve(__dirname, '..');
const port = 17835;
let backend, window;
let token = crypto.randomBytes(32).toString('hex');
const origin = `http://127.0.0.1:${port}`;
const delay = ms => new Promise(r => setTimeout(r, ms));

if (!app.requestSingleInstanceLock()) app.quit();
else {
  app.on('second-instance', () => { if (window) { if (window.isMinimized()) window.restore(); window.focus(); } });
  app.whenReady().then(async () => {
    try {
      fs.mkdirSync(path.join(root, 'data'), { recursive: true });
      const logfile = fs.openSync(path.join(root, 'data', 'backend.log'), 'a');
      try {
        await fetch('http://127.0.0.1:11434/api/version', { signal: AbortSignal.timeout(1500) });
      } catch {
        const ollama = path.join(process.env.LOCALAPPDATA, 'Programs', 'Ollama', 'ollama.exe');
        const proc = spawn(ollama, ['serve'], { windowsHide: true, detached: true, stdio: 'ignore' });
        proc.on('error', e => fs.appendFileSync(path.join(root, 'data', 'backend.log'), String(e)));
        proc.unref();
        for (let i = 0; i < 30; i++) { try { await fetch('http://127.0.0.1:11434/api/version', {signal: AbortSignal.timeout(1000)}); break; } catch { await delay(500); } }
      }
      let existing = false;
      try {
        const response = await fetch(origin + '/api/health', {signal: AbortSignal.timeout(1000)});
        if ((await response.json()).app === 'friday') {
          const runtime = JSON.parse(fs.readFileSync(path.join(root, 'data', 'runtime.json'), 'utf8'));
          token = runtime.token;
          existing = true;
        } else throw new Error('Порт приложения занят');
      } catch (error) { if (error.message === 'Порт приложения занят') throw error; }
      if (!existing) {
        backend = spawn(path.join(root, '.venv', 'Scripts', 'python.exe'), ['-u', path.join(root, 'backend', 'app.py')], {
          cwd: root, windowsHide: true, stdio: ['ignore', logfile, logfile],
          env: {...process.env, FRIDAY_ROOT: root, FRIDAY_TOKEN: token, FRIDAY_PORT: String(port), FRIDAY_DESKTOP_PID: String(process.pid), PYTHONUTF8: '1', HF_HUB_OFFLINE: '1'}
        });
        backend.on('error', e => dialog.showErrorBox('Пятница', 'Не удалось запустить помощника: ' + e.message));
      }
      session.defaultSession.setPermissionRequestHandler((contents, permission, callback, details) => {
        const trusted = contents.getURL().startsWith(origin + '/');
        callback(trusted && permission === 'media' && (!details.mediaTypes || details.mediaTypes.every(t => t === 'audio')));
      });
      session.defaultSession.setPermissionCheckHandler((contents, permission, requestingOrigin, details) => permission === 'media' && requestingOrigin === origin && details.mediaType !== 'video');
      window = new BrowserWindow({ width: 1440, height: 960, minWidth: 1050, minHeight: 720, icon: path.join(root, 'public', 'friday.ico'), backgroundColor: '#0c121c', title: 'Пятница', autoHideMenuBar: true, show: false, webPreferences: {nodeIntegration: false, contextIsolation: true, sandbox: true, backgroundThrottling: false, autoplayPolicy: 'no-user-gesture-required'} });
      window.setMenu(null);
      window.webContents.setWindowOpenHandler(() => ({action: 'deny'}));
      window.webContents.on('will-navigate', (event, url) => { if (!url.startsWith(origin + '/')) event.preventDefault(); });
      for (let i = 0; i < 100; i++) {
        try {
          const result = await fetch(origin + '/api/health', {signal: AbortSignal.timeout(1000)});
          if (result.ok) break;
        } catch {}
        if (backend && backend.exitCode !== null) throw new Error('Сервис завершился. Подробности: data/backend.log');
        if (i === 99) throw new Error('Сервис не запустился. Подробности: data/backend.log');
        await delay(300);
      }
      await window.loadURL(origin + '/#token=' + token);
      window.show();
    } catch (error) {
      dialog.showErrorBox('Не удалось запустить Пятницу', String(error.message));
      app.quit();
    }
  });
  app.on('window-all-closed', () => app.quit());
  app.on('before-quit', () => { if (backend) backend.kill(); });
}
