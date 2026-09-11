"""Fetch the official model artifacts once; inference is fully local afterwards."""
import json
import hashlib
import os
import shutil
from pathlib import Path
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

ROOT = Path(__file__).resolve().parents[1]
MODELS = ROOT / 'models'
MODELS.mkdir(exist_ok=True)
os.environ['HF_HUB_DISABLE_SYMLINKS_WARNING'] = '1'

def llm():
    req = urllib.request.Request('http://127.0.0.1:11434/api/pull', data=json.dumps({'model': 'qwen3.5:4b', 'stream': True}).encode(), headers={'Content-Type':'application/json'})
    last = 0
    with urllib.request.urlopen(req, timeout=1200) as response:
        for line in response:
            event = json.loads(line)
            if event.get('error'): raise RuntimeError(event['error'])
            if time.time() - last > 10 or event.get('status') == 'success':
                print('LLM:', event.get('status'), round(event.get('completed', 0) / max(event.get('total', 1), 1) * 100), '%', flush=True)
                last = time.time()

def tts():
    dest = MODELS / 'silero-v4-ru.pt'
    if not dest.exists():
        print('Downloading Silero v4 Russian voice...', flush=True)
        from huggingface_hub import hf_hub_download
        source = hf_hub_download('Derur/silero-models', 'tts/ru/ru_v4/v4_ru.pt', revision='ab3dfc8')
        checksum = hashlib.sha256(Path(source).read_bytes()).hexdigest()
        if checksum != '896ab96347d5bd781ab97959d4fd6885620e5aab52405d3445626eb7c1414b00':
            raise RuntimeError('Silero model checksum mismatch')
        shutil.copyfile(source, str(dest) + '.partial')
        Path(str(dest) + '.partial').replace(dest)
    print('Silero ready:', dest.stat().st_size, flush=True)

def stt():
    from huggingface_hub import snapshot_download
    snapshot_download('mobiuslabsgmbh/faster-whisper-large-v3-turbo', local_dir=str(MODELS / 'whisper-large-v3-turbo'), allow_patterns=['*.json', '*.bin', '*.txt'])
    print('Whisper Large v3 Turbo ready', flush=True)

if __name__ == '__main__':
    with ThreadPoolExecutor(max_workers=3) as pool:
        jobs = [pool.submit(fn) for fn in (llm, tts, stt)]
        for job in jobs: job.result()
    print('ALL MODELS READY', flush=True)
