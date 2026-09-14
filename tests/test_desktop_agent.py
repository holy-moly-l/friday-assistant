import asyncio
import json
from pathlib import Path
import sys
import threading
import time
sys.path.insert(0,str(Path(__file__).parents[1]/'backend'))
import pytest
from pydantic import ValidationError
import desktop_agent as d
from pc import CommandError

@pytest.mark.parametrize('phrase,tool,mode,target',[
 ('Открой дискорд','open_app','','active'),
 ('Сверни калькулятор','window','minimize','calculator'),
 ('Перекинь вот это окно на второй монитор','window','move','active'),
 ('Перенеси его на второй монитор','window','move','context'),
 ('Пятница, нажми тут продолжить','click','','active'),
 ('Сделай музыку чуть тише','volume','delta','active'),
 ('Сделай громкость 30%','volume','set','active'),
 ('Включи звук','volume','unmute','active'),
])
def test_simple_commands_need_no_model(phrase,tool,mode,target):
    step=d.deterministic(phrase).steps[0]
    assert (step.tool,step.mode,step.target)==(tool,mode,target)

def test_chain_and_literal_text():
    plan=d.deterministic('Открой калькулятор, перенеси его на второй монитор и разверни')
    assert [s.tool for s in plan.steps]==['open_app','window','window']
    assert plan.steps[1].monitor==2 and plan.steps[2].target=='context'
    assert d.deterministic('Пятница, напечатай Привет, и открой дверь!').steps[0].text=='Привет, и открой дверь!'
    assert d.deterministic('Открой калькулятор и удали файл') is None
    assert d.deterministic('Не открывай калькулятор') is None

@pytest.mark.parametrize('data',[
 {'tool':'shell','text':'cmd.exe'}, {'tool':'window','mode':'delete'},
 {'tool':'volume','mode':'set','value':101}, {'tool':'volume','mode':'set','value':-2},
 {'tool':'click','name':'Отправить','approved':True}, {'tool':'press_key','mode':'win+r'},
 {'tool':'click_point','x':1.01,'y':.5},
])
def test_allowlist_validation(data):
    with pytest.raises(ValidationError):d.Step(**data)

@pytest.mark.parametrize('label',['Отправить','Удалить','Оплатить','Publish','Купить','Не сохранять'])
def test_irreversible_buttons_always_need_approval(label):
    assert d.approval_reason(d.Step(tool='click',name=label),{'title':'Тест','process':'app.exe'},{'name':label},[])

def test_terminal_and_password_input_blocked():
    for title in ['PowerShell','Пароль','WindowsTerminal']:
        with pytest.raises(CommandError):d.approval_reason(d.Step(tool='type_text',text='x'),{'title':title},None,[])

def test_confirmation_nonce_one_use_and_expiry(tmp_path):
    agent=d.DesktopAgent(tmp_path)
    agent.pending={'nonce':'test-nonce','decision':None,'expires':time.monotonic()+10}
    with pytest.raises(CommandError):agent.approve('wrong',True)
    agent.approve('test-nonce',False)
    with pytest.raises(CommandError):agent.approve('test-nonce',True)
    agent.pending={'nonce':'expired','decision':None,'expires':time.monotonic()-1}
    with pytest.raises(CommandError):agent.approve('expired',True)

def test_failed_step_prevents_later_actions(tmp_path,monkeypatch):
    def fail(*args):raise CommandError('Программа не открылась')
    monkeypatch.setattr(d.native,'launch',fail)
    monkeypatch.setattr(d.native,'window_action',lambda *args:pytest.fail('Must not run after failure'))
    agent=d.DesktopAgent(tmp_path)
    async def run():return [e async for e in agent.run('Открой калькулятор, перенеси его на второй монитор и разверни','test',[])]
    events=asyncio.run(run())
    assert any(e['type']=='agent_stopped' for e in events)
    assert not any(e.get('status')=='done' for e in events)

