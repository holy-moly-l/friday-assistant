import asyncio
import base64
import io
import json
from pathlib import Path
import sys
import threading
from unittest.mock import Mock
sys.path.insert(0,str(Path(__file__).parents[1]/'backend'))
import pytest
from PIL import Image,ImageDraw
import desktop_agent as d
import desktop_native as n
import desktop_images as images
from desktop_display import display_number
from desktop_trace import trace
from pc import CommandError

WIN=dict(hwnd=42,pid=12,created=1,title='Test',process='app.exe',rect=[0,0,640,480],minimized=False)


@pytest.mark.parametrize('noun',['экран','монитор','дисплей'])
@pytest.mark.parametrize('word,number',[('первый',1),('второй',2),('третий',3),('1',1),('2',2),('3',3)])
def test_shared_display_parser(noun,word,number):
    text=f'{word} {noun}'
    assert display_number(text)==number
    assert display_number(f'{noun} {number}')==number
    assert d.deterministic(f'Перенеси окно на {text}').steps[0].monitor==number
    assert display_number(f'Что видно на {text}?')==number


@pytest.mark.parametrize('text,number',[('на втором экране',2),('на третьем мониторе',3),('экран номер 2',2),('монитор № 3',3),('2-й экран',2)])
def test_display_declensions(text,number):assert display_number(text)==number


def test_wake_word_is_not_fifth_display():
    assert display_number('Пятница, экран 2')==2
    assert display_number('Пятница, посмотри на экран') is None


@pytest.mark.parametrize('text,tool',[
 ('Какие окна сейчас открыты?','list_windows'),('Какие окна открыты?','list_windows'),
 ('Какие программы у меня запущены?','list_windows'),('Что сейчас открыто?','list_windows'),
 ('Какие приложения ты сейчас видишь?','list_windows'),('Какое окно сейчас активно?','get_active_window'),
 ('Сколько мониторов подключено?','list_monitors'),('На каком мониторе сейчас это окно?','window_monitor'),
])
def test_local_information_never_uses_qwen(text,tool,tmp_path,monkeypatch):
    assert d.deterministic(text).steps[0].tool==tool and not d.vision_request(text)
    agent=d.DesktopAgent(tmp_path);agent.foreground.target=lambda *a:WIN
    agent.plan=agent.describe=lambda *a:pytest.fail('No model')
    monkeypatch.setattr(n,'windows_text',lambda:'Сейчас открыты Telegram, Chrome — 3 окна.')
    monkeypatch.setattr(n,'monitors',lambda:[dict(index=7,name='Display',device='DISPLAY7')])
    monkeypatch.setattr(n,'window_monitor',lambda w:dict(index=7))
    events=asyncio.run(collect(agent,text))
    assert not any(e['type']=='agent_stopped' for e in events)
    assert any(e.get('status')=='done' for e in events)


async def collect(agent,text,allow=False):
    events=[]
    async for event in agent.run(text,'test',[]):
        events.append(event)
        if event['type']=='approval':agent.approve(event['nonce'],allow)
    return events


def test_sparse_windows_display_ids_not_array_offsets(monkeypatch):
    screens=[dict(index=7,primary=True,rect=[0,0,1920,1080],bounds=[0,0,1920,1080]),
             dict(index=2,primary=False,rect=[1920,0,3200,1024],bounds=[1920,0,3200,1024])]
    monkeypatch.setattr(n,'monitors',lambda:screens)
    monkeypatch.setattr(n,'_capture_bounds',lambda rect,scope,target,cancel:target)
    assert n.capture_screen(threading.Event(),7)=={'monitor':7}
    with pytest.raises(CommandError):n.capture_screen(threading.Event(),1)


def test_capture_uses_windows_monitor_of_minimized_window(monkeypatch):
    screens=[dict(index=2,primary=True,bounds=[0,0,1920,1080]),dict(index=7,primary=False,bounds=[1920,0,3200,1024])]
    monkeypatch.setattr(n,'monitors',lambda:screens)
    monkeypatch.setattr(n,'window_monitor',lambda window:screens[1])
    monkeypatch.setattr(n,'_capture_bounds',lambda rect,scope,target,cancel:target)
    assert n.capture_screen(threading.Event(),window={**WIN,'rect':[-32000,-32000,-31840,-31972],'minimized':True})=={'monitor':7}


