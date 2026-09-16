"""Real Codex ChatGPT image input, Windows displays, fallback and cancellation.

Only our disposable window is clicked. No user messages are sent.
"""
import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
from unittest.mock import AsyncMock
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'backend'))
import desktop_native as n
import desktop_uia as uia
from desktop_agent import DesktopAgent,Plan,PROMPT,stop_request
from desktop_display import display_number
from ai_providers import ProviderError
from ai_router import decode

async def main():
    with tempfile.TemporaryDirectory(prefix='friday-codex-integration-') as folder:
        path=Path(folder)/'fixture.json'
        process=subprocess.Popen([sys.executable,str(ROOT/'tests/desktop_fixture.py'),str(path)],
            creationflags=subprocess.CREATE_NO_WINDOW,env={**os.environ,'FRIDAY_TEST_PARENT_PID':str(os.getpid())})
        try:
            for _ in range(100):
                if path.exists():break
                await asyncio.sleep(.1)
            win=n.info(json.loads(path.read_text())['hwnd']);assert win
            agent=DesktopAgent(folder);agent.foreground.target=lambda *args:n.same(win)
            agent.ai.vision_provider='codex'
            health=await agent.ai.codex.health_check(force=True)
            assert health['authenticated'];print('CHATGPT_AUTH',health['version'],flush=True)
            for phrase in ('Найди кнопку Продолжить','Нажми Назад'):
                model=agent.ai.codex.analyze_image;agent.ai.codex.analyze_image=AsyncMock(side_effect=AssertionError('UIA must win'))
                events=[e async for e in agent.run(phrase,'test',[])]
                assert any(e.get('status')=='done' for e in events) and not any(e['type']=='approval' for e in events)
                agent.ai.codex.analyze_image=model
            print('UIA_FIND_AND_SAFE_CLICK_WITHOUT_AI_PASS',flush=True)
            cancel=threading.Event();shot=n.capture_window(win,cancel)
            answer=await agent.describe('Прочитай текст ошибки или результата в этом окне.',shot['image'])
            assert 'Шаг' in answer or 'шаг' in answer or 'выполнен' in answer
            assert agent.ai.last_result.provider=='codex';print('WINDOW_IMAGE_LUNA',answer,flush=True)
            screens=n.monitors();print('DISPLAYS',[(s['index'],s['bounds']) for s in screens],flush=True)
            for screen in screens:
                n.window_action(win,'move',screen['index'],cancel)
                assert n.window_monitor(win)['index']==screen['index']
                shot=n.capture_screen(cancel,screen['index'])
                assert decode(shot['image']).size==tuple(shot['original_size'])
                print('REAL_MONITOR_CAPTURE',screen['index'],shot['size'],flush=True)
            assert display_number('второй экран')==display_number('второй монитор')==2
            assert any(s['bounds'][2]-s['bounds'][0]>=2560 for s in screens),'2K display required for this live test'
            n.window_action(win,'maximize',1,cancel)
            large=n.capture_window(win,cancel)
            point=await agent.locate('Продолжить',large['image'])
            assert point.found and point.box[0]<point.x<point.box[2]
            print('SMALL_BUTTON_PROGRESSIVE_LOCATION_PASS',point.box,flush=True)
            n.window_action(win,'minimize',1,cancel)
            minimized=n.capture_window(win,cancel);assert n.same(win)['minimized']
            reply=await agent.describe('Что написано в этом окне?',minimized['image'])
            assert reply and n.same(win)['minimized'];print('MINIMIZED_VISION_STATE_PRESERVED',flush=True)
            # A real planner returns validated tools, without executing them.
            before=n.same(win)
            result=await agent.ai.codex.plan('Сначала открой калькулятор, затем перенеси его на второй монитор и разверни.',
                {'monitors':[{'index':s['index']} for s in screens]},schema=Plan.model_json_schema(),system=PROMPT)
            plan=Plan.model_validate_json(result.content)
            assert [s.tool for s in plan.steps]==['open_app','window','window'] and plan.steps[1].monitor==2
            assert n.same(win)['minimized']==before['minimized'];print('LUNA_STRUCTURED_PLAN_PASS',flush=True)
            real=agent.ai.codex.analyze_image
            for status in ('unavailable','usage_limit'):
                agent.ai.codex.analyze_image=AsyncMock(side_effect=ProviderError(status,'simulated provider failure'))
                answer=await agent.describe('Что написано в этом окне?',minimized['image'])
                assert answer and agent.ai.last_result.provider=='ollama';print('REAL_OLLAMA_FALLBACK',status,flush=True)
            agent.ai.codex.analyze_image=real
            agent.cancel.clear();assert stop_request('Пятница, стоп')
            task=asyncio.create_task(agent.cancellable(agent.describe('Опиши окно подробно',minimized['image'])))
            await asyncio.sleep(1);started=time.perf_counter();agent.stop()
            try:await asyncio.wait_for(task,3)
            except (n.Stopped,asyncio.CancelledError):pass
            else:raise AssertionError('Request was not cancelled')
            print('REAL_CODEX_STOP_MS',round((time.perf_counter()-started)*1000),flush=True)
            print('CODEX_WINDOWS_INTEGRATION_PASS',flush=True)
        finally:
            if process.poll() is None:process.terminate()
            process.wait(timeout=5)

if __name__=='__main__':asyncio.run(main())