def test_context_and_stop_between_steps(tmp_path,monkeypatch):
    win={'hwnd':42,'pid':10,'created':1,'title':'Калькулятор'};calls=[]
    monkeypatch.setattr(d.native,'launch',lambda *args:win)
    monkeypatch.setattr(d.native,'same',lambda window:window)
    monkeypatch.setattr(d.native,'window_action',lambda *args:calls.append(args) or win)
    agent=d.DesktopAgent(tmp_path)
    async def run():
        async for event in agent.run('Открой калькулятор, перенеси его на второй монитор и разверни','test',[]):
            if event.get('status')=='done':agent.stop()
    asyncio.run(run());assert not calls;assert agent.context['test']==win
    assert agent.foreground.target('context',win)==win

def test_app_identity_not_browser_tab_title():
    assert not d.native.matches({'title':'Telegram — Google Chrome','process':'chrome.exe'},'telegram')
    assert d.native.matches({'title':'Telegram','process':'Telegram.exe'},'telegram')

def test_launch_selects_an_existing_app_window_without_duplicate_launch(monkeypatch):
    old=[{'hwnd':1,'title':'Калькулятор','process':'CalculatorApp.exe'}, {'hwnd':2,'title':'Калькулятор','process':'CalculatorApp.exe'}]
    monkeypatch.setattr(d.native,'windows',lambda:old)
    monkeypatch.setattr(d.native,'open_app',lambda *a,**kw:pytest.fail('App already has windows'))
    monkeypatch.setattr(d.native,'same',lambda win:win)
    monkeypatch.setattr(d.native,'try_focus',lambda *a:False)
    monkeypatch.setattr(d.native,'wait_for',lambda predicate,*args:predicate())
    monkeypatch.setattr(d.native.u,'GetForegroundWindow',lambda:999)
    result=d.native.launch('calculator',threading.Event())
    assert result['hwnd']==1 and result['launch_status']=='already_running' and result['focused'] is False

def test_launch_remembers_new_window_without_matching_browser_tab(monkeypatch):
    old=[{'hwnd':1,'title':'Калькулятор — Chrome','process':'chrome.exe'}]
    new={'hwnd':3,'title':'Калькулятор','process':'CalculatorApp.exe'};started=[]
    monkeypatch.setattr(d.native,'windows',lambda:old+([new] if started else []))
    monkeypatch.setattr(d.native,'open_app',lambda name,**kw:started.append(True))
    monkeypatch.setattr(d.native,'same',lambda win:win)
    monkeypatch.setattr(d.native,'try_focus',lambda *a:True)
    monkeypatch.setattr(d.native,'wait_for',lambda predicate,*args:predicate())
    result=d.native.launch('calculator',threading.Event())
    assert result['hwnd']==new['hwnd'] and result['launch_status']=='started'

def test_model_request_cancellation_is_prompt(tmp_path):
    agent=d.DesktopAgent(tmp_path)
    async def run():
        async def slow():await asyncio.sleep(30)
        task=asyncio.create_task(agent.cancellable(slow()))
        await asyncio.sleep(.05);agent.stop()
        with pytest.raises(d.native.Stopped):await asyncio.wait_for(task,.5)
    asyncio.run(run())

def test_stop_websocket_does_not_wait_for_whisper(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from wake_word import WakeService
    class Recognizer:
        def Reset(self):pass
        def AcceptWaveform(self,pcm):return False
        def PartialResult(self):return json.dumps({'partial':'пятница стоп'})
    wake=WakeService(Path('models'));monkeypatch.setattr(wake,'recognizer',lambda:Recognizer())
    stopped=[];app=FastAPI()
    wake.mount(app,'secret',17835,lambda pcm:pytest.fail('Whisper must not run for stop'),lambda:True,lambda:stopped.append(True))
    with TestClient(app).websocket_connect('/api/wake',headers={'origin':'http://127.0.0.1:17835'}) as ws:
        ws.send_json({'token':'secret','sample_rate':16000,'mode':'stop'});assert ws.receive_json()['type']=='ready'
        ws.send_bytes(bytes(3200));assert ws.receive_json()['type']=='stopped'
    assert stopped==[True]
