import importlib.util
from pathlib import Path
from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient

spec = importlib.util.spec_from_file_location('friday', Path(__file__).parents[1] / 'backend' / 'app.py')
friday = importlib.util.module_from_spec(spec)
spec.loader.exec_module(friday)

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(friday, 'DB', tmp_path / 'test.db')
    friday.init_db()
    # No lifespan: unit tests do not load models or touch the user's history.
    return TestClient(friday.app, headers={'X-Friday-Token': friday.TOKEN})

def test_auth_and_origin(client):
    assert client.get('/api/sessions', headers={'X-Friday-Token': ''}).status_code == 401
    assert client.post('/api/sessions', headers={'origin':'https://evil.example'}).status_code == 403
    assert client.get('/api/health').status_code == 200


def test_messaging_routes_without_ollama_and_cancels_between_turns(client,monkeypatch,tmp_path):
    from desktop_agent import DesktopAgent
    agent=DesktopAgent(tmp_path)
    monkeypatch.setattr(friday,'desktop',agent)
    monkeypatch.setitem(friday.state,'llm','error')
    sid=client.post('/api/sessions').json()['id']
    response=client.post('/api/chat',json={'session_id':sid,'text':'Напиши Насте'})
    assert response.status_code==200 and 'Что написать Насте?' in response.text
    assert agent.telegram.pending_messages[sid].recipient=='Настя'
    response=client.post('/api/chat',json={'session_id':sid,'text':'отмена'})
    assert response.status_code==200 and not agent.telegram.pending_messages

def test_commands_cannot_inject_shell():
    assert friday.resolve_command('Открой калькулятор') == ('open', 'калькулятор')
    assert friday.resolve_command('Пятница, открой блокнот.') == ('open', 'блокнот')
    for text in ['Открой calc.exe & del C:\\', 'Расскажи про команду открой блокнот', 'Открой проводник; shutdown /s', 'запусти powershell', 'Не открывай блокнот']:
        assert friday.resolve_command(text) is None

def test_actual_launch_is_allowlisted():
    with patch.object(friday.subprocess, 'Popen') as popen:
        result, _ = friday.execute_command(('open','калькулятор'))
        assert 'Открываю' in result
        args, kwargs = popen.call_args
        assert len(args[0]) == 1 and args[0][0].endswith('calc.exe')
        assert kwargs['shell'] is False

def test_session_notes_and_deletion(client):
    sid = client.post('/api/sessions').json()['id']
    response = client.post('/api/chat', json={'session_id':sid,'text':'Запиши заметку: Купить чай'})
    assert response.status_code == 200
    assert 'Заметка сохранена' in response.text
    assert client.get('/api/notes').json()[0]['content'] == 'Купить чай'
    messages = client.get('/api/sessions/'+sid).json()['messages']
    assert [m['role'] for m in messages] == ['user','assistant']
    assert client.delete('/api/sessions/'+sid).status_code == 200
    assert client.get('/api/sessions/'+sid).status_code == 404
    with friday.connect() as db:
        assert db.execute('SELECT COUNT(*) FROM messages').fetchone()[0] == 0

def test_validation(client):
    assert client.post('/api/chat', json={'session_id':'missing','text':'Привет'}).status_code == 404
    assert client.post('/api/chat', json={'session_id':'missing','text':' '}).status_code == 422


def test_stop_bypasses_busy_chat_and_model_readiness(client,monkeypatch):
    stop=__import__('unittest.mock',fromlist=['Mock']).Mock()
    monkeypatch.setattr(friday.desktop,'stop',stop)
    monkeypatch.setattr(friday.chat_lock,'locked',lambda:True)
    response=client.post('/api/chat',json={'session_id':'stop-only','text':'Пятница, стоп'})
    assert response.status_code==200 and 'Остановлено' in response.text
    stop.assert_called_once()


def test_disabled_vision_explains_setting_even_when_model_offline(client,monkeypatch):
    monkeypatch.setattr(friday.desktop,'vision',False)
    monkeypatch.setitem(friday.state,'llm','error')
    sid=client.post('/api/sessions').json()['id']
    response=client.post('/api/chat',json={'session_id':sid,'text':'Что ты видишь?'})
    assert response.status_code==200 and 'Снимки экрана отключены' in response.text


def test_system_reports_selected_model(client,monkeypatch):
    monkeypatch.setattr(friday.desktop,'model','qwen3.5:2b')
    assert client.get('/api/health').json()['model']=='qwen3.5:2b'
    assert client.get('/api/system').json()['model']=='qwen3.5:2b'

def test_speech_guards(client, monkeypatch):
    monkeypatch.setitem(friday.state, 'tts', 'ready')
    assert client.post('/api/speech', json={'text':'привет','speaker':'unknown'}).status_code == 422
    assert client.post('/api/speech', json={'text':''}).status_code == 422

def test_empty_audio(client, monkeypatch):
    monkeypatch.setitem(friday.state, 'stt', 'ready')
    assert client.post('/api/transcribe', files={'audio':('x.webm', b'', 'audio/webm')}).status_code == 422

def test_invalid_audio(client, monkeypatch):
    monkeypatch.setitem(friday.state, 'stt', 'ready')
    assert client.post('/api/transcribe', files={'audio':('x.webm', b'garbage'*100, 'audio/webm')}).status_code == 422
