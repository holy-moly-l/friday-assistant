from pathlib import Path
import httpx
import json
root=Path(__file__).resolve().parents[1]
runtime=json.loads((root/'data/runtime.json').read_text())
with httpx.Client(base_url=f"http://127.0.0.1:{runtime['port']}",headers={'X-Friday-Token':runtime['token']},timeout=30,trust_env=False) as client:
    sid=client.post('/api/sessions').json()['id']
    try:
        for command in ['Пятница, можешь открыть мне проводник, пожалуйста?', 'Какая громкость?', 'Сколько места на диске?', 'Открой приложение friday-smoke-nonexistent']:
            response=client.post('/api/chat',json={'session_id':sid,'text':command});response.raise_for_status()
            events=[json.loads(line) for line in response.text.splitlines()]
            assert not any(e['type']=='error' for e in events),events
            text=''.join(e['text'] for e in events if e['type']=='delta')
            assert text
            print(command,'=>',text)
    finally:client.delete('/api/sessions/'+sid).raise_for_status()
