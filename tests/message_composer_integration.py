"""Real local Qwen; optional installed Telegram self-chat only.

python tests/message_composer_integration.py
python tests/message_composer_integration.py --telegram --send-self
No input/output message contents are persisted in the diagnostic report.
"""
import argparse
import asyncio
import json
from pathlib import Path
import statistics
import sys
import tempfile
import threading
import time
sys.path[:0]=[str(Path(__file__).parents[1]/'backend'),str(Path(__file__).parent)]
from message_composer import MessageComposer
from telegram_language import message_intent
from test_message_composer import CASES


async def main(telegram=False,send_self=False):
    rows=[];composer=MessageComposer()
    cases=CASES+[
        ('Напиши Насте дословно: пусть приезжает сегодня','пусть приезжает сегодня'),
        ('Напиши Насте, что я приеду завтра в 12 часов. Я буду ждать у дома 15 минут. '
         'Саша уже купил хлеб. Я не забыл ключи. Мы будем примерно в восемь. '
         'Ссылка https://example.org/a?x=12&y=20',None),
    ]
    for i,(command,expected) in enumerate(cases):
        intent=message_intent(command);start=time.perf_counter();length=0;status='PASS'
        try:
            result=await composer.compose_message(intent.text,intent.recipient,{'mode':intent.mode},verbatim=intent.verbatim)
            length=len(result.text)
            assert not result.needs_clarification
            # A polite explicit 'ты' is allowed in a question, but no new facts.
            actual=result.text
            if intent.mode=='question':actual=actual.removeprefix('Ты ').removeprefix('ты ')
            normalized=lambda s:s.casefold().removeprefix('я ').rstrip('.')
            assert expected is None or normalized(actual)==normalized(expected), 'Unexpected formulation'
        except Exception as exc:status='FAIL';error=type(exc).__name__
        row=dict(case=i+1,status=status,latency_ms=round((time.perf_counter()-start)*1000),output_length=length,verbatim=intent.verbatim)
        if status=='FAIL':row['error']=error
        rows.append(row);print(json.dumps(row),flush=True)
    assert all(r['status']=='PASS' for r in rows),'Local formulation failed; Telegram not touched'
    # Cancel an actual in-flight Ollama request; never launch Telegram here.
    event=threading.Event()
    task=asyncio.create_task(composer.compose_message('я приеду завтра в 12 часов','Настя',cancel=event))
    while not composer.provider._tasks and not task.done():await asyncio.sleep(.01)
    assert not task.done(),'Cancellation fixture finished before it could be stopped'
    start=time.perf_counter();event.set()
    try:await task
    except asyncio.CancelledError:pass
    else:raise AssertionError('Model request was not cancelled')
    cancel_ms=round((time.perf_counter()-start)*1000)
    assert cancel_ms<1000
    print(json.dumps(dict(test='real_ollama_cancel',status='PASS',latency_ms=cancel_ms)),flush=True)
    if telegram:
        from desktop_agent import DesktopAgent
        import desktop_native as native
        from telegram_uia import call
        window=native.launch('telegram',threading.Event())
        await asyncio.to_thread(call,window,'self',threading.Event())
        initial=await asyncio.to_thread(call,window,'inspect',threading.Event())
        assert initial['draft_length']==0,'Existing user draft; not overwriting'
        with tempfile.TemporaryDirectory(prefix='friday-composer-') as folder:
            agent=DesktopAgent(folder)
            for decision in ([False,'stop',True] if send_self else [False,'stop']):
                approvals=0;reply=''
                async for e in agent.run('Напиши себе, что пусть приедет сегодня в 12 часов','composer-self',[]):
                    if e['type']=='approval':
                        approvals+=1
                        pending=agent.telegram.pending_messages['composer-self']
                        assert pending.verified_chat.get('self_chat') is True
                        assert e['text']=='Приезжай сегодня в 12 часов.'
                        fresh=await asyncio.to_thread(call,pending.window,'inspect',threading.Event())
                        assert fresh['draft_length']==len(e['text'])
                        if decision=='stop':agent.stop()
                        else:agent.approve(e['nonce'],decision)
                    if e['type']=='delta':reply+=e['text']
                assert approvals==1
                assert ('Отправила' in reply) if decision is True else ('не отправляла' in reply)
                print(json.dumps(dict(test='telegram_'+str(decision),status='PASS')),flush=True)
            final=await asyncio.to_thread(call,window,'inspect',threading.Event())
            assert final['draft_length']==0
            assert final['history_count']==initial['history_count']+(1 if send_self else 0)
    times=[r['latency_ms'] for r in rows if not r['verbatim']]
    report=dict(model='qwen3.5:4b',cases=rows,median_ms=statistics.median(times),cancel_ms=cancel_ms,
        telegram=telegram,self_messages_sent=1 if send_self else 0)
    (Path(__file__).parents[1]/'data/message-composer-check.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(dict(median_ms=report['median_ms'],status='PASS')),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--telegram',action='store_true');p.add_argument('--send-self',action='store_true')
    args=p.parse_args()
    asyncio.run(main(args.telegram or args.send_self,args.send_self))
