from pathlib import Path
import sys
import numpy as np
import soundfile as sf
import torch
root=Path(__file__).resolve().parents[1]
torch.set_num_threads(4)
model=torch.package.PackageImporter(str(root/'models/silero-v4-ru.pt')).load_pickle('tts_models','model')
audio=model.apply_tts(text='Пятница, стоп.',speaker='xenia',sample_rate=48000).numpy()
sf.write(root/'data/desktop-stop.wav',np.concatenate([np.zeros(48000*5),audio,np.zeros(48000*3)]),48000,subtype='PCM_16')
print('Stop sample created')
