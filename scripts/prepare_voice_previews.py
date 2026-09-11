"""Prepare fixed, non-personal voice demos for instant offline playback."""
import sys,time
from pathlib import Path
root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root/'backend'))
from expressive_voice import ExpressiveVoice,PREVIEW_TEXT
voice=ExpressiveVoice(root)
try:
    for speaker in ['Serena','Sohee','Ono_Anna']:
        start=time.monotonic()
        data=voice.synthesize(PREVIEW_TEXT,speaker,preview=True)
        print(speaker,len(data),'bytes',round(time.monotonic()-start,2),'s',flush=True)
finally:voice.close()
