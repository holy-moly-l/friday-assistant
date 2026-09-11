import io
import json
from pathlib import Path
import time
import httpx
import soundfile as sf

root=Path(__file__).resolve().parents[1]
for _ in range(60):
    try:
        runtime=json.loads((root/'data/runtime.json').read_text(encoding='utf8'))
        client=httpx.Client(base_url=f"http://127.0.0.1:{runtime['port']}",headers={'X-Friday-Token':runtime['token']},timeout=240,trust_env=False)
        if all(v=='ready' for v in client.get('/api/health').json()['services'].values()):break
    except (httpx.HTTPError,OSError):pass
    time.sleep(1)
else:raise RuntimeError('Models did not start')
results=[]
for voice in ['qwen-serena','qwen-anna']:
    started=time.perf_counter()
    result=client.post('/api/speech',json={'text':'Привет! Все системы готовы.','speaker':voice})
    result.raise_for_status()
    (root/'data'/f'{voice}-verified.wav').write_bytes(result.content)
    audio,sr=sf.read(io.BytesIO(result.content))
    recognized=client.post('/api/transcribe',files={'audio':('test.wav',result.content,'audio/wav')})
    recognized.raise_for_status()
    transcript=recognized.json()['text']
    entry={'voice':voice,'seconds':round(time.perf_counter()-started,2),'audio_seconds':round(len(audio)/sr,2),'transcript':transcript}
    print(json.dumps(entry,ensure_ascii=False),flush=True)
    assert 'готов' in transcript.lower(),entry
    results.append(entry)
(root/'data/voice-upgrade-verification.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf8')
print('ALL ADDITIONAL VOICES PASS',flush=True)
