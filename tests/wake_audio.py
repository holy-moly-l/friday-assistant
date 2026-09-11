"""Real offline keyword recognition of synthetic speech, without recording a mic."""
from pathlib import Path
import sys,time
sys.path.insert(0,str(Path(__file__).parents[1]/'backend'))
import soundfile as sf
from wake_word import WakeService,WakeSession
root=Path(__file__).resolve().parents[1]
service=WakeService(root/'models')
for name,expected in [('command',True),('wake',True),('plain',False),('ambient',False)]:
    audio,sr=sf.read(root/f'data/wake-{name}.wav',dtype='int16');assert sr==16000
    detector=WakeSession(service.recognizer());events=[];start=time.perf_counter()
    pcm=audio.tobytes()
    for i in range(0,len(pcm),3200):
        event=detector.feed(pcm[i:i+3200])
        if event:events.append(event['type'])
    print(name,events,'seconds',round(time.perf_counter()-start,2),flush=True)
    assert ('segment' in events)==expected,(name,events)
print('REAL WAKE AUDIO PASS')
