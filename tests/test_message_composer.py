"""No real messages/network: local composer contract and Telegram integration."""
import asyncio
import json
from pathlib import Path
import sys
import threading
import time
import pytest
sys.path[:0]=[str(Path(__file__).parents[1]/'backend'),str(Path(__file__).parent)]
from ai_providers import AIResult, ProviderError
from message_composer import MessageComposer, CompositionError, ComposedMessage, safe_rewrite
from telegram_language import message_intent
from telegram_messages import TelegramMessages
from desktop_agent import DesktopAgent
from test_telegram_messages import FakeTelegram, FakeComposer, collect, answer

CASES=[
 ('Напиши Насте, что пусть приедет сегодня в 12 часов','Приезжай сегодня в 12 часов.'),
 ('Скажи Насте, что я опоздаю на 20 минут','Я опоздаю на 20 минут.'),
 ('Скажи Саше, чтобы он купил хлеб','Купи хлеб.'),
 ('Спроси Настю, сможет ли она приехать завтра','Сможешь приехать завтра?'),
 ('Скажи Насте, что Саша уже приехал','Саша уже приехал.'),
 ('Скажи Насте, пусть не ждёт меня сегодня','Не жди меня сегодня.'),
 ('Напиши Насте, что я уже выехал','Я уже выехал.'),
 ('Скажи Саше, что он забыл у меня зарядку','Ты забыл у меня зарядку.'),
 ('Передай Насте, что мы будем примерно в восемь','Мы будем примерно в восемь.'),
 ('Напиши Насте, что пусть позвонит мне, когда освободится','Позвони мне, когда освободишься.'),
 ('Скажи Насте, что она забыла ключи','Ты забыла ключи.'),
 ('Скажи Насте, что я забыл ключи','Я забыл ключи.'),
 ('Спроси Настю, будет ли она дома в 12:30','Будешь дома в 12:30?'),
 ('Скажи Насте, чтобы не ждала меня','Не жди меня.'),
 ('Напиши Насте, что я приеду 25.09.2026 в 12:30','Я приеду 25.09.2026 в 12:30.'),
 ('Напиши Насте, что адрес: улица Ленина, дом 12','Адрес: улица Ленина, дом 12.'),
 ('Напиши Насте, что ссылка https://example.org/a?x=12&y=20','Ссылка https://example.org/a?x=12&y=20.'),
]


class Provider:
    model='qwen3.5:4b'
    def __init__(self,*results):self.results=list(results);self.calls=[];self.options={};self.cancelled=False
    def cancel(self):self.cancelled=True
    async def _request_once(self,messages,schema):
        self.calls.append((messages,schema))
        result=self.results.pop(0)
        if isinstance(result,Exception):raise result
        return AIResult(json.dumps(result,ensure_ascii=False),'ollama',self.model,{})


def data(text,needs=False):return dict(text=text,needs_clarification=needs)


@pytest.mark.parametrize('command,expected',CASES)
def test_parser_and_guard_accept_supported_perspective(command,expected):
    intent=message_intent(command)
    assert intent and intent.text and not intent.error
    assert safe_rewrite(intent.text,expected,intent.mode)
    p=Provider(data(expected))
    result=asyncio.run(MessageComposer(provider=p).compose_message(intent.text,intent.recipient,{'mode':intent.mode}))
    assert result.text==expected and not result.verbatim and len(p.calls)==1


@pytest.mark.parametrize('prefix',[
    'Напиши Насте дословно:', 'Отправь Насте слово в слово:',
    'Напиши Насте именно так:', 'Напиши Насте сообщение дословно',
    'Отправь как есть:', 'Напиши Насте дословно',
])
def test_verbatim_never_calls_model_and_preserves_payload(prefix):
    original='пусть приезжает сегодня, 12:30!\n{Enter}  Ёж — https://example.org/a?x=12'
    intent=message_intent(prefix+' '+original)
    assert intent.verbatim and intent.text==original
    provider=Provider()
    result=asyncio.run(MessageComposer(provider=provider).compose_message(intent.text,intent.recipient,verbatim=True))
    assert result==ComposedMessage(original,True) and not provider.calls


@pytest.mark.parametrize('command', ['Скажи сколько времени','Спроси у модели про космос','Передай файл','Напиши стихотворение'])
def test_non_message_not_captured(command):
    result=message_intent(command)
    assert result is None or result.error


