from pathlib import Path
import numpy as np
import soundfile as sf
import torch
root=Path(__file__).resolve().parents[1]
torch.set_num_threads(4)
model=torch.package.PackageImporter(str(root/'models/silero-v4-ru.pt')).load_pickle('tts_models','model')
for name,text in [('command','Пятница, который час?'),('wake','Пятница!'),('plain','Который час?'),('ambient','Сегодня пятница. Завтра выходной.'),('cancel','Отмена.')]:
    audio=model.apply_tts(text=text,speaker='xenia',sample_rate=48000,put_accent=True,put_yo=True).numpy()
    # Decimation is only for controlled speech fixtures; live capture is resampled by Web Audio.
    audio=audio[::3]
    sf.write(root/f'data/wake-{name}.wav',np.concatenate([np.zeros(16000),audio,np.zeros(16000*2)]),16000)
combined,sr=sf.read(root/'data/wake-command.wav')
sf.write(root/'data/wake-minimized.wav',np.concatenate([np.zeros(16000*5),combined,np.zeros(16000*8)]),sr)
print('Generated synthetic wake/command/ambient/cancel audio. No microphone was recorded.')
