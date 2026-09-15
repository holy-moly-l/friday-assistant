"""Real installed Telegram Desktop; no messages sent by default.

Run: .venv/Scripts/python tests/telegram_windows_integration.py
Optional --send-self explicitly authorizes ONE message to your own Saved Messages.
No contact names, drafts, chat history or UI screenshots are written to this report.
"""
import argparse
import asyncio
from collections import Counter
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
sys.path.insert(0, str(Path(__file__).parents[1]/'backend'))
import desktop_native as native
from desktop_agent import DesktopAgent
from telegram_uia import call
from telegram_uia_worker import TelegramUI, cells
import uiautomation as auto

BODY = 'Тест Пятницы: проверка отправки'


async def workflow(agent, decision):
    events = []; approvals = 0
    async for event in agent.run('Напиши себе '+BODY, 'self-integration', []):
        events.append(event)
        if event['type'] == 'approval':
            assert event['kind'] == 'telegram_message' and event['text'] == BODY
            assert 'Избранное' in event['window'] or 'Saved Messages' in event['window']
            assert agent.telegram.pending_messages['self-integration'].status == 'awaiting_confirmation'
            approvals += 1
            if decision == 'stop': agent.stop()
            else: agent.approve(event['nonce'], decision)
    assert approvals == 1, 'Workflow did not reach verified draft confirmation'
    text = ''.join(e['text'] for e in events if e['type'] == 'delta')
    if decision is True: assert text.startswith('Отправила'), text
    else: assert 'не отправляла' in text, text


async def main(send_self=False):
    results = []
    def passed(name):
        results.append(dict(test=name,status='PASS')); print('PASS',name,flush=True)
    cancel = threading.Event()
    window = native.launch('telegram',cancel)
    assert window['process'].casefold() == 'telegram.exe'; passed('Telegram already open / resolver')
    await asyncio.to_thread(call,window,'self',cancel)
    initial = await asyncio.to_thread(call,window,'inspect',cancel)
    assert initial['draft_length'] == 0, 'Saved Messages already has a user draft; not overwriting it'
    literal = 'Тест: {Enter}\nВторая строка'
    try:
        prepared = await asyncio.to_thread(call,window,'prepare',cancel,chat=initial['chat'],text=literal)
        assert prepared['drafted']
        fresh = await asyncio.to_thread(call,window,'inspect',cancel)
        assert fresh['draft_length'] == len(literal) and fresh['history_count'] == initial['history_count']
        passed('Literal braces and newline are text; no Enter key or Send')
    finally: await asyncio.to_thread(call,window,'cleanup',cancel,chat=initial['chat'],text=literal)
    with tempfile.TemporaryDirectory(prefix='friday-telegram-') as directory:
        agent = DesktopAgent(directory)
        await workflow(agent,False); passed('Draft without approval; reject; exact draft cleanup')
        await workflow(agent,'stop'); passed('Friday stop at confirmation; no Send')
        assert call(window,'inspect',cancel)['draft_length'] == 0
        native.window_action(window,'minimize',1,cancel)
        assert native.same(window)['minimized']
        await workflow(agent,False); passed('Telegram minimized -> launch -> verified draft -> cancel')
        # WM_CLOSE respects Telegram's own close-to-tray/quit preference.
        native.u.PostMessageW(window['hwnd'],0x10,0,0)
        await asyncio.sleep(.8)
        await workflow(agent,False); passed('Telegram window closed -> launch -> draft -> cancel')
        window = native.launch('telegram',cancel)
        query = 'FridayIntegrationNoSuchRecipient973124'
        try:
            result = await asyncio.to_thread(call,window,'search',cancel,query=query)
            assert not result['candidates']; passed('Recipient not found in real Telegram')
        finally: await asyncio.to_thread(call,window,'clear_search',cancel,query=query)
        # Global search mode can hide the normal list. This is test navigation;
        # the production workflow uses the matching result directly.
        ui = TelegramUI(window)
        try: ui.chat_list()
        except ValueError:
            native.focus(window,cancel)
            ui.search_field().SetFocus(); auto.SendKeys('{Esc}',waitTime=.2)
        rows = [cells(r,{'Тип','Название','Type','Name'}) for r in ui.chat_list().GetChildren()]
        counts = Counter(d.get('Название',d.get('Name')) for d in rows)
        queries = [d.get('Название',d.get('Name')) for d in rows
            if not d.get('Тип',d.get('Type')) and d.get('Название',d.get('Name'))]
        tested = set()
        for query in queries:
            category = 'ambiguous' if counts[query] > 1 else 'unique'
            if category in tested: continue
            try:
                result = await asyncio.to_thread(call,window,'search',cancel,query=query)
                exact = [c for c in result['candidates'] if c['title'] == query]
                if category == 'unique' and len(exact) == 1:
                    opened = await asyncio.to_thread(call,window,'open',cancel,query=query,candidate=exact[0])
                    assert opened['chat']['title'] == query
                    tested.add(category); passed('Unique real contact: UIA search -> Invoke -> header verified (no draft/send)')
                elif category == 'ambiguous' and len(exact) > 1:
                    assert len({c['id'] for c in exact}) > 1
                    tested.add(category); passed('Two real equal display names have distinct recipient identities')
            finally: await asyncio.to_thread(call,window,'clear_search',cancel,query=query)
            if len(tested) == 2: break
        for missing in {'unique','ambiguous'} - tested:
            results.append(dict(test='Real contacts '+missing,status='SKIP',reason='No suitable fixture in user contact list'))
        await asyncio.to_thread(call,window,'self',cancel)
        if send_self:
            await workflow(agent,True); passed('One confirmed real Saved Messages send; new history message verified')
        else: results.append(dict(test='Real send',status='SKIP',reason='Use --send-self only with explicit user authorization'))
        assert call(window,'inspect',cancel)['draft_length'] == 0
    target = Path(__file__).parents[1]/'data/telegram-integration-latest.json'
    target.write_text(json.dumps(results,indent=2),encoding='utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--send-self',action='store_true')
    asyncio.run(main(parser.parse_args().send_self))
