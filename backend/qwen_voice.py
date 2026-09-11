"""Isolated CUDA speech worker. JSON lines on stdio, no listening network port."""
import contextlib
import json
import os
from pathlib import Path
import sys
import traceback
import time
from lifecycle import follow_parent

ROOT=Path(__file__).resolve().parents[1]
os.environ['HF_HUB_OFFLINE']='1'
os.environ['TRANSFORMERS_OFFLINE']='1'
os.environ['TOKENIZERS_PARALLELISM']='false'

# The desktop launcher can terminate its Python service. Follow that parent so CUDA memory is released too.
follow_parent(os.environ.get('FRIDAY_PARENT_PID'))

def emit(payload):
    print(json.dumps(payload,ensure_ascii=False),flush=True)

try:
    with contextlib.redirect_stdout(sys.stderr):
        import torch
        import soundfile as sf
        from faster_qwen3_tts import FasterQwen3TTS
        # Small autoregressive CUDA steps suffer from CPU thread-pool overhead.
        torch.set_num_threads(1)
        torch.set_num_interop_threads(1)
        model=FasterQwen3TTS.from_pretrained(str(ROOT/'models/qwen3-tts'),device='cuda:0',dtype=torch.bfloat16,attn_implementation='sdpa',max_seq_len=1024)
    emit({'ready':True})
except Exception as exc:
    traceback.print_exc(file=sys.stderr)
    emit({'error':str(exc)})
    sys.exit(1)

for line in sys.stdin:
    try:
        job=json.loads(line)
        destination=Path(job['output']).resolve()
        if not destination.is_relative_to((ROOT/'data').resolve()):raise ValueError('Invalid output directory')
        with contextlib.redirect_stdout(sys.stderr):
            started=time.perf_counter()
            waves,sr=model.generate_custom_voice(text=job['text'],language='Russian',speaker=job['speaker'],max_new_tokens=600)
            sf.write(str(destination),waves[0],sr,subtype='PCM_16')
            print(f"Speech completed: {job['speaker']}, {len(job['text'])} chars, {time.perf_counter()-started:.2f}s",file=sys.stderr,flush=True)
        emit({'ok':True,'sample_rate':sr,'seconds':len(waves[0])/sr})
    except Exception as exc:
        traceback.print_exc(file=sys.stderr)
        emit({'error':str(exc)})
