"""Sequential Windows regressions with isolated databases/profiles and bounded test processes.

Run after npm run package with Friday closed. Optional arguments select test filenames.
Reports and fixture recordings remain in ignored data/; no user history is modified.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import httpx
import psutil

ROOT=Path(__file__).resolve().parents[1]
PYTHON=ROOT/'.venv/Scripts/python.exe'
TESTS=['desktop_integration.py','desktop_apps_integration.py','desktop_model_check.py','desktop_model_cancel.py',
       'catalog-ui.cjs','refinement-ui.cjs','wake-ui.cjs','recognition-ui.cjs','voice-regression.cjs',
       'voice-native.cjs','wake-minimized.cjs','desktop-native.cjs','voice-diagnose.cjs',
       'integration.py','ui.cjs','microphone.cjs','upgrade-ui.cjs','electron.cjs','startup.cjs','voice-upgrade.cjs',
       'pc_smoke.py','remaining-voices.py','wake_audio.py','telegram-ui.cjs','telegram_windows_integration.py','codex-ui.cjs','message_composer_integration.py']
SHARED={'integration.py','ui.cjs','microphone.cjs','upgrade-ui.cjs','pc_smoke.py','remaining-voices.py'}


def stop_tree(process):
    if not process:return
    try:children=psutil.Process(process.pid).children(recursive=True)
    except psutil.NoSuchProcess:children=[]
    for child in reversed(children):
        try:child.terminate()
        except psutil.NoSuchProcess:pass
    if process.poll() is None:process.terminate()
    try:process.wait(timeout=10)
    except subprocess.TimeoutExpired:process.kill();process.wait()


def main():
    selected=sys.argv[1:] or TESTS
    assert all(name in TESTS for name in selected),'Unknown test filename'
    os.chdir(ROOT)
    with httpx.Client(trust_env=False,timeout=1) as client:
        for port in (17835,17839,17840):
            try:client.get(f'http://127.0.0.1:{port}/api/health')
            except httpx.HTTPError:continue
            raise RuntimeError(f'Close Friday/test server on port {port} before running')
    runtime=ROOT/'data/runtime.json';backup=runtime.read_bytes() if runtime.exists() else None
    results=[]
    try:
        for name in selected:
            started=time.monotonic();server=process=None
            logpath=ROOT/'data'/('regression-'+Path(name).stem+'.log')
            print('RUN',name,flush=True)
            with tempfile.TemporaryDirectory(prefix='friday-regression-') as folder,logpath.open('w',encoding='utf-8') as log:
                env={**os.environ,'PYTHONUTF8':'1','FRIDAY_DATA_DIR':folder,
                     'FRIDAY_TEST_PROFILE':str(Path(folder)/'profile'),'FRIDAY_DESKTOP_PID':str(os.getpid())}
                try:
                    if name in SHARED:
                        server=subprocess.Popen([str(PYTHON),'-u','backend/app.py'],env=env,stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW)
                        with httpx.Client(trust_env=False,timeout=2) as client:
                            for _ in range(240):
                                if server.poll() is not None:raise RuntimeError('Test server exited')
                                try:
                                    health=client.get('http://127.0.0.1:17835/api/health').json()
                                    if all(v=='ready' for v in health['services'].values()):break
                                except httpx.HTTPError:pass
                                time.sleep(.5)
                            else:raise RuntimeError('Models did not become ready')
                        runtime.write_bytes((Path(folder)/'runtime.json').read_bytes())
                    command=[str(PYTHON),'-u'] if name.endswith('.py') else ['node']
                    process=subprocess.Popen([*command,str(ROOT/'tests'/name)],env=env,stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW)
                    code=process.wait(timeout=360)
                    status='PASS' if code==0 else 'FAIL'
                except Exception as exc:
                    status='FAIL';log.write(f'Runner: {type(exc).__name__}\n')
                finally:
                    stop_tree(process);stop_tree(server)
                    time.sleep(1.5)
                result={'test':name,'status':status,'seconds':round(time.monotonic()-started,1)}
                results.append(result);print(json.dumps(result),flush=True)
            (ROOT/'data/regressions-latest.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
    finally:
        if backup is not None:runtime.write_bytes(backup)
        elif runtime.exists():runtime.unlink()
    return int(any(r['status']!='PASS' for r in results))


if __name__=='__main__':sys.exit(main())
