import os
from pathlib import Path
import time
os.environ['HF_HUB_OFFLINE']='1'
os.environ['TRANSFORMERS_OFFLINE']='1'
import torch
import soundfile as sf
from qwen_tts import Qwen3TTSModel
root=Path(__file__).resolve().parents[1]
torch.set_num_threads(4)
started=time.perf_counter()
model=Qwen3TTSModel.from_pretrained(str(root/'models/qwen3-tts'),device_map='cuda:0',dtype=torch.bfloat16,attn_implementation='sdpa',local_files_only=True)
print('LOAD',round(time.perf_counter()-started,2),'VRAM GB',torch.cuda.memory_allocated()/1024**3,flush=True)
for voice in ['Serena','Sohee']:
    started=time.perf_counter()
    waves,sr=model.generate_custom_voice(text='Привет! Я Пятница. Теперь можно просто сказать, что нужно сделать, а я помогу.',language='Russian',speaker=voice,max_new_tokens=250,do_sample=False)
    sf.write(str(root/f'data/qwen-{voice.lower()}.wav'),waves[0],sr)
    print(voice,'TIME',round(time.perf_counter()-started,2),'DURATION',len(waves[0])/sr,flush=True)
