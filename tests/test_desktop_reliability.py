import asyncio
import base64
import io
import json
from pathlib import Path
import sys
import threading
from unittest.mock import Mock
sys.path.insert(0,str(Path(__file__).parents[1]/'backend'))
import httpx
from PIL import Image
import pytest
import desktop_agent as d
import desktop_native as n
import desktop_vision as vision
import pc

WINDOW=dict(hwnd=42,pid=12,created=1,title='Test',process='Telegram.exe',rect=[0,0,640,480],minimized=False)


@pytest.mark.parametrize('phrase,scope',[
 ('Что у меня на экране?','monitor'),('Что ты видишь?','monitor'),
 ('Посмотри на экран','monitor'),('Посмотри сюда','monitor'),
 ('Прочитай, что написано на экране','monitor'),('Что за ошибка на экране?','monitor'),
 ('Прочитай текст на экране','monitor'),
 ('Посмотри скрин','monitor'),('Посмотри скриншот','monitor'),('Что сейчас открыто передо мной?','monitor'),
 ('Что открыто на экране?','monitor'),('Что видно на компьютере?','monitor'),
 ('Что здесь?','window'),('Что тут?','window'),('Прочитай экран','monitor'),
 ('Что в этом окне?','window'),('Что написано в Telegram?','window'),
 ('Посмотри на рабочий стол','monitor'),
 ('Что на всех мониторах?','all_screens'),('Что видно на втором мониторе?','monitor'),
])
def test_explicit_vision_routing(phrase,scope,tmp_path,monkeypatch):
    assert d.vision_request(phrase) and d.desktop_request(phrase)
    assert d.vision_scope(phrase)==scope
    agent=d.DesktopAgent(tmp_path);agent.foreground.target=lambda *a:WINDOW
    captured=[];received=[]
    def capture(kind):
        def run(*args):
            captured.append(kind);return {'image':'actual-capture'}
        return run
    monkeypatch.setattr(n,'capture_window',capture('window'))
    monkeypatch.setattr(n,'capture_screen',capture('monitor'))
    monkeypatch.setattr(n,'capture_all_screens',capture('all_screens'))
    async def describe(text,image):received.append((text,image));return 'Изображение получено'
    agent.describe=describe
    agent.plan=lambda *a:pytest.fail('Explicit vision must not call the text planner')
    events=asyncio.run(collect(agent,phrase))
    assert captured==[scope] and received==[(phrase,'actual-capture')]
    assert events[-1]['text']=='Изображение получено'


@pytest.mark.parametrize('phrase',[
 'Перенеси окно на второй экран','Открой Telegram','Нажми кнопку Продолжить',
 'Напечатай Что у меня на экране?','Не смотри на экран','Как сделать скриншот?',
 'Покажи рабочий стол','Запиши заметку Что ты видишь?',
 'Что такое экран?',
])
def test_vision_does_not_steal_commands(phrase):assert not d.vision_request(phrase)


async def collect(agent,text,approve=None):
    events=[]
    async for event in agent.run(text,'test',[]):
        events.append(event)
        if event['type']=='approval' and approve is not None:agent.approve(event['nonce'],approve)
    return events


def test_vision_disabled_never_captures_or_calls_model(tmp_path,monkeypatch):
    agent=d.DesktopAgent(tmp_path);agent.vision=False
    monkeypatch.setattr(n,'capture_screen',lambda *a:pytest.fail('No capture when disabled'))
    agent.plan=agent.describe=lambda *a:pytest.fail('No model when disabled')
    events=asyncio.run(collect(agent,'Что ты видишь?'))
    assert events[-2]['type']=='agent_stopped' and 'отключены' in events[-1]['text']


@pytest.mark.parametrize('already',[False,True])
@pytest.mark.parametrize('focused',[False,True])
def test_launch_result_is_independent_of_focus(already,focused,monkeypatch):
    started=[]
    monkeypatch.setattr(n,'windows',lambda:[WINDOW] if already or started else [])
    monkeypatch.setattr(n,'same',lambda win:win)
    monkeypatch.setattr(n,'open_app',lambda name,**kw:started.append(name))
    def focus(*args):
        if not focused:raise pc.CommandError('Windows denied foreground')
    monkeypatch.setattr(n,'focus',focus)
    result=n.launch('телега',threading.Event())
    assert result['hwnd']==42 and result['focused']==focused
    assert result['launch_status']==('already_running' if already else 'started')
    assert started==([] if already else ['telegram'])


def test_focus_cancellation_is_not_swallowed(monkeypatch):
    monkeypatch.setattr(n,'same',lambda win:win)
    monkeypatch.setattr(n,'focus',Mock(side_effect=n.Stopped('stop')))
    with pytest.raises(n.Stopped):n.try_focus(WINDOW,threading.Event())


