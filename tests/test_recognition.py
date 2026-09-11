from pathlib import Path
import sys
from types import SimpleNamespace as Segment
import numpy as np
import pytest
sys.path.insert(0,str(Path(__file__).parents[1]/'backend'))
from recognition import prepare_audio,transcribe
from wake_word import WakeSession

def test_silence_is_not_sent_to_model():
    class Model:
        def transcribe(self,*args,**kwargs):pytest.fail('Do not hallucinate on silence')
    assert transcribe(Model(),np.zeros(16000))['text']==''

def test_audio_diagnostics_and_bounded_gain():
    audio=np.sin(np.arange(16000)/10).astype(np.float32)*.001
    normalized,quality=prepare_audio(audio)
    assert quality['warning'] and np.max(np.abs(normalized))<=.00401
    _,clipped=prepare_audio(np.ones(16000,dtype=np.float32))
    assert 'перегружен' in clipped['warning']

def test_confident_quiet_segment_is_not_discarded():
    class Model:
        def transcribe(self,*args,**kwargs):
            assert kwargs['beam_size']==5 and kwargs['temperature']==0
            return iter([Segment(text=' Не закрывай окно.',no_speech_prob=.8,avg_logprob=-.2,compression_ratio=1)]),None
    result=transcribe(Model(),np.ones(16000,dtype=np.float32)*.1+np.sin(np.arange(16000))*.01)
    assert result['text']=='Не закрывай окно.' and not result['uncertain']

def test_uncertain_segment_is_flagged_for_review():
    class Model:
        def transcribe(self,*args,**kwargs):return iter([Segment(text='открой',no_speech_prob=.1,avg_logprob=-1.5,compression_ratio=1)]),None
    assert transcribe(Model(),np.sin(np.arange(16000))*.1)['uncertain']

def test_wake_keeps_command_across_short_pause():
    import json
    class Recognizer:
        def Reset(self):pass
        def AcceptWaveform(self,pcm):return True
        def Result(self):return json.dumps({'text':'пятница открой калькулятор'})
    detector=WakeSession(Recognizer())
    speech=(np.ones(1600)*3000).astype('<i2').tobytes()
    detector.feed(speech)
    for _ in range(8):assert detector.feed(bytes(3200)) is None
    assert detector.feed(speech) is None
    found=[]
    for _ in range(13):
        event=detector.feed(bytes(3200))
        if event:found.append(event)
    assert len(found)==1 and len(found[0]['audio'])>=3200*22
