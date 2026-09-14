"""Real captures + local Qwen + confirmed coordinate click in our disposable window only."""
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
    with tempfile.TemporaryDirectory(prefix='friday-vision-') as folder:
        processes=[];cancel=threading.Event()
        async def fixture(name,status):
            file=Path(folder)/(name+'.json')
            p=subprocess.Popen([sys.executable,str(ROOT/'tests/desktop_fixture.py'),str(file)],
                creationflags=subprocess.CREATE_NO_WINDOW,env={**os.environ,'FRIDAY_TEST_PARENT_PID':str(os.getpid()),
                'FRIDAY_FIXTURE_TITLE':name,'FRIDAY_FIXTURE_STATUS':status})
            processes.append(p)
            for _ in range(100):
                if file.exists():return n.info(json.loads(file.read_text())['hwnd'])
                await asyncio.sleep(.1)
            raise AssertionError('Fixture failed to start')
        try:
            win=await fixture('Friday Vision Fixture','Ошибка 810: тестовый документ не найден')
            cover=await fixture('Friday Cover Fixture','Ошибка 999: это другое окно')
            await asyncio.sleep(.4)
            with patch.object(n,'focus',side_effect=AssertionError('Capture must not focus')):
                shot=await asyncio.to_thread(n.capture_window,win,cancel)
                assert shot['scope']=='window' and shot['original_size']==[650,420]
                all_shot=await asyncio.to_thread(n.capture_all_screens,cancel)
                screens=n.monitors()
                assert all_shot['original_size'][0]==max(s['bounds'][2] for s in screens)-min(s['bounds'][0] for s in screens)
                second=await asyncio.to_thread(n.capture_screen,cancel,len(n.monitors()))
                assert second['target']['monitor']==len(n.monitors())
            print('CAPTURE_OK: window behind another window, focus forbidden, monitor and all_screens',flush=True)
            # The standalone script must describe the first window, not the covering one.
            proc=await asyncio.create_subprocess_exec(sys.executable,str(ROOT/'scripts/test_vision.py'),
                '--scope','window','--window',str(win['hwnd']),'--question','Прочитай номер и текст ошибки на изображении.',
                stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE,creationflags=subprocess.CREATE_NO_WINDOW)
            out,err=await proc.communicate()
            print(err.decode('utf-8'),flush=True);answer=out.decode('utf-8');print('STANDALONE',answer,flush=True)
            assert proc.returncode==0 and '810' in answer and '999' not in answer
            await asyncio.to_thread(n.window_action,cover,'close',1,cancel)
            agent=DesktopAgent(folder);agent.foreground.target=lambda *args:n.same(win)
            async def run(text,approve=False):
                events=[]
                async for event in agent.run(text,'test',[]):
                    events.append(event)
                    if event['type']=='approval':
                        assert approve and event['window']=='Friday Vision Fixture'
                        print('CONFIRM_OWN_FIXTURE',event.get('x'),event.get('y'),flush=True)
                        agent.approve(event['nonce'],True)
                print('COMMAND',text,'RESULT',events[-1].get('text'),flush=True)
                return events
            result=await run('Что написано в этом окне?')
            assert '810' in result[-1]['text']
            # Exercise actual model locator → fixed tool, even with a failing UIA provider.
            async def unavailable(*args):return {'elements':[],'unavailable':'Simulated unsupported provider'}
            agent.observe=unavailable
            result=await run('Нажми кнопку Продолжить',True)
            assert any(e.get('status')=='done' for e in result),result[-1]
            rows=await asyncio.to_thread(uia.call,win,'inspect',cancel)
            assert any('Шаг выполнен: 1' in r['name'] for r in rows['elements'])
            # A full-monitor request uses an actual monitor capture. Cover it with our fixture first.
            await asyncio.to_thread(n.window_action,win,'maximize',1,cancel)
            await asyncio.to_thread(n.focus,win,cancel)
            result=await run('Что у меня на экране?')
            assert not any(e['type']=='agent_stopped' for e in result)
            assert any(word in result[-1]['text'].lower() for word in ('тестов','пятниц','продолжить','fixture'))
            agent.vision=False
            assert 'отключены' in (await run('Что ты видишь?'))[-1]['text']
            print('VISION_NATIVE_PASS: separate script, real Qwen 4B image, actual coordinate click + verification, disabled vision',flush=True)
        finally:
            for p in processes:
                if p.poll() is None:p.terminate()
                p.wait(timeout=5)


if __name__=='__main__':asyncio.run(main())
