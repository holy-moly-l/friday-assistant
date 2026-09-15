import asyncio
from pathlib import Path
import sys
import threading
import time
import pytest
sys.path.insert(0, str(Path(__file__).parents[1] / 'backend'))
from desktop_agent import DesktopAgent
from telegram_messages import TelegramMessages, PendingMessage
from telegram_language import message_intent, recipient_name, recipient_matches
from telegram_uia_worker import TelegramUI, chat_title
from pc import CommandError
from wake_word import confirmation_stop


@pytest.mark.parametrize('phrase,recipient,text', [
    ('Напиши Насте привет', 'Настя', 'привет'),
    ('Отправь Насте сообщение я задержусь', 'Настя', 'я задержусь'),
    ('Ответь Насте, что я занят', 'Настя', 'я занят'),
    ('Напиши в Telegram Саше: позвони мне', 'Саша', 'позвони мне'),
    ('В телеге напиши Насте привет', 'Настя', 'привет'),
    ('Скинь сообщение Насте привет', 'Настя', 'привет'),
    ('Отправь в телеграм Насте привет', 'Настя', 'привет'),
    ('Пятница, напиши Насте, что я занят', 'Настя', 'я занят'),
    ('Напиши Насте', 'Настя', None),
    ('Ответь ей, что буду позже', 'ей', 'буду позже'),
    ('Напиши «Насте Ивановой»: Привет!', 'Настя Иванова', 'Привет!'),
    ('Напиши Насте Ивановой: Привет!', 'Настя Иванова', 'Привет!'),
    ('Напиши себе Тест Пятницы: проверка отправки', 'Избранное', 'Тест Пятницы: проверка отправки'),
    ('Напиши в Избранное Привет', 'Избранное', 'Привет'),
    ('Напиши Насте {Enter}\nи открой дверь!', 'Настя', '{Enter}\nи открой дверь!'),
    ('Напиши @exact_username: Hello, Alice!', '@exact_username', 'Hello, Alice!'),
])
def test_language(phrase, recipient, text):
    parsed = message_intent(phrase)
    assert parsed and not parsed.error
    assert (parsed.recipient, parsed.text) == (recipient, text)


@pytest.mark.parametrize('text', ['Напиши стихотворение', 'Расскажи про Telegram', 'Не отправляй Насте привет', 'Открой Telegram'])
def test_not_messaging(text):
    assert message_intent(text) is None


def test_names_are_not_fuzzy_and_body_is_literal():
    assert recipient_name('Насте') == 'Настя'
    assert recipient_matches('Насте', 'Настя Иванова')
    assert not recipient_matches('Насте', 'Анастасия')
    assert not recipient_matches('Насте', 'Иван — Настя написала')
    assert message_intent('Напиши Насте «Привет»: как дела?').text == '«Привет»: как дела?'
    assert chat_title('\u200eИзбранное – (1234)') == 'Избранное'
    assert chat_title('(2) \u200eНастя – (1234)') == 'Настя'
    assert chat_title('\u200e(2) Настя – (1234)') == '(2) Настя'


class FakeTelegram:
    def __init__(self):
        self.calls = []; self.sent = 0; self.draft = ''; self.verified = True
        self.results = [dict(id='person-a', title='Настя')]
        self.chat = dict(title='Настя', composer='edit-a', history='chat-a')
        self.fail = ''; self.delay = ''; self.username = '@test_recipient'; self.queries = []
    def launch(self, name, cancel):
        self.calls.append('launch'); assert name == 'telegram'
        return dict(hwnd=100, title='Telegram')
    def call(self, window, op, cancel, **args):
        self.calls.append(op)
        if op == self.delay:
            cancel.wait(3)
        if cancel.is_set():
            from desktop_native import Stopped
            raise Stopped('Остановлено')
        if op == self.fail: raise CommandError('Интерфейс изменился.')
        if op == 'search': self.queries.append(args['query']); return dict(candidates=self.results)
        if op == 'profile': return dict(usernames=[self.username])
        if op == 'clear_search': return dict(cleared=True)
        if op in ('open','self'): return dict(chat=self.chat.copy())
        if op == 'prepare':
            if self.draft: raise CommandError('Есть существующий черновик.')
            self.draft = args['text']; return dict(baseline=['old-message'])
        if op == 'cleanup':
            if self.draft == args['text']: self.draft = ''
            return dict(cleared=not self.draft)
        if op == 'send':
            assert args['confirmed'] is True
            assert self.draft == args['text'] and args['chat'] == self.chat
            self.sent += 1; self.draft = ''; return dict(requested=True)
        if op == 'verify': return dict(verified=self.verified)
        raise AssertionError(op)


