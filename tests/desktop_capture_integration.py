"""Real app capture matrix. Images stay in memory and no application content is logged."""
import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'backend'))
import desktop_native as n
import desktop_uia as uia
from desktop_agent import DesktopAgent
from pc import CommandError


async def main():
    cancel=threading.Event();previous=n.info(n.u.GetForegroundWindow())
    with tempfile.TemporaryDirectory(prefix='friday-capture-matrix-') as folder:
        path=Path(folder)/'fixture.json'
        process=subprocess.Popen([sys.executable,str(ROOT/'tests/desktop_fixture.py'),str(path)],creationflags=subprocess.CREATE_NO_WINDOW,
            env={**os.environ,'FRIDAY_TEST_PARENT_PID':str(os.getpid())})
        try:
            for _ in range(100):
                if path.exists():break
                await asyncio.sleep(.1)
            fixture=n.info(json.loads(path.read_text())['hwnd'])
            initial={app:bool([w for w in n.windows() if n.matches(w,app)]) for app in ('telegram','discord','chrome','calculator')}
            print('INITIAL_APP_WINDOWS',initial,flush=True)
            for app in ('telegram','discord','chrome','calculator','win32'):
                window=fixture if app=='win32' else await asyncio.to_thread(n.launch,app,cancel)
                assert window
                if app=='telegram':
                    again=await asyncio.to_thread(n.launch,app,cancel)
                    assert again['launch_status']=='already_running'
                    print('TELEGRAM_ALREADY_OPEN_PASS',flush=True)
                    # Closing Telegram's main window normally moves it to the tray; do not terminate its process.
                    n.u.PostMessageW(window['hwnd'],0x10,0,0)
                    assert n.wait_for(lambda:not any(n.matches(w,'telegram') for w in n.windows()),cancel,5)
                    window=await asyncio.to_thread(n.launch,'telegram',cancel)
                    assert window['launch_status']=='started'
                    print('TELEGRAM_CLOSED_WINDOW_REOPEN_PASS',flush=True)
                saved=n.placement(window)
                was_topmost=bool(n.u.GetWindowLongPtrW(window['hwnd'],-20)&8)
                try:
                    await asyncio.to_thread(n.try_focus,window,cancel)
                    shot=await asyncio.to_thread(n.capture_window,window,cancel)
                    print('CAPTURE',app,shot['method'],shot['size'],flush=True)
                    assert shot['image'] and shot['scope']=='window'
                    await asyncio.to_thread(n.window_action,window,'minimize',1,cancel)
                    with patch.object(n,'focus',side_effect=AssertionError('Capture must not focus')):
                        shot=await asyncio.to_thread(n.capture_window,window,cancel)
                    assert n.same(window)['minimized']
                    print('MINIMIZED_RESTORED',app,flush=True)
                    await asyncio.to_thread(n.window_action,window,'restore',1,cancel)
                    await asyncio.to_thread(n.window_action,window,'move',n.monitors()[0]['index'],cancel)
                    await asyncio.to_thread(n.try_focus,window,cancel)
                    # Visibility, not foreground, is the crop precondition. Temporarily expose the tested app.
                    n.u.SetWindowPos(window['hwnd'],-1,0,0,0,0,0x13)
                    await asyncio.sleep(.2)
                    with patch.object(n,'_print_window',side_effect=CommandError('Injected PrintWindow failure')):
                        shot=await asyncio.to_thread(n.capture_window,window,cancel)
                    assert shot['method']=='MonitorCropFallback' and shot['image']
                    print('FALLBACK',app,'PASS',flush=True)
                finally:
                    if not was_topmost:n.u.SetWindowPos(window['hwnd'],-2,0,0,0,0,0x13)
                    n.restore_placement(window,saved)
                if app=='calculator' and not initial[app]:n.window_action(window,'close',1,cancel)
            screens=n.monitors()
            print('DISPLAYS',[(s['index'],s['device'],s['bounds']) for s in screens],flush=True)
            assert all(str(s['index'])==s['device'].split('DISPLAY')[-1] for s in screens)
            agent=DesktopAgent(folder);agent.foreground.target=lambda *a:n.same(fixture)
            for phrase in ['Какие окна сейчас открыты?','Какие программы у меня запущены?','Что сейчас открыто?',
                           'Какое окно сейчас активно?','Сколько мониторов подключено?','На каком мониторе сейчас это окно?']:
                agent.plan=lambda *a:(_ for _ in ()).throw(AssertionError('No model'))
                events=[e async for e in agent.run(phrase,'test',[])]
                assert any(e.get('status')=='done' for e in events)
            print('LOCAL_INFORMATION_PASS',flush=True)
            for text,needs_approval in [('Нажми Назад',False),('Нажми Отправить',True)]:
                events=[]
                async for event in agent.run(text,'test',[]):
                    events.append(event)
                    if event['type']=='approval':agent.approve(event['nonce'],False)
                assert any(e['type']=='approval' for e in events)==needs_approval
                assert any(e.get('status')=='done' for e in events)!=needs_approval
            print('SAFE_UIA_NO_APPROVAL_DANGEROUS_UIA_APPROVAL_PASS',flush=True)
            saved=n.placement(fixture)
            try:
                for screen in screens:
                    await asyncio.to_thread(n.window_action,fixture,'move',screen['index'],cancel)
                    assert n.window_monitor(fixture)['index']==screen['index']
                print('MONITOR_MOVE_PASS',len(screens),'physical displays',flush=True)
            finally:n.restore_placement(fixture,saved)
            print('REAL_CAPTURE_MATRIX_PASS',flush=True)
        finally:
            if process.poll() is None:process.terminate()
            process.wait(timeout=5)
            if previous and n.info(previous['hwnd']):n.try_focus(previous,threading.Event())


if __name__=='__main__':asyncio.run(main())
