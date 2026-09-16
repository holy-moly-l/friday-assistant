import asyncio
import base64
import io
import json
from pathlib import Path
import sys
import threading
import time
from unittest.mock import AsyncMock
import httpx
from PIL import Image,ImageDraw
import pytest
sys.path.insert(0,str(Path(__file__).parents[1]/'backend'))
import ai_providers as p
import ai_router as r
import desktop_agent as d

def picture(size=(2560,1440)):
    im=Image.new('RGB',size,'white');ImageDraw.Draw(im).text((30,40),'Test 810',fill='black')
    buf=io.BytesIO();im.save(buf,format='PNG');return base64.b64encode(buf.getvalue()).decode()

def result(provider='codex',content='{"reply":"видно"}'):
    return p.AIResult(content,provider,'gpt-5.6-luna' if provider=='codex' else 'qwen3.5:4b',dict(first_response_ms=10,total_ms=12))

@pytest.mark.parametrize('mode,vision,complex_,expected',[
    ('local',True,False,False),('hybrid',True,False,True),('codex_vision',True,False,True),
    ('hybrid',False,False,False),('hybrid',False,True,True)])
def test_routes(mode,vision,complex_,expected):
    assert r.ModelRouter(mode=mode,vision_provider='codex').cloud_for(image=vision,task='Сначала разберись, затем составь план' if complex_ else 'Объясни кратко')==expected

def test_qwen_is_default_and_vision_provider_is_explicit():
    router=r.ModelRouter()
    assert not router.cloud_for(image=True)
    assert router.cloud_for(task='Сначала разберись, затем составь план')
    router.vision_provider='codex';assert router.cloud_for(image=True)
    router.mode='local';assert not router.cloud_for(image=True)
    router.mode='codex_vision';router.vision_provider='ollama';assert router.cloud_for(image=True)

@pytest.mark.parametrize('status',['unavailable','not_authenticated','usage_limit','timeout','invalid_response'])
def test_fallback_and_both_unavailable(status):
    async def run():
        router=r.ModelRouter(vision_provider='codex');router.codex.analyze_image=AsyncMock(side_effect=p.ProviderError(status,'private message'))
        router.local.analyze_image=AsyncMock(return_value=result('ollama'))
        value=await router.analyze_image(picture(),'вопрос');assert value.provider=='ollama'
        router.local.analyze_image.assert_awaited_once()
        router.local.analyze_image=AsyncMock(side_effect=p.ProviderError('unavailable','local'))
        with pytest.raises(p.ProviderError,match='Codex и локальная Ollama'):await router.analyze_image(picture(),'вопрос')
        router.fallback=False;router.local.analyze_image.reset_mock()
        with pytest.raises(p.ProviderError):await router.analyze_image(picture(),'вопрос')
        router.local.analyze_image.assert_not_awaited()
    asyncio.run(run())

def test_available_codex_does_not_need_ollama():
    async def run():
        router=r.ModelRouter(vision_provider='codex');router.codex.analyze_image=AsyncMock(return_value=result())
        router.local.analyze_image=AsyncMock(side_effect=AssertionError('must not use local'))
        assert (await router.analyze_image(picture(),'опиши')).provider=='codex'
    asyncio.run(run())

def test_cancel_never_falls_back():
    async def run():
        router=r.ModelRouter(vision_provider='codex');router.codex.analyze_image=AsyncMock(side_effect=asyncio.CancelledError)
        router.local.analyze_image=AsyncMock()
        with pytest.raises(asyncio.CancelledError):await router.analyze_image(picture(),'опиши')
        router.local.analyze_image.assert_not_awaited()
    asyncio.run(run())

def test_preprocessing_crop_and_coordinate_mapping():
    source=picture();prepared=r.prepare_image(source)
    assert prepared.original==(2560,1440) and prepared.sent==(1440,810)
    assert r.prepare_image(source,False).sent==(2560,1440)
    crop,rect=r.crop_image(source,[250,250,750,750])
    assert r.decode(crop).size==(1280,720)
    assert r.map_box([0,0,1000,1000],rect)==[250,250,750,750]
    assert r.map_box([250,250,750,750],rect)==[375,375,625,625]
    for box in ([0,0,0,0],[-1,0,800,900],[0,0,2000,800]):
        with pytest.raises(ValueError):r.crop_image(source,box)