@pytest.fixture
def setup(tmp_path):
    fake = FakeTelegram(); agent = DesktopAgent(tmp_path)
    agent.telegram = TelegramMessages(fake.call, fake.launch)
    async def forbidden(*args, **kwargs): raise AssertionError('Messaging must not call Ollama')
    agent.plan = agent.describe = forbidden
    return agent, fake


async def collect(agent, text, *, session='s', decision=False, on_approval=None):
    events = []
    async for event in agent.run(text, session, []):
        events.append(event)
        if event['type'] == 'approval':
            if on_approval: on_approval(event)
            else: agent.approve(event['nonce'], decision)
    return events


def answer(events): return ''.join(e['text'] for e in events if e['type'] == 'delta')


def test_approved_send_and_no_model(setup):
    agent, fake = setup
    events = asyncio.run(collect(agent, 'Напиши Насте привет', decision=True))
    assert fake.sent == 1 and answer(events) == 'Отправила Насте.'
    approval = next(e for e in events if e['type'] == 'approval')
    assert approval['text'] == 'привет' and 'Насте' in approval['label']
    assert fake.calls.index('prepare') < fake.calls.index('send') < fake.calls.index('verify')
    assert not agent.pending and not agent.telegram.pending_messages


@pytest.mark.parametrize('decision', [False, 'stop', 'timeout'])
def test_draft_never_sends_without_approval_and_cleans_up(setup, decision):
    agent, fake = setup
    def approve(event):
        assert fake.draft == 'привет' and fake.sent == 0
        if decision == 'stop': agent.stop()
        elif decision == 'timeout': agent.pending['expires'] = 0
        else: agent.approve(event['nonce'], False)
    events = asyncio.run(collect(agent, 'Напиши Насте привет', on_approval=approve))
    assert fake.sent == 0 and fake.draft == '' and 'send' not in fake.calls
    assert 'не отправляла' in answer(events)


def test_preexisting_draft_is_never_erased_even_if_identical(setup):
    agent, fake = setup; fake.draft = 'привет'
    events = asyncio.run(collect(agent, 'Напиши Насте привет', decision=True))
    assert fake.draft == 'привет' and fake.sent == 0 and 'cleanup' not in fake.calls
    assert not any(e['type'] == 'approval' for e in events)


@pytest.mark.parametrize('count', [0,2])
def test_no_guess_for_missing_or_ambiguous_recipients(setup, count):
    agent, fake = setup
    fake.results = [dict(id=str(i), title='Настя '+str(i)) for i in range(count)]
    asyncio.run(collect(agent, 'Напиши Насте привет', decision=True))
    assert fake.sent == 0 and 'open' not in fake.calls and 'prepare' not in fake.calls
    item = agent.telegram.pending_messages['s']
    assert item.status == 'awaiting_recipient' and item.text == 'привет'
    fake.results = [dict(id='b', title='Настя Иванова')]; fake.chat['title'] = 'Настя Иванова'
    events = asyncio.run(collect(agent, 'Настя Иванова', decision=True))
    assert fake.sent == 1 and 'Отправила' in answer(events)


def test_two_turn_context_and_literal_body(setup):
    agent, fake = setup
    events = asyncio.run(collect(agent, 'Напиши Насте'))
    assert answer(events) == 'Что написать Насте?' and not fake.calls
    events = asyncio.run(collect(agent, 'Привет, я задержусь на час', decision=True))
    assert next(e['text'] for e in events if e['type'] == 'approval') == 'Привет, я задержусь на час'
    assert fake.sent == 1
    asyncio.run(collect(agent, 'Ответь ей, что буду позже', decision=True))
    assert fake.sent == 2