@pytest.mark.parametrize('failure',['blank','crash','timeout'])
def test_print_worker_failure_reaches_crop_and_reaps_worker(failure,monkeypatch):
    monkeypatch.setattr(n,'same',lambda w:WIN)
    process=Mock(returncode=0);process.poll.return_value=0
    if failure=='blank':process.communicate.return_value=(json.dumps({'error':'blank image'}).encode(),b'')
    if failure=='crash':process.returncode=1;process.communicate.return_value=(b'',b'')
    if failure=='timeout':
        process.poll.return_value=None
        process.communicate.side_effect=[n.subprocess.TimeoutExpired('capture',.1),(b'',b'')]
        clock=iter([0,7]);monkeypatch.setattr(n.time,'monotonic',lambda:next(clock))
    monkeypatch.setattr(n.subprocess,'Popen',lambda *a,**kw:process)
    crop=Mock(return_value={'method':'MonitorCropFallback','image':'visible image'})
    monkeypatch.setattr(n,'_monitor_crop',crop)
    assert n.capture_window(WIN,threading.Event())['method']=='MonitorCropFallback'
    crop.assert_called_once()
    if failure=='timeout':process.kill.assert_called_once()


def test_windows_are_grouped_without_private_titles(monkeypatch):
    monkeypatch.setattr(n,'windows',lambda:[{**WIN,'process':'chrome.exe','title':'private message'},
        {**WIN,'process':'chrome.exe','title':'password'}, {**WIN,'process':'telegram.exe','title':'private chat'}])
    assert n.windows_text()=='Сейчас открыты: Chrome — 2 окна, Telegram.'


@pytest.mark.parametrize('failure',[None,'print','both','stop'])
def test_minimized_state_is_restored_even_after_failure(failure,monkeypatch):
    state={'minimized':True};calls=[];cancel=threading.Event()
    monkeypatch.setattr(n,'same',lambda w:{**WIN,**state})
    monkeypatch.setattr(n,'info',lambda h:{**WIN,**state})
    monkeypatch.setattr(n,'placement',lambda w:'saved')
    monkeypatch.setattr(n,'restore_placement',lambda w,p:calls.append('restore'))
    monkeypatch.setattr(n.u,'IsIconic',lambda h:state['minimized'])
    def show(hwnd,mode):state['minimized']=mode==7;calls.append(mode)
    monkeypatch.setattr(n.u,'ShowWindowAsync',show)
    def capture(*a):
        assert not state['minimized']
        if failure=='stop':cancel.set();raise n.Stopped('stop')
        if failure:raise CommandError('PrintWindow failed')
        return {'image':'ok'}
    monkeypatch.setattr(n,'_print_window',capture)
    def fallback(*a):
        calls.append('fallback')
        if failure=='both':raise CommandError('covered')
        return {'image':'fallback'}
    monkeypatch.setattr(n,'_monitor_crop',fallback)
    if failure in ('both','stop'):
        with pytest.raises(CommandError):n.capture_window(WIN,cancel)
    else:assert n.capture_window(WIN,cancel)['image'] in ('ok','fallback')
    assert state['minimized'] and calls[-2:]==[7,'restore']
    assert ('fallback' in calls)==(failure in ('print','both'))


def test_occluded_fallback_never_captures_wrong_window(monkeypatch):
    monkeypatch.setattr(n,'same',lambda w:WIN)
    monkeypatch.setattr(n,'unobscured',lambda w:False)
    monkeypatch.setattr(n,'_capture_bounds',lambda *a,**kw:pytest.fail('covered window must not be cropped'))
    with pytest.raises(CommandError,match='перекрыто'):n._monitor_crop(WIN,threading.Event())


@pytest.mark.parametrize('name,typ,extra',[
 ('Назад','ButtonControl',{}),('Вперёд','ButtonControl',{}),('Файл','MenuItemControl',{}),
 ('Пауза','ButtonControl',{}),('Play','ButtonControl',{}),('Обзор','TabItemControl',{}),
 ('Документ','ListItemControl',{'selected':False}),('Размер','ComboBoxControl',{'expanded':0}),
])
def test_safe_uia_does_not_ask(name,typ,extra):
    element={'name':name,'type':typ,**extra}
    assert d.approval_reason(d.Step(tool='click',name=name),WIN,element,[]) is None


@pytest.mark.parametrize('name',['Удалить','Отправить','Оплатить','Заказать','Сохранить','Перезаписать','Подтвердить','Продолжить','Неизвестное действие'])
def test_unsafe_uia_still_asks(name):
    assert d.approval_reason(d.Step(tool='click',name=name),WIN,dict(name=name,type='ButtonControl'),[])