def test_progressive_vision_uses_original_crop():
    async def run():
        router=r.ModelRouter(vision_provider='codex');seen=[]
        async def analyze(images,*args,**kwargs):
            seen.append(r.decode(images[0]).size)
            return result(content='{"reply":"Текст мелкий","needs_crop":true,"crop":[250,250,750,750]}' if len(seen)==1 else '{"reply":"Ошибка 810"}')
        router.codex.analyze_image=analyze
        assert await router.describe('Прочитай текст',picture())=='Ошибка 810'
        assert seen==[(1440,810),(1328,768)]
    asyncio.run(run())

def test_command_is_isolated_and_prompt_is_not_argument(tmp_path,monkeypatch):
    cmd=p.codex_command('codex.exe',tmp_path,'gpt-5.6-luna',['encoded'])
    assert '--ignore-user-config' in cmd and '--ephemeral' in cmd and '--ignore-rules' in cmd
    assert cmd[cmd.index('--sandbox')+1]=='read-only'
    assert 'forced_login_method="chatgpt"' in cmd
    for flag in ('shell_tool','apps','plugins','hooks','browser_use','computer_use','code_mode_host'):
        assert cmd[cmd.index(flag)-1]=='--disable'
    assert 'code_mode.disable_in_process_fallback=true' in cmd
    monkeypatch.setenv('OPENAI_API_KEY','test-secret');monkeypatch.setenv('CODEX_API_KEY','test-secret')
    monkeypatch.setenv('CODEX_HOME',str(tmp_path))
    env=p.codex_environment();assert 'OPENAI_API_KEY' not in env and 'CODEX_API_KEY' not in env
    assert env['CODEX_HOME']==str(tmp_path)
    with pytest.raises(p.ProviderError):p.codex_command('exe',tmp_path,'gpt-5.6-sol',[])

@pytest.mark.parametrize('value,status',[
    ('HTTP status 429','usage_limit'),('usage_limit_reached','usage_limit'),('HTTP 401','not_authenticated'),
    ('network unavailable at 14:29:05.429Z','unavailable'),('connection refused','unavailable')])
def test_error_classification(value,status):assert p.classify_error(value).status==status

def test_schema_rejects_tools_and_bad_coordinates():
    with pytest.raises(p.ProviderError):p.checked_json('{"steps":[{"tool":"shell"}]}',d.Plan.model_json_schema())
    schema=p.strict_schema(d.Plan.model_json_schema());assert schema['required']==list(schema['properties'])
    assert schema['$defs']['Step']['required']==list(schema['$defs']['Step']['properties'])
    assert json.loads(p.checked_json('```json\n{"reply":"ok"}\n```',p.REPLY_SCHEMA))=={'reply':'ok'}

def fake_cli(tmp_path,monkeypatch,body):
    script=tmp_path/'cli_fixture.py';script.write_text('import sys,json,time\n'+body,encoding='utf-8')
    monkeypatch.setattr(p,'codex_executable',lambda:sys.executable)
    monkeypatch.setattr(p,'codex_command',lambda *args:[sys.executable,str(script)])
    provider=p.CodexProvider();provider.health_check=AsyncMock(return_value={'authenticated':True,'status':'connected'})
    return provider

def test_real_subprocess_jsonl_stdin_and_cleanup(tmp_path,monkeypatch):
    provider=fake_cli(tmp_path,monkeypatch,
        'prompt=sys.stdin.read()\nassert "уникальный запрос" in prompt\n'
        'print(json.dumps({"type":"turn.started"}),flush=True)\n'
        'print(json.dumps({"type":"item.completed","item":{"type":"agent_message","text":json.dumps({"reply":"ok"})}}),flush=True)\n'
        'print(json.dumps({"type":"turn.completed"}),flush=True)\ntime.sleep(30)\n')
    start=time.perf_counter();res=asyncio.run(provider.analyze_image(picture(),'уникальный запрос'))
    assert json.loads(res.content)['reply']=='ok' and time.perf_counter()-start<3