def test_context_is_isolated_and_expires(setup):
    agent, fake = setup
    asyncio.run(collect(agent, 'Напиши Насте привет', decision=True))
    events = asyncio.run(collect(agent, 'Ответь ей, что буду позже', session='other'))
    assert 'Кому' in answer(events) and fake.sent == 1
    agent.telegram.context['s'].expires = 0
    events = asyncio.run(collect(agent, 'Ответь ей, что буду позже'))
    assert 'Кому' in answer(events) and fake.sent == 1


def test_cancel_between_turns_and_reject_nonce_replay(setup):
    agent, fake = setup
    asyncio.run(collect(agent, 'Напиши Насте'))
    assert agent.telegram.cancelling('Пятница, отмена', 's')
    events = asyncio.run(collect(agent, 'отмена'))
    assert not agent.telegram.pending_messages and not fake.sent
    events = asyncio.run(collect(agent, 'Напиши Насте привет', decision=True))
    nonce = next(e['nonce'] for e in events if e['type'] == 'approval')
    with pytest.raises(CommandError): agent.approve(nonce, True)
    assert fake.sent == 1


def test_username_is_verified_in_profile_and_reused_for_context(setup):
    agent, fake = setup
    events = asyncio.run(collect(agent,'Напиши @test_recipient: привет',decision=True))
    assert fake.sent == 1 and fake.calls.count('open') == 1
    assert 'profile' in fake.calls
    assert '@test_recipient' in next(e['window'] for e in events if e['type']=='approval')
    asyncio.run(collect(agent,'Ответь Насте, что буду позже',decision=True))
    assert fake.sent == 2 and fake.queries == ['@test_recipient','@test_recipient']


def test_wrong_profile_username_never_gets_draft_or_confirmation(setup):
    agent, fake = setup; fake.username = '@someone_else'
    events = asyncio.run(collect(agent,'Напиши @test_recipient: привет',decision=True))
    assert not fake.sent and 'prepare' not in fake.calls
    assert not any(e['type']=='approval' for e in events)


def test_duplicate_provider_ids_are_not_silently_collapsed(setup):
    agent, fake = setup; fake.results *= 2
    events = asyncio.run(collect(agent,'Напиши Насте привет',decision=True))
    assert 'несколько' in answer(events) and not fake.sent and 'open' not in fake.calls


def test_changed_chat_after_approval_cannot_send(setup):
    agent, fake = setup
    def change(event):
        fake.fail = 'send'; agent.approve(event['nonce'], True)
    events = asyncio.run(collect(agent, 'Напиши Насте привет', on_approval=change))
    assert fake.sent == 0 and fake.calls.count('send') == 1
    assert 'Отправила' not in answer(events)


def test_uncertain_send_is_not_retried(setup):
    agent, fake = setup; fake.fail = 'verify'
    events = asyncio.run(collect(agent, 'Напиши Насте привет', decision=True))
    assert fake.sent == 1 and fake.calls.count('send') == 1
    assert 'не подтверждён' in answer(events) and 'Отправила' not in answer(events)


def test_stop_during_provider_operation(setup):
    agent, fake = setup; fake.delay = 'search'
    async def run():
        task = asyncio.create_task(collect(agent, 'Напиши Насте привет', decision=True))
        while 'search' not in fake.calls: await asyncio.sleep(.01)
        started = time.monotonic(); agent.stop(); events = await task
        assert time.monotonic() - started < 1
        return events
    events = asyncio.run(run())
    assert not fake.sent and 'Открыт' not in answer(events)


def test_aborted_stream_signals_worker_cancellation(setup):
    agent, fake = setup; fake.delay = 'search'
    async def run():
        task = asyncio.create_task(collect(agent,'Напиши Насте привет',decision=True))
        while 'search' not in fake.calls: await asyncio.sleep(.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError): await task
        assert agent.cancel.is_set() and not agent.running
    asyncio.run(run())
    assert not fake.sent


def test_worker_refuses_unapproved_send_before_touching_ui():
    ui = object.__new__(TelegramUI)
    with pytest.raises(ValueError, match='подтверждения'): ui.run('send', dict(confirmed=False))


class Cell:
    ControlTypeName = 'DataItemControl'
    def __init__(self, name, text): self.Name = name; self.Value = text
    def GetPattern(self, _): return self


class Row:
    def __init__(self, rid, text, receipt):
        self.rid = rid; self.children = [Cell('Сообщение', text), Cell('Получение', receipt)]
    def GetChildren(self): return self.children
    def GetRuntimeId(self): return [self.rid]


