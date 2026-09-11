"""Shared Russian transcription for recordings and wake-word commands."""
import numpy as np

MODEL_FOLDER='whisper-large-v3-turbo'
MODEL_LABEL='Whisper Large v3 Turbo'
HOTWORDS='Пятница, Telegram, Телеграм, Discord, Дискорд, браузер, калькулятор, монитор, громкость, проводник, блокнот.'

def prepare_audio(audio):
    samples=np.asarray(audio,dtype=np.float32)
    if samples.ndim!=1 or not np.isfinite(samples).all():raise ValueError('Некорректная запись микрофона.')
    if len(samples)==0:return samples,{'dbfs':-100.0,'clipping':0.0,'warning':'Запись пустая.'}
    rms=float(np.sqrt(np.mean(samples*samples)))
    dbfs=round(20*np.log10(max(rms,1e-5)),1)
    clipping=float(np.mean(np.abs(samples)>=.995))
    warning=''
    if clipping>.01:warning='Микрофон перегружен: уменьшите его усиление.'
    elif dbfs<-42:warning='Очень тихая запись. Проверьте выбранный микрофон и расстояние до него.'
    # Limited gain only, without amplification of near-silence or additional denoising.
    samples=samples-float(np.mean(samples))
    peak=float(np.max(np.abs(samples)))
    if rms>.0002 and peak>0:samples=samples*min(4.0,.85/peak, max(1.0,.06/max(rms,1e-6)))
    return samples,{'dbfs':dbfs,'clipping':round(clipping,4),'warning':warning}

def transcribe(model,audio):
    samples,quality=prepare_audio(audio)
    if len(samples)<1600 or float(np.max(np.abs(samples),initial=0))<.0001:
        return {'text':'','language':'ru','uncertain':True,**quality}
    segments,_=model.transcribe(samples,language='ru',task='transcribe',beam_size=5,
        temperature=0.0,vad_filter=True,
        vad_parameters={'threshold':.35,'min_speech_duration_ms':120,'min_silence_duration_ms':700,'speech_pad_ms':450},
        condition_on_previous_text=False,hotwords=HOTWORDS,
        initial_prompt='Русская речь. Названия программ могут быть на русском или английском.',
        no_speech_threshold=.6,log_prob_threshold=-1.0,compression_ratio_threshold=2.4)
    accepted=[];uncertain=False
    for segment in segments:
        # Whisper's no-speech probability alone must not discard confident, quiet speech.
        if segment.no_speech_prob>.6 and segment.avg_logprob<-1.0:continue
        if not segment.text.strip():continue
        accepted.append(segment.text.strip())
        uncertain|=segment.avg_logprob<-1.0 or segment.compression_ratio>2.4
    text=' '.join(accepted).strip()
    return {'text':text,'language':'ru','uncertain':bool(uncertain or not text),**quality}
