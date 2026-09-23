"""Real movement, maximize and monitor transfer of our own disposable Win32 window."""
import asyncio,json,os,sys,tempfile,subprocess,time
from pathlib import Path
root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root/'backend'))
import desktop_native as native
from gesture_control import GestureControl
from pc import CommandError

async def main():
    with tempfile.TemporaryDirectory(prefix='friday-hands-win-') as folder:
        info=Path(folder)/'window.json'
        proc=subprocess.Popen([sys.executable,str(root/'tests/desktop_fixture.py'),str(info)],creationflags=subprocess.CREATE_NO_WINDOW,env={**os.environ,'FRIDAY_TEST_PARENT_PID':str(os.getpid())})
        try:
            for _ in range(100):
                if info.exists():break
                await asyncio.sleep(.05)
            window=native.info(json.loads(info.read_text())['hwnd']);engine=GestureControl();hwnd=window['hwnd']
            token=(await engine.arm('windows',hwnd))['token']
            await engine.action(token,1,'drag_start',.5,.5)
            before=native.same(window)['rect']
            await engine.action(token,2,'drag_move',.6,.55)
            after=native.same(window)['rect'];assert after!=before
            await engine.action(token,3,'release');assert not engine.status()['dragging']
            await engine.action(token,4,'maximize');assert native.same(window)['maximized']
            engine.session['cooldown']=0
            await engine.action(token,5,'maximize');assert not native.same(window)['maximized']
            screens=sorted(native.monitors(),key=lambda s:(s['bounds'][0],s['bounds'][1]))
            if len(screens)>1:
                current=native.window_monitor(window)
                i=next(i for i,s in enumerate(screens) if s['device_id']==current['device_id'])
                step=1 if i<len(screens)-1 else -1;engine.session['cooldown']=0
                await engine.action(token,6,'monitor_right' if step==1 else 'monitor_left')
                assert native.window_monitor(window)['device_id']==screens[i+step]['device_id']
                print('Real monitor transfer PASS:',current['index'],'->',screens[i+step]['index'])
            engine.stop()
            try:await engine.action(token,7,'maximize');raise AssertionError('Stopped lease accepted')
            except CommandError:pass
            token=(await engine.arm('windows',hwnd))['token'];engine.session['seen']-=2
            assert not engine.status()['armed']
            print('WINDOW GESTURES PASS: actual SetWindowPos, release, maximize/restore, stop, expired lease')
        finally:proc.terminate();proc.wait(timeout=5)

if __name__=='__main__':asyncio.run(main())
