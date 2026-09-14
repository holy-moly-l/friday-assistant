"""Opt-in real installed app launches. Calculator placement is restored afterwards."""
import asyncio
import ctypes as c
from ctypes import wintypes as w
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'backend'))
import desktop_native as n
from desktop_agent import DesktopAgent
from pc import CommandError, installed_shell_apps


class Placement(c.Structure):
    _fields_=[('length',w.UINT),('flags',w.UINT),('show',w.UINT),('min',w.POINT),('max',w.POINT),('rect',w.RECT)]


async def main():
    with tempfile.TemporaryDirectory(prefix='friday-apps-') as folder:
        agent=DesktopAgent(folder)
        initial={name:[x for x in n.windows() if n.matches(x,name)] for name in ('telegram','discord','calculator')}
        print('INITIAL_WINDOWS', {k:len(v) for k,v in initial.items()},flush=True)
        n.u.GetWindowPlacement.argtypes=[w.HWND,c.POINTER(Placement)]
        n.u.SetWindowPlacement.argtypes=[w.HWND,c.POINTER(Placement)]
        saved=[]
        for win in initial['calculator']:
            placement=Placement();placement.length=c.sizeof(placement)
            if n.u.GetWindowPlacement(win['hwnd'],c.byref(placement)):saved.append((win,placement))
        async def run(text):
            events=[e async for e in agent.run(text,'test',[])]
            print('COMMAND',text,'RESULT',events[-1].get('text'),flush=True)
            assert any(e.get('status')=='done' for e in events),events[-1]
            return events
        try:
            await run('Открой Telegram')
            assert agent.context['test']['launch_status']==('already_running' if initial['telegram'] else 'started')
            repeated=await run('Открой Telegram')
            assert 'уже открыт' in repeated[-1]['text'] or 'передний план' in repeated[-1]['text']
            # Real existing Telegram HWND, deterministic denial injection; never close user conversations.
            with patch.object(n,'focus',side_effect=CommandError('Windows denied foreground')):
                assert 'Windows не дала' in (await run('Открой Telegram'))[-1]['text']
            await run('Открой Discord')
            await run('Открой калькулятор')
            calc=agent.context['test']
            # Pin this verified calculator, avoiding unrelated foreground windows during the test.
            agent.foreground.target=lambda *args:n.same(calc)
            for phrase in ['Сверни калькулятор','Разверни калькулятор','Перенеси калькулятор на второй монитор']:
                await run(phrase)
            chain=await run('Открой калькулятор, перенеси его на второй монитор и разверни')
            assert sum(e.get('status')=='done' for e in chain)==3
            print('SHELL_CATALOG_READ',len(installed_shell_apps()),flush=True)
            print('REAL_APPS_PASS',flush=True)
        finally:
            for win,placement in saved:
                if n.info(win['hwnd']):n.u.SetWindowPlacement(win['hwnd'],c.byref(placement))
            if not initial['calculator']:
                for win in n.windows():
                    if n.matches(win,'calculator'):n.window_action(win,'close',1,agent.cancel.__class__())


if __name__=='__main__':asyncio.run(main())