@pytest.mark.parametrize('receipt,saved,expected', [
    ('Отправлено',False,True), ('Отправляется',False,False),
    ('Ошибка',False,False), ('Получено',False,False), ('Получено',True,True),
])
def test_history_requires_new_matching_message_and_delivery(receipt,saved,expected):
    from telegram_uia_worker import identity
    ui = object.__new__(TelegramUI); ui.check = lambda: None
    row = Row(1,'literal body',receipt)
    class History:
        def GetChildren(self): return [row]
    history = History()
    assert ui.matching(history,'literal body',saved=saved)[0]['sent'] == expected
    assert not ui.matching(history,'different body',saved=saved)
    ui.state = lambda expected: (None, Cell('composer',''), history)
    args = dict(chat={'title':'Избранное' if saved else 'Настя','self_chat':saved},text='literal body',baseline=[])
    assert ui.run('verify',args)['verified'] == expected
    args['baseline'] = [identity(row)]
    assert not ui.run('verify',args)['verified'], 'An old identical message is not proof of a new send'


def test_same_title_other_chat_identity_is_rejected():
    ui = object.__new__(TelegramUI)
    ui.guard = lambda: {'title':'Настя'}
    ui.composer = lambda: Row(1,'','')
    ui.history = lambda: Row(2,'','')
    with pytest.raises(ValueError,match='изменились'):
        ui.state(dict(title='Настя',composer='old-composer',history='other-chat'))


def test_body_edited_after_confirmation_cannot_invoke_send():
    ui = object.__new__(TelegramUI)
    ui.state = lambda expected: (None, Cell('composer','user edited this'), None)
    ui.invoke = lambda control: pytest.fail('Must not invoke Send')
    with pytest.raises(ValueError,match='Черновик изменился'):
        ui.run('send',dict(confirmed=True,chat={},text='original'))


def test_saved_messages_uses_semantic_uia_type_without_foreground(monkeypatch):
    import telegram_uia_worker as worker
    ui=object.__new__(TelegramUI); ui.window={}; ui.check=lambda:None
    row=Row(7,'',''); row.children=[Cell('Тип','Избранное'),Cell('Название','Account display name')]
    class Chats:
        def GetChildren(self):return [row]
    ui.chat_list=lambda:Chats(); invoked=[]; ui.invoke=lambda c:invoked.append(c)
    ui.guard=lambda:{'title':'\u200eИзбранное – (42)'}
    ui.state=lambda:(dict(title='Избранное'),None,None)
    monkeypatch.setattr(worker.time,'sleep',lambda _:None)
    monkeypatch.setattr(worker.native,'focus',lambda *a:pytest.fail('UIA must work without foreground'))
    monkeypatch.setattr(worker.auto,'SendKeys',lambda *a,**kw:pytest.fail('No global keys'))
    assert ui.run('self',{})['chat']['self_chat'] is True and invoked==[row]


def test_contact_named_saved_messages_is_not_self_receipt_proof():
    ui=object.__new__(TelegramUI);ui.check=lambda:None
    row=Row(1,'hello','Получено')
    class History:
        def GetChildren(self):return [row]
    ui.state=lambda expected:(None,Cell('composer',''),History())
    assert not ui.run('verify',dict(chat={'title':'Избранное'},text='hello',baseline=[]))['verified']


@pytest.mark.parametrize('text,final,pending,expected', [
    ('пятница стоп',False,False,True), ('отмена',True,True,True),
    ('нет',True,True,True), ('нет',False,True,False), ('нет',True,False,False),
    ('отправь сообщение нет',True,True,False), ('да',True,True,False),
])
def test_voice_cancellation(text,final,pending,expected):
    assert confirmation_stop(text,final,pending) == expected


def test_debug_does_not_contain_private_body(monkeypatch,capsys):
    from desktop_trace import trace
    monkeypatch.setenv('FRIDAY_DEBUG','1')
    trace('TELEGRAM', text='secret password qwerty123', recipient='PrivateName', message_length=29, intent='telegram_send_message')
    output = capsys.readouterr().err
    assert 'qwerty123' not in output and 'PrivateName' not in output and 'secret' not in output
    assert 'message_length' in output and 'telegram_send_message' in output