@pytest.mark.parametrize('title',['Login','Авторизация','Платежи','Billing','Log in'])
def test_login_requires_approval_even_for_tab(title):
    assert d.approval_reason(d.Step(tool='click',name='Обзор'),{**WIN,'title':title},dict(name='Обзор',type='TabItemControl'),[])


@pytest.mark.parametrize('name',['Перезаписать','Overwrite','Заменить','Отправить'])
def test_destructive_tab_cannot_bypass_approval(name):
    assert d.approval_reason(d.Step(tool='click',name=name),WIN,dict(name=name,type='TabItemControl'),[])


@pytest.mark.parametrize('response',[
    '```json\n{"reply":"Ошибка 810","needs_vision":false,"steps":[]}\n```',
    '{"reply":"Ошибка 810","needs_vision":false,"steps":[]}',
])
def test_planner_accepts_wrapped_json_without_extra_model_request(response,tmp_path,monkeypatch):
    from ai_providers import AIResult
    agent=d.DesktopAgent(tmp_path);calls=[]
    async def request(*a,**kw):calls.append(a);return AIResult(response,'ollama',agent.model)
    monkeypatch.setattr(agent.ai.local,'plan',request)
    plan=asyncio.run(agent.plan('Объясни ошибку',[],{}))
    assert not plan.steps and plan.reply=='Ошибка 810'
    assert len(calls)==1


def test_wrapped_plan_still_rejects_unknown_tools():
    with pytest.raises(ValueError):d.structured_answer('```json\n{"steps":[{"tool":"shell","text":"anything"}]}\n```',d.Plan)


def png(offset=0,animation=False,changed=False):
    im=Image.new('RGB',(640,480),'#eeeeee' if not changed else '#162036')
    draw=ImageDraw.Draw(im);draw.rectangle((90+offset,100,210+offset,145),fill='#4488bb')
    draw.text((110+offset,112),'Continue',fill='white')
    if animation:draw.rectangle((570,410,594,430),fill='red')
    buf=io.BytesIO();im.save(buf,format='PNG');return base64.b64encode(buf.getvalue()).decode()


def point(offset=0,label='Continue'):
    return d.ImagePoint(found=True,x=(150+offset)/640,y=122.5/480,box=[(90+offset)/640,100/480,(210+offset)/640,145/480],label=label,explanation='visible')


def test_small_changes_allowed_large_changes_rejected():
    assert images.scene_stable(png(),png(animation=True))<.01
    assert images.target_stable(png(),png(offset=12,animation=True),point(),point(12))[0]<.05
    with pytest.raises(CommandError):images.scene_stable(png(),png(changed=True))


def test_refresh_relocalizes_and_uses_fresh_coordinates(tmp_path,monkeypatch):
    agent=d.DesktopAgent(tmp_path);new=png(offset=12,animation=True)
    monkeypatch.setattr(n,'focus',lambda *a:None)
    monkeypatch.setattr(n,'screenshot',lambda *a:(new,WIN['rect']))
    async def locate(name,image):
        assert name=='Continue' and image==new
        return point(12)
    agent.locate=locate
    image,rect,target=asyncio.run(agent.refresh_target(WIN,'Continue',png(),point()))
    assert abs(target.x-162/640)<3/640 and image==new


def test_stop_during_relocalization_sends_no_click(tmp_path,monkeypatch):
    agent=d.DesktopAgent(tmp_path)
    monkeypatch.setattr(n,'focus',lambda *a:None)
    monkeypatch.setattr(n,'screenshot',lambda *a:(png(),WIN['rect']))
    async def locate(*a):await asyncio.sleep(30)
    agent.locate=locate
    async def run():
        task=asyncio.create_task(agent.refresh_target(WIN,'Continue',png(),point()))
        await asyncio.sleep(.1);agent.stop()
        with pytest.raises(n.Stopped):await asyncio.wait_for(task,.5)
    asyncio.run(run())


def test_debug_log_never_contains_input_fields_or_model_text(monkeypatch,capsys):
    monkeypatch.setenv('FRIDAY_DEBUG','1')
    secret='Введи пароль qwerty123 confidential-message'
    for stage in ('INPUT','VOICE','AI RESULT','VERIFY','RESULT'):
        trace(stage,secret,text=secret,name=secret,value=secret,reason=secret,target={'title':secret},model='qwen3.5:4b')
    output=capsys.readouterr().err
    assert 'qwerty123' not in output and 'confidential' not in output and 'пароль' not in output
    assert 'qwen3.5:4b' in output and 'length' in output