def test_actual_focus_routine_denied_foreground_is_nonfatal_for_launch(monkeypatch):
    monkeypatch.setattr(n,'windows',lambda:[WINDOW])
    monkeypatch.setattr(n,'same',lambda win:win)
    monkeypatch.setattr(n.u,'IsIconic',lambda hwnd:False)
    monkeypatch.setattr(n.u,'SetForegroundWindow',lambda hwnd:False)
    monkeypatch.setattr(n.u,'GetForegroundWindow',lambda:999999)
    monkeypatch.setattr(n.u,'GetWindowThreadProcessId',lambda *a:0)
    monkeypatch.setattr(n,'wait_for',lambda predicate,*a:predicate())
    result=n.launch('telegram',threading.Event())
    assert result['launch_status']=='already_running' and result['focused'] is False


def test_window_capture_never_requires_foreground(monkeypatch):
    monkeypatch.setattr(n,'same',lambda win:win)
    monkeypatch.setattr(n,'focus',lambda *a:pytest.fail('Capture must not focus'))
    process=Mock(returncode=0)
    process.communicate.return_value=(json.dumps(dict(image='png',rect=WINDOW['rect'],scope='window')).encode(),b'')
    monkeypatch.setattr(n.subprocess,'Popen',lambda *a,**kw:process)
    assert n.capture_window(WINDOW,threading.Event())['image']=='png'


def test_monitor_capture_includes_negative_coordinates_and_taskbar(monkeypatch):
    screens=[dict(index=1,primary=True,rect=[0,0,1920,1040],bounds=[0,0,1920,1080]),
             dict(index=2,primary=False,rect=[-1280,0,0,984],bounds=[-1280,0,0,1024])]
    monkeypatch.setattr(n,'monitors',lambda:screens)
    monkeypatch.setattr(n,'_capture_bounds',lambda rect,scope,target,cancel:dict(rect=rect,scope=scope,target=target))
    assert n.capture_screen(threading.Event(),2)['rect']==[-1280,0,0,1024]
    assert n.capture_all_screens(threading.Event())['rect']==[-1280,0,1920,1080]


@pytest.mark.parametrize('name,app',[('телега','telegram'),('дискорд','discord'),('google chrome','chrome')])
def test_aliases_reach_real_tools(name,app):
    assert d.deterministic('Открой '+name).steps[0].name==app


def test_packaged_app_fallback_uses_only_discovered_id(monkeypatch):
    monkeypatch.setattr(pc,'app_path',Mock(side_effect=pc.AppNotFound('absent')))
    monkeypatch.setattr(pc,'installed_shell_apps',lambda:[{'Name':'Telegram Desktop','AppID':'Test.Telegram_x!App'}])
    start=Mock();monkeypatch.setattr(pc.os,'startfile',start)
    pc.open_app('телега')
    start.assert_called_once_with('shell:AppsFolder\\Test.Telegram_x!App')
    with pytest.raises(pc.AppNotFound):pc.open_app('nonexistent')


def test_model_actually_receives_image(monkeypatch):
    original=httpx.AsyncClient;received=[]
    def handler(request):
        body=json.loads(request.content);received.append(body)
        return httpx.Response(200,json={'message':{'content':'Вижу изображение'}})
    monkeypatch.setattr(vision.httpx,'AsyncClient',lambda **kw:original(transport=httpx.MockTransport(handler),**kw))
    result=asyncio.run(vision.image_query('qwen3.5:4b','Опиши','actual-base64'))
    assert result=='Вижу изображение' and len(received)==1
    assert received[0]['messages'][-1]['images']==['actual-base64']
    assert received[0]['model']=='qwen3.5:4b'


@pytest.mark.parametrize('available',[True,False])
@pytest.mark.parametrize('allow',[True,False])
def test_uia_then_real_coordinate_executor(available,allow,tmp_path,monkeypatch):
    agent=d.DesktopAgent(tmp_path);agent.foreground.target=lambda *a:WINDOW
    row=dict(id='button',name='Продолжить',type='ButtonControl',enabled=True)
    calls=[]
    def uia_call(window,op,cancel,**kw):
        if op=='inspect':return {'elements':[row] if available else []}
        calls.append('uia_click');return {'verified':True}
    monkeypatch.setattr(d.uia,'call',uia_call)
    monkeypatch.setattr(n,'same',lambda win:win)
    monkeypatch.setattr(n,'info',lambda hwnd:WINDOW)
    images=iter(['before','after'])
    def screenshot(*a):
        assert not available;calls.append('capture');return next(images),WINDOW['rect']
    monkeypatch.setattr(n,'screenshot',screenshot)
    async def locate(name,image):
        assert name=='Продолжить' and image=='before';calls.append('locate')
        return d.ImagePoint(found=True,x=.25,y=.4,label=name,explanation='visible')
    agent.locate=locate
    async def refresh(window,name,before,anchor):calls.append('refresh');return before,WINDOW['rect'],anchor
    agent.refresh_target=refresh
    def click(*args):
        assert args[1:3]==(.25,.4);calls.append('coordinate_click')
    monkeypatch.setattr(n,'point_click',click)
    async def verify(*a):calls.append('verify');return d.VisualResult(verified=True,explanation='done')
    agent.verify_visual=verify
    events=asyncio.run(collect(agent,'Нажми кнопку Продолжить',allow))
    assert any(e['type']=='approval' for e in events)
    if available:assert calls==(['uia_click'] if allow else [])
    else:assert calls==(['capture','locate','refresh','coordinate_click','capture','verify'] if allow else ['capture','locate'])
    assert any(e.get('status')=='done' for e in events)==allow


