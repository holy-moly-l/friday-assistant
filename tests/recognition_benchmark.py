"""Controlled synthetic corpus, not a claim about the user's real microphone."""
import json,re,sys,time
from pathlib import Path
import numpy as np
root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root/'backend'))
import app
import recognition
import torch
from faster_whisper import WhisperModel
torch.set_num_threads(4)
tts=torch.package.PackageImporter(str(root/'models/silero-v4-ru.pt')).load_pickle('tts_models','model')
phrases=['Пятница, открой Дискорд.','Перенеси это окно на второй монитор и разверни его.',
 'Сделай громкость тридцать процентов.','Не закрывай Телеграм, сверни только калькулятор.',
 'Запиши заметку: завтра в пятнадцать тридцать позвонить Алексею.','Пятница, что за ошибка появилась на экране?']
corpus=[];rng=np.random.default_rng(8)
for index,text in enumerate(phrases):
    audio=tts.apply_tts(text=text,speaker='xenia' if index%2==0 else 'baya',sample_rate=48000,put_accent=True,put_yo=True).numpy()[::3]
    for condition,gain,noise in [('clean',1,0),('quiet',.06,.0006)]:
        sample=np.concatenate([np.zeros(8000),audio*gain+rng.normal(0,noise,len(audio)),np.zeros(20000)]).astype(np.float32)
        corpus.append((text,condition,sample))
del tts
app.load_whisper();assert app.state['stt']=='ready',app.state
print('DEVICE',app.stt_device,flush=True)
def words(text):
    text=text.lower().replace('ё','е').replace('дискорд','discord').replace('телеграм','telegram')
    for word,n in [('пятнадцать','15'),('тридцать','30')]:text=text.replace(word,n)
    return re.findall(r'\w+',text)
def distance(a,b):
    row=list(range(len(b)+1))
    for i,x in enumerate(a):
        next_row=[i+1]
        for j,y in enumerate(b):next_row.append(min(row[j+1]+1,next_row[j]+1,row[j]+(x!=y)))
        row=next_row
    return row[-1]
results=[]
small=WhisperModel(str(root/'models/whisper-small'),device=app.stt_device,compute_type='float16' if app.stt_device=='cuda' else 'int8',local_files_only=True)
for reference,condition,audio in corpus:
    start=time.perf_counter();segments,_=small.transcribe(audio,language='ru',beam_size=3,vad_filter=True,condition_on_previous_text=False)
    old=' '.join(s.text.strip() for s in segments if s.no_speech_prob<.7)
    results.append(dict(reference=reference,condition=condition,old=old,old_seconds=round(time.perf_counter()-start,2),old_errors=distance(words(reference),words(old))))
small.model.unload_model();del small
if app.stt_device=='cuda':app.whisper_model.model.load_model()
for row,(_,_,audio) in zip(results,corpus):
    start=time.perf_counter();result=recognition.transcribe(app.whisper_model,audio)
    row.update(new=result['text'],new_seconds=round(time.perf_counter()-start,2),new_errors=distance(words(row['reference']),words(result['text'])),uncertain=result['uncertain'])
    print(json.dumps(row,ensure_ascii=False),flush=True)
for sample in [np.zeros(32000,dtype=np.float32),rng.normal(0,.00001,32000).astype(np.float32)]:
    assert recognition.transcribe(app.whisper_model,sample)['text']==''
if app.stt_device=='cuda':app.whisper_model.model.unload_model(to_cpu=True)
report={'synthetic_only':True,'old_errors':sum(r['old_errors'] for r in results),'new_errors':sum(r['new_errors'] for r in results),'reference_words':sum(len(words(r['reference'])) for r in results),'samples':results}
(root/'data/recognition-benchmark.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print('RESULT',json.dumps({k:v for k,v in report.items() if k!='samples'}),flush=True)
