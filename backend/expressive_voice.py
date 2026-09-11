from __future__ import annotations
import atexit
from collections import OrderedDict
import hashlib
import json
import os
from pathlib import Path
import queue
import subprocess
import threading
import time
import uuid

PREVIEW_TEXT='Привет! Я Пятница. Чем могу помочь?'

class VoiceCancelled(Exception):
    pass

class ExpressiveVoice:
    def __init__(self,root):
        self.root=Path(root)
        self.process=None
        self.messages=None
        self.lock=threading.Lock()
        self.status='available'
        self.log=None
        self.cache=OrderedDict()
        atexit.register(self.close)

    def close(self):
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:self.process.kill()
        self.process=None
        if self.log:self.log.close();self.log=None
        self.status='available'

    def _receive(self,timeout,cancel=None):
        deadline=time.monotonic()+timeout
        while True:
            if cancel is not None and cancel.is_set():
                self.close()
                raise VoiceCancelled()
            if time.monotonic()>=deadline:
                self.close()
                raise RuntimeError('Подготовка голоса заняла слишком много времени. Повторите попытку или выберите быстрый голос Silero.')
            try:
                reply=self.messages.get(timeout=min(.1,max(.001,deadline-time.monotonic())))
                break
            except queue.Empty:continue
        if reply.get('error'):
            reason=reply['error']
            self.close()
            if 'out of memory' in reason.lower():
                raise RuntimeError('Для выразительного голоса не хватает видеопамяти. Закройте игру или выберите быстрый голос Silero.')
            raise RuntimeError('Не удалось подготовить выразительный голос. Подробности в data/qwen-voice.log.')
        return reply

    def start(self,cancel=None):
        if self.process and self.process.poll() is None:return
        self.close();self.status='loading'
        python=self.root/'.venv-tts/Scripts/python.exe'
        if not python.is_file():raise RuntimeError('Среда выразительного голоса не установлена.')
        self.log=open(self.root/'data/qwen-voice.log','a',encoding='utf-8')
        self.messages=queue.Queue()
        channel=self.messages
        self.process=subprocess.Popen([str(python),'-u',str(self.root/'backend/qwen_voice.py')],cwd=str(self.root),
            stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=self.log,text=True,encoding='utf-8',bufsize=1,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0,
            env={**os.environ,'PYTHONUTF8':'1','HF_HUB_OFFLINE':'1','TRANSFORMERS_OFFLINE':'1','FRIDAY_PARENT_PID':str(os.getpid())})
        output=self.process.stdout
        def read():
            for line in output:
                try:channel.put(json.loads(line))
                except json.JSONDecodeError:pass
            channel.put({'error':'Voice process exited'})
        threading.Thread(target=read,daemon=True).start()
        self._receive(60,cancel)
        self.status='ready'

    def synthesize(self,text,speaker,cancel=None,preview=False):
        cancel=cancel or threading.Event()
        key=hashlib.sha256(('v2|'+speaker+'|'+text).encode()).hexdigest()
        preview_file=self.root/'data/voice-previews'/f'{key}.wav'
        # Only the fixed public demonstration is persisted, never conversation text.
        if preview and text==PREVIEW_TEXT and preview_file.is_file():return preview_file.read_bytes()
        deadline=time.monotonic()+3
        while not self.lock.acquire(timeout=.05):
            if cancel.is_set():raise VoiceCancelled()
            if time.monotonic()>deadline:raise RuntimeError('Предыдущая озвучка ещё завершается. Повторите через несколько секунд.')
        try:
            if cancel.is_set():raise VoiceCancelled()
            if key in self.cache:
                self.cache.move_to_end(key)
                return self.cache[key]
            self.start(cancel)
            self.status='synthesizing'
            output=self.root/'data'/('voice-'+str(uuid.uuid4())+'.wav')
            try:
                self.process.stdin.write(json.dumps({'text':text,'speaker':speaker,'output':str(output)},ensure_ascii=False)+'\n')
                self.process.stdin.flush()
                self._receive(90,cancel)
                data=output.read_bytes()
                if len(data)<1000 or data[:4]!=b'RIFF':raise RuntimeError('Модель вернула пустую запись. Повторите попытку.')
                self.cache[key]=data
                while len(self.cache)>16:self.cache.popitem(last=False)
                if preview and text==PREVIEW_TEXT:
                    preview_file.parent.mkdir(parents=True,exist_ok=True)
                    preview_file.write_bytes(data)
                return data
            finally:
                if self.process and self.process.poll() is None:self.status='ready'
                output.unlink(missing_ok=True)
        finally:
            self.lock.release()
