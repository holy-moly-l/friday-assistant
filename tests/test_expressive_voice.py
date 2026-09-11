import hashlib,queue,sys,threading,time
from pathlib import Path
from unittest.mock import Mock
import pytest
sys.path.insert(0,str(Path(__file__).parents[1]/'backend'))
from expressive_voice import ExpressiveVoice,VoiceCancelled,PREVIEW_TEXT

def test_cancel_stops_active_worker_without_waiting_for_synthesis(tmp_path):
    voice=ExpressiveVoice(tmp_path);voice.messages=queue.Queue()
    process=Mock();process.poll.return_value=None;voice.process=process
    cancel=threading.Event();cancel.set()
    with pytest.raises(VoiceCancelled):voice._receive(180,cancel)
    process.terminate.assert_called_once()
    assert voice.process is None

def test_cancelled_waiter_does_not_stop_another_job(tmp_path):
    voice=ExpressiveVoice(tmp_path);voice.lock.acquire()
    voice.close=Mock();cancel=threading.Event();cancel.set()
    try:
        with pytest.raises(VoiceCancelled):voice.synthesize('text','Serena',cancel)
        assert voice.lock.locked()
        voice.close.assert_not_called()
    finally:voice.lock.release()

def test_worker_timeout_releases_process(tmp_path):
    voice=ExpressiveVoice(tmp_path);voice.messages=queue.Queue();voice.close=Mock()
    with pytest.raises(RuntimeError,match='слишком много времени'):voice._receive(.01)
    voice.close.assert_called_once()

def test_prepared_preview_needs_no_cuda_worker(tmp_path):
    voice=ExpressiveVoice(tmp_path);voice.start=Mock(side_effect=AssertionError('Should not load CUDA'))
    key=hashlib.sha256(('v2|Serena|'+PREVIEW_TEXT).encode()).hexdigest()
    target=tmp_path/'data/voice-previews'/f'{key}.wav';target.parent.mkdir(parents=True)
    target.write_bytes(b'RIFF'+bytes(1000))
    assert voice.synthesize(PREVIEW_TEXT,'Serena',preview=True)==target.read_bytes()

def test_cancel_before_lock_never_starts_model_and_unlocks(tmp_path):
    voice=ExpressiveVoice(tmp_path);voice.start=Mock();cancel=threading.Event();cancel.set()
    with pytest.raises(VoiceCancelled):voice.synthesize('text','Serena',cancel)
    voice.start.assert_not_called();assert not voice.lock.locked()
