"""Real-model round trip. No cloud calls or microphone recording."""
import io
import json
from pathlib import Path
import time
import httpx
import numpy as np
import soundfile as sf

root = Path(__file__).resolve().parents[1]
runtime = json.loads((root / 'data/runtime.json').read_text())
client = httpx.Client(base_url=f"http://127.0.0.1:{runtime['port']}", headers={'X-Friday-Token':runtime['token']}, timeout=180, trust_env=False)
health = client.get('/api/health').json()
assert all(s == 'ready' for s in health['services'].values()), health
stats = {}
phrase = 'Привет, Пятница. Расскажи, что ты умеешь.'
t=time.perf_counter()
voice=client.post('/api/speech', json={'text':phrase,'speaker':'xenia'})
voice.raise_for_status()
stats['tts_seconds']=round(time.perf_counter()-t,2)
audio, sr = sf.read(io.BytesIO(voice.content))
assert sr == 48000 and len(audio)>sr and np.max(np.abs(audio))>.01
(root/'data/voice-sample.wav').write_bytes(voice.content)
stats['audio_duration']=round(len(audio)/sr,2)
t=time.perf_counter()
stt=client.post('/api/transcribe', files={'audio':('test.wav',voice.content,'audio/wav')})
stt.raise_for_status()
stats['stt_seconds']=round(time.perf_counter()-t,2)
recognized=stt.json()['text']
assert 'пятниц' in recognized.lower() and 'умеешь' in recognized.lower(), recognized
stats['transcript']=recognized
# VAD must not invent a command during silence.
silence=io.BytesIO();sf.write(silence,np.zeros(48000*3),48000,format='WAV')
assert client.post('/api/transcribe',files={'audio':('silence.wav',silence.getvalue(),'audio/wav')}).json()['text']==''
sid=client.post('/api/sessions').json()['id']
t=time.perf_counter()
answer=''; first=None
with client.stream('POST','/api/chat',json={'session_id':sid,'text':recognized}) as response:
    response.raise_for_status()
    for line in response.iter_lines():
        data=json.loads(line)
        assert data['type']!='error', data
        if data['type']=='delta':
            if first is None: first=time.perf_counter()-t
            answer+=data['text']
stats['first_token_seconds']=round(first,2)
stats['reply_seconds']=round(time.perf_counter()-t,2)
stats['reply']=answer
assert len(answer)>30 and any(c in answer.lower() for c in 'яюэы')
t=time.perf_counter()
spoken_reply=client.post('/api/speech',json={'text':answer,'speaker':'xenia'})
spoken_reply.raise_for_status()
stats['reply_tts_seconds']=round(time.perf_counter()-t,2)
for speaker in ['baya','kseniya']:
    result=client.post('/api/speech',json={'text':'Все системы готовы.','speaker':speaker})
    result.raise_for_status()
    assert len(result.content)>10000
client.delete('/api/sessions/'+sid).raise_for_status()
(root/'data/verification.json').write_text(json.dumps(stats,ensure_ascii=False,indent=2),encoding='utf8')
print(json.dumps(stats,ensure_ascii=False,indent=2))
print('REAL MODELS PASS: TTS -> STT -> streamed LLM; 3 voices; silence rejected')