@pytest.mark.parametrize('raw,bad',[
    ('пусть приедет в 12 часов','Приезжай в 2 часа.'),
    ('я буду через 20 минут','Я буду через час.'),
    ('я буду завтра','Я буду сегодня.'),
    ('я приеду 25.09.2026','Я приеду 26.09.2026.'),
    ('я буду в восемь','Я буду в девять.'),
    ('я приеду в 12','Я приеду после 12.'),
    ('баланс -20 рублей','Баланс 20 рублей.'),
    ('я не приеду сегодня','Я приеду сегодня.'),
    ('я приеду сегодня','Я не приеду сегодня.'),
    ('я не обещал приехать','Я обещал не приехать.'),
    ('я забыл ключи','Ты забыл ключи.'),
    ('я опоздаю','Я опоздал.'),
    ('Саша уже приехал','Ты уже приехал.'),
    ('ссылка https://example.org/a?x=12','Ссылка https://evil.org/a?x=12.'),
    ('я занят','Я занят, пожалуйста, позвони позже.'),
    ('я занят',''),('я занят','X'*500),
    ('я обещаю приехать','Я приеду.'),
    ('я бы приехал','Я приехал.'),
    ('если будет дождь, я не приеду','Будет дождь, я не приеду.'),
    ('я занят','Я занят 🙂.'),
    ('он забыл у меня зарядку','Он забыл у меня зарядку.'),
    ('Саша ждёт Машу','Маша ждёт Сашу.'),
])
def test_safety_rejects_changed_facts(raw,bad):
    assert not safe_rewrite(raw,bad)
    provider=Provider(data(bad),data(bad))
    with pytest.raises(CompositionError):asyncio.run(MessageComposer(provider=provider).compose_message(raw,'Настя'))
    assert len(provider.calls)==2


def test_retry_once_and_clarification():
    p=Provider(data('Я приеду в 2.'),data('Я приеду в 12.'))
    assert asyncio.run(MessageComposer(provider=p).compose_message('я приеду в 12','Настя')).text=='Я приеду в 12.'
    assert len(p.calls)==2
    p=Provider(data('',True))
    assert asyncio.run(MessageComposer(provider=p).compose_message('он сказал ей про него','Настя')).needs_clarification


def test_strict_schema_and_malformed_retry():
    for bad in ({'text':'Привет.'},dict(text='Привет.',needs_clarification=False,recipient='Другой')):
        p=Provider(bad,bad)
        with pytest.raises(CompositionError):asyncio.run(MessageComposer(provider=p).compose_message('привет','Настя'))
        assert len(p.calls)==2


def test_long_message_and_length_limit():
    raw='Я приеду завтра в 12 часов. '*85
    p=Provider(data(raw))
    assert asyncio.run(MessageComposer(provider=p).compose_message(raw,'Настя')).text==raw.strip()
    assert p.options['num_predict']>768
    with pytest.raises(CompositionError):asyncio.run(MessageComposer(provider=p).compose_message('x'*4001,'Настя'))


def test_model_unavailable_never_uses_cloud():
    p=Provider(ProviderError('unavailable','Private diagnostic must not escape'))
    with pytest.raises(CompositionError,match='дословно') as exc:
        asyncio.run(MessageComposer(provider=p).compose_message('я занят','Настя'))
    assert 'Private' not in str(exc.value) and len(p.calls)==1


def test_only_allowed_context_is_sent_and_logs_redacted(monkeypatch,capsys):
    monkeypatch.setenv('FRIDAY_DEBUG','1')
    p=Provider(data('Я занят.'))
    asyncio.run(MessageComposer(provider=p).compose_message('я занят','PrivateRecipient',{'mode':'statement','history':'SECRET_HISTORY'}))
    logged=capsys.readouterr().err
    assert '[MESSAGE_COMPOSER]' in logged and 'input_length' in logged and 'verbatim' in logged
    assert not any(s in logged for s in ['PrivateRecipient','занят','SECRET_HISTORY'])
    assert 'SECRET_HISTORY' not in json.dumps(p.calls)


def test_stop_during_composition_and_no_telegram_launch(tmp_path):
    class SlowProvider(Provider):
        async def _request_once(self,*args):
            self.calls.append(True);await asyncio.sleep(30)
    p=SlowProvider();fake=FakeTelegram();agent=DesktopAgent(tmp_path)
    agent.telegram=TelegramMessages(fake.call,fake.launch,MessageComposer(provider=p))
    async def run():
        task=asyncio.create_task(collect(agent,'Напиши Насте, что я занят'))
        while not p.calls:await asyncio.sleep(.01)
        start=time.perf_counter();agent.stop();events=await task
        assert time.perf_counter()-start<1 and 'не отправляла' in answer(events)
    asyncio.run(run())
    assert not fake.calls and not agent.running and not agent.telegram.pending_messages


def test_cancel_event_without_agent_stop():
    class SlowProvider(Provider):
        async def _request_once(self,*args):await asyncio.sleep(30)
    async def run():
        event=threading.Event();c=MessageComposer(provider=SlowProvider())
        task=asyncio.create_task(c.compose_message('я занят','Настя',cancel=event))
        await asyncio.sleep(.05);event.set()
        with pytest.raises(asyncio.CancelledError):await asyncio.wait_for(task,1)
        assert not c._tasks
    asyncio.run(run())


