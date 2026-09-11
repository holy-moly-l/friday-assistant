"""Local streaming wake word detection. Ambient audio never goes to history/disk."""
import asyncio
import json
import re
import secrets
import threading
import numpy as np
from fastapi import WebSocket, WebSocketDisconnect

SAMPLE_RATE=16000
WAKE=re.compile(r'^\s*(?:(?:эй|привет)[\s,!?…;.]+)?пятница\b[\s,!?…;.:—-]*',re.I)
def after_wake(text):
    match=WAKE.match(text)
    return text[match.end():].strip() if match else None

class WakeSession:
    """One recognizer per microphone connection; maximum 20 s in-memory audio."""
    def __init__(self,recognizer):
        self.recognizer=recognizer
        self.reset()

    def reset(self,armed=False):
        self.recognizer.Reset()
        self.audio=bytearray()
        self.armed=armed
        self.notified=armed
        self.silence=0
        self.pending_segment=False

    def feed(self,pcm):
        if not pcm or len(pcm)%2 or len(pcm)>12800:raise ValueError('Invalid PCM frame')
        self.audio.extend(pcm)
        samples=np.frombuffer(pcm,dtype='<i2').astype(np.float32)/32768
        rms=float(np.sqrt(np.mean(samples*samples)))
        self.silence=self.silence+len(samples) if rms<.006 else 0
        if self.pending_segment and self.silence>=SAMPLE_RATE*1.2:
            audio=bytes(self.audio);require_wake=not self.armed;self.reset()
            return {'type':'segment','audio':audio,'require_wake':require_wake}
        if len(self.audio)>SAMPLE_RATE*2*20:
            self.reset();return {'type':'timeout'}
        if self.armed and self.silence>SAMPLE_RATE*8:
            self.reset();return {'type':'timeout'}
        if self.recognizer.AcceptWaveform(pcm):
            text=json.loads(self.recognizer.Result()).get('text','')
            if self.armed and text:
                self.pending_segment=True
                return None
            if after_wake(text) is not None or self.notified:
                self.pending_segment=True;self.notified=True
                return None
            if not self.armed:
                self.audio.clear();self.notified=False
            return None
        partial=json.loads(self.recognizer.PartialResult()).get('partial','')
        if not self.notified and after_wake(partial) is not None:
            self.notified=True
            return {'type':'wake'}
        return None

class WakeService:
    def __init__(self,models):
        self.path=models/'vosk-model-small-ru-0.22'
        self.model=None
        self.lock=threading.Lock()
        self.status='available' if (self.path/'am/final.mdl').is_file() else 'missing'

    def recognizer(self):
        from vosk import Model, KaldiRecognizer, SetLogLevel
        with self.lock:
            if self.model is None:
                self.status='loading';SetLogLevel(-1)
                try:self.model=Model(str(self.path));self.status='ready'
                except Exception:self.status='error';raise
        return KaldiRecognizer(self.model,SAMPLE_RATE)

    def mount(self,app,token,port,transcribe,ready,on_stop=lambda:None):
        slots=asyncio.Semaphore(2)
        @app.websocket('/api/wake')
        async def wake(socket:WebSocket):
            origin=socket.headers.get('origin')
            host=socket.headers.get('host','').split(':')[0]
            if host not in ('127.0.0.1','localhost','testserver') or origin not in (f'http://127.0.0.1:{port}','http://127.0.0.1:5173','http://localhost:5173'):
                await socket.close(code=1008);return
            await socket.accept()
            try:
                auth=await asyncio.wait_for(socket.receive_json(),5)
                if not isinstance(auth,dict) or not isinstance(auth.get('token'),str) or not secrets.compare_digest(auth['token'],token) or auth.get('sample_rate')!=SAMPLE_RATE:
                    await socket.close(code=1008);return
                if not ready():
                    await socket.send_json({'type':'error','message':'Распознавание речи ещё загружается.'});await socket.close();return
                if slots.locked():
                    await socket.send_json({'type':'error','message':'Голосовая активация уже используется в других окнах.'});await socket.close();return
                async with slots:
                    detector=WakeSession(await asyncio.to_thread(self.recognizer))
                    stop_only=auth.get('mode')=='stop'
                    await socket.send_json({'type':'ready'})
                    while True:
                        packet=await socket.receive()
                        if packet['type']=='websocket.disconnect':break
                        pcm=packet.get('bytes')
                        if pcm is None:raise ValueError('Expected audio')
                        if stop_only:
                            def detect_stop():
                                if not pcm or len(pcm)%2 or len(pcm)>12800:raise ValueError('Invalid PCM')
                                final=detector.recognizer.AcceptWaveform(pcm)
                                data=json.loads(detector.recognizer.Result() if final else detector.recognizer.PartialResult())
                                return bool(re.search(r'\bпятница\s+(?:стоп|остановись|останови)\b',data.get('text',data.get('partial','')),re.I))
                            if await asyncio.to_thread(detect_stop):
                                on_stop()
                                await socket.send_json({'type':'stopped'})
                                await socket.close();return
                            continue
                        event=await asyncio.to_thread(detector.feed,pcm)
                        if not event:continue
                        if event['type']!='segment':
                            await socket.send_json(event);continue
                        await socket.send_json({'type':'transcribing'})
                        recognized=await asyncio.to_thread(transcribe,event['audio'])
                        if isinstance(recognized,dict):
                            if recognized.get('uncertain'):
                                await socket.send_json({'type':'uncertain','text':recognized.get('text',''),'message':'Не уверена, что правильно расслышала. Проверьте текст перед отправкой.'})
                                await socket.close();return
                            recognized=recognized['text']
                        command=after_wake(recognized) if event['require_wake'] else recognized.strip()
                        if command is None:
                            await socket.send_json({'type':'idle'});continue
                        if not command or command.strip(' .!?').lower() in ('пятница','да','ага'):
                            detector.reset(armed=True)
                            await socket.send_json({'type':'listening'});continue
                        # Once awake the name can be repeated, but it is not required.
                        command=after_wake(command) if after_wake(command) is not None else command
                        if command.strip(' .!?').lower() in ('отмена','отмени','стоп','ничего','не надо','не нужно'):
                            on_stop()
                            await socket.send_json({'type':'cancelled'});continue
                        await socket.send_json({'type':'command','text':command})
                        # One command per connection. A fresh listener starts after the reply.
                        await socket.close();return
            except (WebSocketDisconnect,RuntimeError):pass
            except Exception:
                try:await socket.send_json({'type':'error','message':'Голосовая активация прервалась. Проверьте микрофон и включите её снова.'})
                except (RuntimeError,WebSocketDisconnect):pass
                try:await socket.close(code=1011)
                except RuntimeError:pass