def test_missing_uia_and_disabled_vision_stops(tmp_path,monkeypatch):
    agent=d.DesktopAgent(tmp_path);agent.vision=False;agent.foreground.target=lambda *a:WINDOW
    monkeypatch.setattr(d.uia,'call',lambda *a,**kw:{'elements':[]})
    monkeypatch.setattr(n,'screenshot',lambda *a:pytest.fail('disabled capture'))
    events=asyncio.run(collect(agent,'Нажми кнопку Продолжить'))
    assert 'Снимки отключены' in events[-1]['text']


def test_tool_error_not_invented_by_model(tmp_path,monkeypatch):
    agent=d.DesktopAgent(tmp_path);agent.plan=lambda *a:pytest.fail('Do not ask model to open apps')
    monkeypatch.setattr(n,'launch',Mock(side_effect=pc.AppNotFound('Не нашла Telegram среди установленных приложений.')))
    assert asyncio.run(collect(agent,'Открой Telegram'))[-1]['text']=='Не нашла Telegram среди установленных приложений.'


def test_stop_phrase():assert d.stop_request('Пятница, стоп')


def test_grounding_wrappers_do_not_bypass_coordinate_validation():
    box=vision.structured_answer('```json\n[{"found":true,"box":[10,20,100,150],"label":"Continue","explanation":"visible"}]\n```',d.ImageBox)
    assert box.box==[10,20,100,150]
    for coords in ([0,0,1001,100],[20,20,10,10]):
        with pytest.raises(ValueError):vision.structured_answer(json.dumps(dict(found=True,box=coords,label='x',explanation='x')),d.ImageBox)
    with pytest.raises(ValueError):vision.structured_answer('{"found":true,"box":[0,0,10,10],"label":"x","explanation":"x","tool":"shell"}',d.ImageBox)


def test_coordinate_click_denied_focus_never_sends_input(monkeypatch):
    monkeypatch.setattr(n,'focus',Mock(side_effect=pc.CommandError('denied')))
    click=Mock();monkeypatch.setattr(n.u,'mouse_event',click)
    with pytest.raises(pc.CommandError):n.point_click(WINDOW,.5,.5,WINDOW['rect'],'image',threading.Event())
    click.assert_not_called()


def test_missing_uia_fallback_also_works_inside_model_plan(tmp_path,monkeypatch):
    agent=d.DesktopAgent(tmp_path);agent.foreground.target=lambda *a:WINDOW
    async def plan(*a):return d.Plan(steps=[d.Step(tool='click',name='Продолжить')])
    agent.plan=plan
    monkeypatch.setattr(d.uia,'call',Mock(side_effect=pc.CommandError('provider unavailable')))
    monkeypatch.setattr(n,'screenshot',lambda *a:('image',WINDOW['rect']))
    async def locate(*a):return d.ImagePoint(found=True,x=.2,y=.3,label='Продолжить',explanation='visible')
    agent.locate=locate
    events=asyncio.run(collect(agent,'Продолжим работу',False))
    approval=next(e for e in events if e['type']=='approval')
    assert approval['image']=='image' and (approval['x'],approval['y'])==(.2,.3)


def test_stop_during_shell_catalog_terminates_worker(monkeypatch):
    cancel=threading.Event();process=Mock();process.poll.return_value=None
    def communicate(**kw):
        if 'timeout' in kw:
            cancel.set();raise pc.subprocess.TimeoutExpired('fixed command',.1)
        return b'[]',b''
    process.communicate.side_effect=communicate
    monkeypatch.setattr(pc.subprocess,'Popen',lambda *a,**kw:process)
    with pytest.raises(pc.CommandError,match='Остановлено'):pc.installed_shell_apps(cancel)
    process.kill.assert_called_once()


def test_no_tool_means_no_invented_os_failure(tmp_path,monkeypatch):
    agent=d.DesktopAgent(tmp_path)
    monkeypatch.setattr(d,'deterministic',lambda text:None)
    async def plan(*a):return d.Plan(reply='Windows не разрешает: у меня нет доступа.')
    agent.plan=plan
    events=asyncio.run(collect(agent,'Открой Telegram'))
    assert 'нет доступа' not in events[-1]['text'] and 'Не удалось составить' in events[-1]['text']