def test_rewritten_text_is_prepared_confirmed_and_verified(tmp_path):
    fake=FakeTelegram();agent=DesktopAgent(tmp_path);p=Provider(data('Приезжай сегодня в 12 часов.'))
    agent.telegram=TelegramMessages(fake.call,fake.launch,MessageComposer(provider=p))
    def approve(event):
        assert event['text']==fake.draft=='Приезжай сегодня в 12 часов.'
        assert fake.sent==0
        agent.approve(event['nonce'],True)
    events=asyncio.run(collect(agent,CASES[0][0],on_approval=approve))
    assert fake.sent==1 and answer(events)=='Отправила Насте.'
    assert fake.calls.index('prepare')<fake.calls.index('send')<fake.calls.index('verify')


@pytest.mark.parametrize('reply',['отмена','Пятница, отмена','нет'])
def test_composition_failure_preserves_original_for_explicit_verbatim_or_cancel(tmp_path,reply):
    fake=FakeTelegram();agent=DesktopAgent(tmp_path);p=Provider(ProviderError('unavailable','failed'))
    agent.telegram=TelegramMessages(fake.call,fake.launch,MessageComposer(provider=p))
    events=asyncio.run(collect(agent,'Напиши Насте, что пусть приедет в 12'))
    assert 'дословно' in answer(events) and not fake.calls
    asyncio.run(collect(agent,reply))
    assert not agent.telegram.pending_messages and not fake.sent


def test_explicit_verbatim_fallback_still_requires_approval(tmp_path):
    fake=FakeTelegram();agent=DesktopAgent(tmp_path);p=Provider(ProviderError('unavailable','failed'))
    agent.telegram=TelegramMessages(fake.call,fake.launch,MessageComposer(provider=p))
    asyncio.run(collect(agent,'Напиши Насте, что пусть приедет в 12'))
    events=asyncio.run(collect(agent,'отправь дословно',decision=False))
    approval=next(e for e in events if e['type']=='approval')
    assert approval['text']=='пусть приедет в 12' and not fake.sent and not fake.draft
    assert len(p.calls)==1


def test_two_turn_text_and_pronoun_context_use_composer(tmp_path):
    fake=FakeTelegram();agent=DesktopAgent(tmp_path)
    p=Provider(data('Я задержусь на час.'),data('Буду позже.'))
    agent.telegram=TelegramMessages(fake.call,fake.launch,MessageComposer(provider=p))
    asyncio.run(collect(agent,'Напиши Насте'))
    assert not p.calls
    first=asyncio.run(collect(agent,'Я задержусь на час',decision=True))
    second=asyncio.run(collect(agent,'Ответь ей, что буду позже',decision=False))
    assert next(e['text'] for e in first if e['type']=='approval')=='Я задержусь на час.'
    assert next(e['text'] for e in second if e['type']=='approval')=='Буду позже.'
    assert fake.sent==1


def test_meaningful_message_word_is_not_stripped_after_that():
    assert message_intent('Напиши Насте что сообщение дошло').text=='сообщение дошло'


def test_finite_first_person_and_past_subjects():
    assert safe_rewrite('я приеду завтра. Я буду ждать. Я не забыл ключи.',
                        'Приеду завтра. Буду ждать. Я не забыл ключи.')
    assert not safe_rewrite('буду позже','Будешь позже.')
    assert not safe_rewrite('Я не забыл ключи.','Ты не забыл ключи.')


def test_real_http_contract_is_local_text_only(monkeypatch):
    import ai_providers
    import httpx
    requests=[]
    def handle(request):
        requests.append(request);body=json.loads(request.content)
        assert str(request.url)=='http://127.0.0.1:11434/api/chat'
        assert body['model']=='qwen3.5:4b' and body['think'] is False
        assert body['options']==dict(temperature=0,num_ctx=4096,num_predict=768)
        assert 'tools' not in body and all('images' not in m for m in body['messages'])
        response=dict(message=dict(content=json.dumps(data('Я занят.'),ensure_ascii=False)),done=True)
        return httpx.Response(200,text=json.dumps(response)+'\n')
    client=httpx.AsyncClient
    monkeypatch.setattr(ai_providers.httpx,'AsyncClient',lambda **kwargs:client(transport=httpx.MockTransport(handle),**kwargs))
    assert asyncio.run(MessageComposer().compose_message('я занят','Настя')).text=='Я занят.'
    assert len(requests)==1


def test_timeout_is_sanitized_without_model_retry():
    p=Provider(ProviderError('timeout','secret transport details'))
    with pytest.raises(CompositionError,match='локально'):
        asyncio.run(MessageComposer(provider=p).compose_message('я занят','Настя'))
    assert len(p.calls)==1
