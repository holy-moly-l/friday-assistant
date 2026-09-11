import asyncio
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root/'backend'))
import desktop_native as n
import desktop_uia as uia
from desktop_agent import DesktopAgent,Plan,Step

async def main():
    with tempfile.TemporaryDirectory(prefix='friday-desktop-test-') as folder:
        path=Path(folder)/'window.json'
        p=subprocess.Popen([sys.executable,str(root/'tests/desktop_fixture.py'),str(path)],creationflags=subprocess.CREATE_NO_WINDOW)
        cancel=threading.Event()
        try:
            for _ in range(100):
                if path.exists():break
                await asyncio.sleep(.1)
            win=n.info(json.loads(path.read_text())['hwnd']);assert win
            screens=n.monitors();print('MONITORS',len(screens),flush=True)
            snapshot=await asyncio.to_thread(uia.call,win,'inspect',cancel)
            print('UIA',json.dumps(snapshot,ensure_ascii=False),flush=True)
            assert any(e['name']=='Продолжить' for e in snapshot['elements'])
            for mode in ('maximize','minimize','restore'):
                print('WINDOW',mode,n.same(win),flush=True)
                await asyncio.to_thread(n.window_action,win,mode,1,cancel)
            await asyncio.to_thread(n.window_action,win,'move',len(screens),cancel)
            agent=DesktopAgent(folder);agent.context['test']=win
            agent.foreground.last=win
            async def run(text,approve=True):
                events=[]
                async for event in agent.run(text,'test',[{'role':'user','content':text}]):
                    events.append(event)
                    if event['type']=='approval':agent.approve(event['nonce'],approve)
                print('COMMAND',text,json.dumps(events,ensure_ascii=False),flush=True)
                return events
            # Direct calls target the fixture even if the test runner owns foreground.
            agent.foreground.target=lambda name,context:n.same(win)
            result=await run('Нажми тут продолжить');assert any(e['type']=='agent_step' and e['status']=='done' for e in result)
            result=await run('Нажми отправить',False);assert any(e['type']=='approval' for e in result)
            assert not any(e['type']=='agent_step' and e['status']=='done' for e in result)
            snapshot=await asyncio.to_thread(uia.call,win,'inspect',cancel)
            field=next(e for e in snapshot['elements'] if e['type']=='EditControl')
            async def typing(*args):return Plan(steps=[Step(tool='type_text',target='context',name=field['id'],text='Проверка локального ввода')])
            agent.plan=typing
            result=await run('Заполни поле');assert any(e['type']=='agent_step' and e['status']=='done' for e in result)
            result=await run('Нажми Tab');assert any(e['type']=='agent_step' and e['status']=='done' for e in result)
            await asyncio.to_thread(n.window_action,win,'close',1,cancel)
            assert n.info(win['hwnd']) is None
            if not any(n.matches(x,'calculator') for x in n.windows()):
                actual=DesktopAgent(folder)
                try:
                    events=[e async for e in actual.run('Открой калькулятор, перенеси его на второй монитор и разверни','calc',[])]
                    print('CALCULATOR_CHAIN',json.dumps(events,ensure_ascii=False),flush=True)
                    assert sum(e.get('status')=='done' for e in events)==3
                    remembered=actual.context['calc']
                    events=[e async for e in actual.run('Сверни его','calc',[])]
                    assert any(e.get('status')=='done' for e in events)
                    assert n.same(remembered)['minimized']
                    print('REAL_APP_CHAIN_AND_CONTEXT_OK',flush=True)
                finally:
                    window=actual.context.get('calc')
                    if window:await asyncio.to_thread(n.window_action,window,'close',1,cancel)
            import comtypes
            comtypes.CoInitialize()
            endpoint=n.get_volume();old=round(endpoint.GetMasterVolumeLevelScalar()*100)
            try:
                assert n.volume('set',30,cancel)=='Громкость 30%.'
                assert n.volume('delta',-5,cancel)=='Громкость 25%.'
                print('REAL_VOLUME_OK',flush=True)
            finally:n.volume('set',old,cancel);comtypes.CoUninitialize()
            print('NATIVE_INTEGRATION_OK',flush=True)
        finally:
            if p.poll() is None:p.terminate()
            p.wait(timeout=5)

asyncio.run(main())