@pytest.mark.parametrize('cancel',[True,False])
def test_subprocess_stop_or_timeout_is_bounded(tmp_path,monkeypatch,cancel):
    provider=fake_cli(tmp_path,monkeypatch,'sys.stdin.read()\nprint(json.dumps({"type":"turn.started"}),flush=True)\ntime.sleep(30)\n')
    provider.timeout=.3
    async def run():
        task=asyncio.create_task(provider.analyze_image(picture(),'test'))
        await asyncio.sleep(.12)
        if cancel:provider.cancel()
        with pytest.raises(asyncio.CancelledError if cancel else p.ProviderError):await asyncio.wait_for(task,2)
    asyncio.run(run())

def test_offline_ollama_transport(monkeypatch):
    client=httpx.AsyncClient
    def fail(request):raise httpx.ConnectError('offline')
    monkeypatch.setattr(p.httpx,'AsyncClient',lambda **kw:client(transport=httpx.MockTransport(fail),**kw))
    async def run():
        local=p.LocalOllamaProvider();assert (await local.health_check())['status']=='unavailable'
        with pytest.raises(p.ProviderError):await local.analyze_image(picture(),'опиши')
    asyncio.run(run())

def test_timeout_also_interrupts_blocked_stdin(tmp_path,monkeypatch):
    provider=fake_cli(tmp_path,monkeypatch,'time.sleep(30)\n');provider.timeout=.25
    start=time.perf_counter()
    with pytest.raises(p.ProviderError):asyncio.run(provider.analyze_image(picture(),'x'*2000000))
    assert time.perf_counter()-start<3

def test_logs_never_include_prompt_text_or_image(monkeypatch,capsys):
    monkeypatch.setenv('FRIDAY_DEBUG','1')
    p.trace('VISION','пароль qwerty123',provider='codex',model='gpt-5.6-luna',image='secret-base64',prompt='private',total_ms=22)
    output=capsys.readouterr().err
    assert 'gpt-5.6-luna' in output and '22' in output
    for secret in ('qwerty123','secret-base64','private'):assert secret not in output

@pytest.mark.parametrize('phrase',['Открой Telegram','Громкость 30%','Перенеси Chrome на второй монитор','Какие окна открыты?','Что вообще у меня открыто на компьютере?'])
def test_direct_commands_never_need_cloud(phrase):assert d.deterministic(phrase) is not None

def test_settings_persist_and_validate(tmp_path):
    agent=d.DesktopAgent(tmp_path);assert agent.ai.mode=='hybrid' and agent.ai.codex.model=='gpt-5.6-luna' and agent.ai.vision_provider=='ollama'
    agent.save(agent.model,True,ai_mode='local',cloud_model='gpt-5.6-terra',local_fallback=False,image_optimization=False,vision_provider='codex')
    restored=d.DesktopAgent(tmp_path)
    assert restored.ai.mode=='local' and not restored.ai.fallback and not restored.ai.optimize
    assert restored.ai.vision_provider=='codex'
    with pytest.raises(d.CommandError):restored.save(restored.model,True,cloud_model='gpt-5.6-sol')

@pytest.mark.parametrize('available',[True,False])
def test_find_button_is_uia_first_and_never_clicks(tmp_path,monkeypatch,available):
    agent=d.DesktopAgent(tmp_path);agent.foreground.target=lambda *a:{'hwnd':10,'title':'Test'}
    agent.plan=AsyncMock(side_effect=AssertionError('No planner'))
    agent.observe=AsyncMock(return_value={'elements':[{'id':'x','name':'Продолжить','type':'ButtonControl','enabled':True}] if available else []})
    agent.capture_action=AsyncMock(return_value=(picture(),[0,0,2560,1440]))
    agent.locate=AsyncMock(return_value=d.ImagePoint(found=True,x=.5,y=.5,label='Продолжить',explanation='visible'))
    monkeypatch.setattr(d.native,'point_click',lambda *a:pytest.fail('Finding must not click'))
    async def run():return [e async for e in agent.run('Найди здесь кнопку Продолжить','test',[])]
    events=asyncio.run(run())
    assert any(e.get('status')=='done' for e in events) and not any(e['type']=='approval' for e in events)
    assert agent.locate.await_count==(0 if available else 1)
