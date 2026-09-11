import os,time,sys
from pathlib import Path
root=Path(__file__).resolve().parents[1]
os.environ.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1')
import torch,soundfile as sf
torch.set_num_threads(1);torch.set_num_interop_threads(1)
from faster_qwen3_tts import FasterQwen3TTS
t=time.monotonic()
model=FasterQwen3TTS.from_pretrained(str(root/'models/qwen3-tts'),device='cuda:0',dtype=torch.bfloat16,max_seq_len=1024)
print('LOADED',round(time.monotonic()-t,2),flush=True)
for i in range(2):
    t=time.monotonic()
    waves,sr=model.generate_custom_voice(text='Привет! Я Пятница. Чем могу помочь?',language='Russian',speaker='Serena',max_new_tokens=300)
    sf.write(str(root/f'data/voice-fast-{i}.wav'),waves[0],sr)
    print('GENERATED',i,round(time.monotonic()-t,2),'s',len(waves[0])/sr,'audio seconds',flush=True)
