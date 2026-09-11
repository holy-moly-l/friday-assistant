from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).parents[1]/'backend'))
import pytest
from wake_word import WakeSession,after_wake

@pytest.mark.parametrize('text,expected',[
    ('Пятница, открой проводник','открой проводник'),('Пятница!',''),
    ('Пятница?',''),('Пятница…',''),('Пятница? Который час?','Который час?'),
    ('Привет, Пятница, который час?','который час?'),('эй пятница включи звук','включи звук'),
    ('Сегодня пятница',None),('на пятницу запланирована встреча',None),
    ('Открой проводник',None),('Пятницами',None),
])
def test_only_address_at_start(text,expected):assert after_wake(text)==expected

class Recognizer:
    def Reset(self):pass
    def AcceptWaveform(self,data):return False
    def PartialResult(self):return '{"partial":""}'

def test_silence_never_activates_and_memory_is_bounded():
    detector=WakeSession(Recognizer());timeouts=0
    for _ in range(1000):
        event=detector.feed(bytes(3200))
        if event:assert event['type']=='timeout';timeouts+=1
        assert len(detector.audio)<=16000*2*20
    assert timeouts>0

def test_wait_for_command_expires():
    detector=WakeSession(Recognizer());detector.reset(armed=True)
    events=[detector.feed(bytes(3200)) for _ in range(85)]
    assert any(e and e['type']=='timeout' for e in events)
    assert not detector.armed

@pytest.mark.parametrize('pcm',[b'',b'1',bytes(20000)],ids=['empty','odd','oversized'])
def test_invalid_audio_rejected(pcm):
    with pytest.raises(ValueError):WakeSession(Recognizer()).feed(pcm)

def test_wake_websocket_authentication():
    from fastapi.testclient import TestClient
    from starlette.websockets import WebSocketDisconnect
    import app
    client=TestClient(app.app)
    for origin,token in [('https://example.com',app.TOKEN),(f'http://127.0.0.1:{app.PORT}','incorrect')]:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect('/api/wake',headers={'origin':origin}) as socket:
                socket.send_json({'token':token,'sample_rate':16000});socket.receive_json()
