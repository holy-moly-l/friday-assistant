from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from datetime import datetime
import io
import json
import logging
import os
from pathlib import Path
import re
import secrets
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import uuid
sys.path.insert(0, str(Path(__file__).resolve().parent))
from pc import CommandError, normalize, open_app, resolve_pc_command, run_pc
from expressive_voice import ExpressiveVoice, VoiceCancelled, PREVIEW_TEXT
from lifecycle import follow_parent
from wake_word import WakeService
from desktop_agent import DesktopAgent, deterministic, vision_request, stop_request
from desktop_trace import trace
from recognition import MODEL_FOLDER as STT_FOLDER, MODEL_LABEL as STT_LABEL, transcribe as recognize_russian
follow_parent(os.environ.get('FRIDAY_DESKTOP_PID'))

import httpx
import numpy as np
import psutil
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
import soundfile as sf

ROOT = Path(os.environ.get('FRIDAY_ROOT', Path(__file__).resolve().parents[1]))
DATA = Path(os.environ.get('FRIDAY_DATA_DIR', ROOT / 'data'))
DATA.mkdir(exist_ok=True)
MODELS = ROOT / 'models'
DB = DATA / 'friday.db'
TOKEN = os.environ.get('FRIDAY_TOKEN') or secrets.token_urlsafe(32)
PORT = int(os.environ.get('FRIDAY_PORT', '17835'))
OLLAMA = 'http://127.0.0.1:11434'
state = {'llm': 'loading', 'stt': 'loading', 'tts': 'loading', 'errors': {}}
dll_handles = []
stt_device = 'cpu'
voice_model = None
whisper_model = None
voice_lock = threading.Lock()
whisper_lock = threading.Lock()
chat_lock = asyncio.Lock()
log = logging.getLogger('friday')
expressive = ExpressiveVoice(ROOT)
wake_service = WakeService(MODELS)
desktop = DesktopAgent(DATA, before_model=expressive.close)


def connect():
    db = sqlite3.connect(DB, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    return db


def init_db():
    with connect() as db:
        db.executescript('''
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY, title TEXT NOT NULL, created TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS messages(id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE, role TEXT NOT NULL, content TEXT NOT NULL, created TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS notes(id TEXT PRIMARY KEY, content TEXT NOT NULL, created TEXT NOT NULL);
        ''')


def save_message(session_id, role, content):
    mid = str(uuid.uuid4())
    with connect() as db:
        db.execute('INSERT INTO messages VALUES (?,?,?,?,?)', (mid, session_id, role, content, datetime.now().isoformat()))
    return mid


def load_voice():
    global voice_model
    try:
        import torch
        torch.set_num_threads(4)
        voice_model = torch.package.PackageImporter(str(MODELS / 'silero-v4-ru.pt')).load_pickle('tts_models', 'model')
        voice_model.to(torch.device('cpu'))
        for _ in range(3):
            voice_model.apply_tts(text='Привет. Я Пятница, ваша персональная помощница. Все системы готовы.', speaker='xenia', sample_rate=48000)
        state['tts'] = 'ready'
    except Exception as exc:
        log.exception('Voice loading failed')
        state['tts'] = 'error'
        state['errors']['tts'] = str(exc)


def load_whisper():
    global whisper_model, stt_device
    try:
        if os.name == 'nt':
            candidates = [Path(os.environ.get('LOCALAPPDATA', '')) / 'Programs/Ollama/lib/ollama/cuda_v12', Path(sys.prefix) / 'Lib/site-packages/nvidia/cuda_nvrtc/bin', Path(sys.prefix) / 'Lib/site-packages/nvidia/cublas/bin', Path(sys.prefix) / 'Lib/site-packages/nvidia/cudnn/bin']
            for folder in candidates:
                if folder.exists():
                    dll_handles.append(os.add_dll_directory(str(folder)))
                    os.environ['PATH'] = str(folder) + os.pathsep + os.environ['PATH']
        import ctranslate2
        from faster_whisper import WhisperModel
        if ctranslate2.get_cuda_device_count() > 0:
            try:
                whisper_model = WhisperModel(str(MODELS / STT_FOLDER), device='cuda', compute_type='int8_float16', local_files_only=True)
                # Exercise CUDA/cuDNN during startup, so a missing runtime falls back before the first recording.
                list(whisper_model.transcribe(np.zeros(16000, dtype=np.float32), language='ru', beam_size=1, vad_filter=False)[0])
                stt_device = 'cuda'
                whisper_model.model.unload_model(to_cpu=True)
            except Exception:
                log.warning('CUDA recognition unavailable; using CPU', exc_info=True)
                whisper_model = None
        if whisper_model is None:
            whisper_model = WhisperModel(str(MODELS / STT_FOLDER), device='cpu', compute_type='int8', cpu_threads=6, local_files_only=True)
            stt_device = 'cpu'
        state['stt'] = 'ready'
    except Exception as exc:
        log.exception('Whisper loading failed')
        state['stt'] = 'error'
        state['errors']['stt'] = str(exc)


def warm_llm():
    try:
        with httpx.Client(timeout=180, trust_env=False) as client:
            response = client.get(f'{OLLAMA}/api/tags')
            response.raise_for_status()
            if desktop.model not in [m['name'] for m in response.json()['models']]:
                raise RuntimeError('Скачайте выбранную модель в настройках → Система.')
        state['llm'] = 'ready'
    except Exception as exc:
        state['llm'] = 'error'
        state['errors']['llm'] = str(exc)


@asynccontextmanager
async def lifespan(app):
    init_db()
    desktop.foreground.start()
    (DATA / 'runtime.json').write_text(json.dumps({'port': PORT, 'token': TOKEN, 'pid': os.getpid()}), encoding='utf-8')
    pool = ThreadPoolExecutor(max_workers=3)
    for fn in (load_voice, load_whisper, warm_llm):
        pool.submit(fn)
    yield
    desktop.stop()
    desktop.foreground.closed.set()
    expressive.close()
    pool.shutdown(wait=False)


app = FastAPI(title='Friday Local', lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


@app.middleware('http')
async def local_only(request: Request, call_next):
    host = request.headers.get('host', '').split(':')[0]
    if host not in ('127.0.0.1', 'localhost', 'testserver'):
        return JSONResponse({'detail': 'Local connections only'}, status_code=403)
    if request.url.path.startswith('/api/') and request.url.path != '/api/health':
        if not secrets.compare_digest(request.headers.get('X-Friday-Token', ''), TOKEN):
            return JSONResponse({'detail': 'Откройте приложение через ярлык «Пятница».'}, status_code=401)
        origin = request.headers.get('origin')
        if origin and origin not in (f'http://127.0.0.1:{PORT}', 'http://127.0.0.1:5173', 'http://localhost:5173'):
            return JSONResponse({'detail': 'Origin forbidden'}, status_code=403)
    response = await call_next(request)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; media-src 'self' blob:; connect-src 'self'; frame-ancestors 'none'"
    return response


@app.get('/api/health')
def health():
    return {'app': 'friday', 'version': '1.7.0', 'services': {k: state[k] for k in ('llm', 'stt', 'tts')}, 'model': desktop.model, 'stt_model': STT_LABEL, 'stt_device': stt_device, 'expressive_voice': expressive.status, 'wake_word': wake_service.status}


@app.post('/api/retry')
def retry_models():
    for name, fn in [('llm', warm_llm), ('stt', load_whisper), ('tts', load_voice)]:
        if state[name] == 'error':
            state[name] = 'loading'
            state['errors'].pop(name, None)
            threading.Thread(target=fn, daemon=True).start()
    return health()


@app.get('/api/system')
def system():
    memory = psutil.virtual_memory()
    return {'cpu': psutil.cpu_percent(), 'ram_used': round(memory.used / 1024**3, 1), 'ram_total': round(memory.total / 1024**3, 1), 'services': state, 'model': desktop.model}


@app.get('/api/sessions')
def sessions():
    with connect() as db:
        return [dict(r) for r in db.execute('SELECT s.*, (SELECT COUNT(*) FROM messages m WHERE m.session_id=s.id) AS count FROM sessions s ORDER BY created DESC LIMIT 100')]


@app.post('/api/sessions')
def new_session():
    row = {'id': str(uuid.uuid4()), 'title': 'Новый разговор', 'created': datetime.now().isoformat()}
    with connect() as db:
        db.execute('INSERT INTO sessions VALUES (:id,:title,:created)', row)
    return row


@app.get('/api/sessions/{sid}')
def get_session(sid: str):
    with connect() as db:
        session = db.execute('SELECT * FROM sessions WHERE id=?', (sid,)).fetchone()
        if not session:
            raise HTTPException(404, 'Разговор не найден')
        return {'session': dict(session), 'messages': [dict(r) for r in db.execute('SELECT * FROM messages WHERE session_id=? ORDER BY rowid', (sid,))]}


@app.delete('/api/sessions/{sid}')
def delete_session(sid: str):
    if chat_lock.locked():
        raise HTTPException(409, 'Сначала остановите ответ')
    with connect() as db:
        db.execute('DELETE FROM sessions WHERE id=?', (sid,))
    return {'ok': True}


@app.get('/api/notes')
def notes():
    with connect() as db:
        return [dict(r) for r in db.execute('SELECT * FROM notes ORDER BY created DESC LIMIT 100')]


from command_language import CATALOG, calculate, resolve as resolve_language

def resolve_command(text: str):
    command=resolve_language(text)
    legacy={'calculator':'\u043a\u0430\u043b\u044c\u043a\u0443\u043b\u044f\u0442\u043e\u0440','notepad':'\u0431\u043b\u043e\u043a\u043d\u043e\u0442','explorer':'\u043f\u0440\u043e\u0432\u043e\u0434\u043d\u0438\u043a'}
    if command and command[0]=='pc_app' and command[1] in legacy:return ('open',legacy[command[1]])
    return command


def execute_command(command):
    kind, arg = command
    if kind == 'calculate':
        try:answer=calculate(arg)
        except ZeroDivisionError:raise CommandError('На ноль делить нельзя.')
        except SyntaxError:raise CommandError('Проверьте выражение и скобки. Например: «Посчитай (25 + 5) / 2».')
        except (ValueError,OverflowError) as exc:raise CommandError(str(exc))
        return f'Результат: {answer}.', 'Вычислено'
    if kind == 'weekday':
        days=['понедельник','вторник','среда','четверг','пятница','суббота','воскресенье']
        return 'Сегодня '+days[datetime.now().weekday()]+'.', 'День недели'
    if kind == 'notes':
        with connect() as db:rows=db.execute('SELECT content FROM notes ORDER BY created DESC LIMIT 5').fetchall()
        return ('Последние заметки:\n'+'\n'.join(f'{i+1}. {row[0][:500]}' for i,row in enumerate(rows)) if rows else 'Заметок пока нет. Скажите: «Запиши заметку», а затем ваш текст.'), 'Мои заметки'
    if kind == 'help':
        return f'В каталоге {len(CATALOG)} команд: программы, папки, сайты, поиск, звук, музыка, экран, параметры Windows, заметки и вычисления. Откройте вкладку «Команды»: у каждого действия есть варианты фраз. Можно говорить «Пятница, будь добра» или «можешь». Полный список также сохранён в COMMANDS.md.', 'Справка'
    if kind == 'time':
        return f'Сейчас {datetime.now():%H:%M}.', 'Текущее время'
    if kind == 'date':
        months = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря']
        now = datetime.now()
        return f'Сегодня {now.day} {months[now.month - 1]} {now.year} года.', 'Сегодняшняя дата'
    if kind == 'system':
        info = system()
        return f"Загрузка процессора — {info['cpu']:.0f}%. Используется {info['ram_used']} из {info['ram_total']} ГБ оперативной памяти.", 'Состояние системы'
    if kind == 'note':
        with connect() as db:
            db.execute('INSERT INTO notes VALUES (?,?,?)', (str(uuid.uuid4()), arg, datetime.now().isoformat()))
        return f'Заметка сохранена: {arg}', 'Заметка сохранена'
    if kind == 'open':
        open_app({'калькулятор':'calculator','блокнот':'notepad','проводник':'explorer'}[arg])
        return f'Открываю {arg}.', 'Приложение открыто'
    if kind.startswith('pc_'):
        return run_pc(command, DATA)
    raise ValueError('Unknown command')


class ChatBody(BaseModel):
    session_id: str
    text: str = Field(min_length=1, max_length=8000)


@app.post('/api/chat')
async def chat(body: ChatBody, request: Request):
    text = body.text.strip()
    if not text:
        raise HTTPException(422, 'Введите сообщение')
    if stop_request(text) or desktop.telegram.cancelling(text,body.session_id):
        desktop.stop()
        return StreamingResponse(iter([json.dumps({'type':'delta','text':'Остановлено.'},ensure_ascii=False)+'\n']),media_type='application/x-ndjson')
    if chat_lock.locked():
        raise HTTPException(409, 'Дождитесь текущего ответа')
    with connect() as db:
        if not db.execute('SELECT id FROM sessions WHERE id=?', (body.session_id,)).fetchone():
            raise HTTPException(404, 'Разговор не найден')
    messaging = desktop.telegram.handles(text,body.session_id)
    command = None if messaging or vision_request(text) else resolve_command(text)
    if not messaging and not command and deterministic(text) is None and state['llm'] != 'ready' and not (vision_request(text) and not desktop.vision):
        raise HTTPException(503, 'Модель ещё загружается. Подождите немного или проверьте настройки.')
    await chat_lock.acquire()
    try:
        save_message(body.session_id, 'user', text)
        with connect() as db:
            db.execute("UPDATE sessions SET title=? WHERE id=? AND title='Новый разговор'", (text[:60], body.session_id))
            rows = db.execute('SELECT role,content FROM messages WHERE session_id=? ORDER BY rowid DESC LIMIT 16', (body.session_id,)).fetchall()
        history = list(reversed([dict(r) for r in rows]))
        # Bound historical text separately from the newest input.
        while len(history) > 1 and sum(len(m['content']) for m in history) > 12000:
            history.pop(0)
        if history and history[0]['role'] != 'user':
            history.pop(0)
    except Exception:
        chat_lock.release()
        raise

    def event(data):
        return json.dumps(data, ensure_ascii=False) + '\n'

    async def generate():
        answer = ''
        saved = False
        started = time.perf_counter()
        try:
            if command and deterministic(text) is None:
                answer, label = await asyncio.to_thread(execute_command, command)
                yield event({'type': 'action', 'label': label})
                yield event({'type': 'delta', 'text': answer})
            else:
                async for data in desktop.run(text,body.session_id,history):
                    if data['type']=='delta':answer+=data['text']
                    yield event(data)
            if answer:
                mid = save_message(body.session_id, 'assistant', answer)
                saved = True
                yield event({'type': 'done', 'id': mid, 'elapsed': round(time.perf_counter() - started, 2)})
        except asyncio.CancelledError:
            raise
        except CommandError as exc:
            answer = str(exc)
            yield event({'type': 'delta', 'text': answer})
        except FileNotFoundError as exc:
            log.error('Application launch failed: %s',type(exc).__name__)
            answer = 'Не удалось найти программу для этой команды. Попробуйте назвать её как в меню «Пуск».'
            yield event({'type': 'delta', 'text': answer})
        except Exception as exc:
            log.error('Chat failed: %s',type(exc).__name__)
            yield event({'type': 'error', 'message': 'Не удалось завершить ответ. Проверьте состояние моделей в настройках и попробуйте ещё раз.'})
        finally:
            if answer and not saved:
                save_message(body.session_id, 'assistant', answer)
            chat_lock.release()

    return StreamingResponse(generate(), media_type='application/x-ndjson', headers={'Cache-Control': 'no-cache'})


class SpeechBody(BaseModel):
    text: str = Field(min_length=1, max_length=5000)
    speaker: str = 'xenia'
    preview: bool = False


@app.post('/api/speech')
async def speech(body: SpeechBody, request: Request):
    if not body.speaker.startswith('qwen-') and state['tts'] != 'ready':
        raise HTTPException(503, 'Голос ещё загружается')
    if body.speaker not in ('xenia', 'baya', 'kseniya', 'qwen-serena', 'qwen-sohee', 'qwen-anna'):
        raise HTTPException(422, 'Неизвестный голос')
    clean = re.sub(r'```.*?```', ' Фрагмент кода доступен в чате. ', PREVIEW_TEXT if body.preview else body.text, flags=re.S)
    clean = re.sub(r'https?://\S+', ' ссылка ', clean)
    clean = re.sub(r'[*#_`<>\[\]{}|~]', '', clean).strip()
    if not clean:
        raise HTTPException(422, 'Нет текста для озвучки')
    if body.speaker.startswith('qwen-'):
        if len(clean)>500:
            raise HTTPException(422, 'Для выразительной озвучки отправляйте текст частями до 500 символов.')
        speaker={'qwen-serena':'Serena','qwen-sohee':'Sohee','qwen-anna':'Ono_Anna'}[body.speaker]
        # Free only our own LLM before the expressive GPU voice needs memory.
        if not body.preview and not desktop.running:
            try:
                async with httpx.AsyncClient(timeout=10,trust_env=False) as client:
                    await client.post(OLLAMA+'/api/generate',json={'model':desktop.model,'keep_alive':0})
            except httpx.HTTPError:pass
        cancelled=threading.Event()
        task=asyncio.create_task(asyncio.to_thread(expressive.synthesize,clean,speaker,cancelled,body.preview))
        async def watch_disconnect():
            # Await the ASGI receive channel. Polling is_disconnected() can miss
            # disconnects behind Starlette's BaseHTTPMiddleware receive wrapper.
            while True:
                message=await request.receive()
                if message['type']=='http.disconnect':
                    cancelled.set()
                    return
        watcher=asyncio.create_task(watch_disconnect())
        try:
            return Response(await task,media_type='audio/wav',headers={'Cache-Control':'no-store'})
        except VoiceCancelled:
            raise HTTPException(499,'Озвучка отменена')
        except Exception as exc:
            log.error('Expressive speech failed: %s',type(exc).__name__)
            raise HTTPException(503,str(exc))
        finally:
            watcher.cancel()
            cancelled.set()
            # A disconnected ASGI task must still consume the worker's outcome.
            if not task.done():task.add_done_callback(lambda t: None if t.cancelled() else t.exception())
    chunks = []
    current = ''
    for word in clean.split():
        if len(current) + len(word) > 700:
            chunks.append(current.strip())
            current = ''
        current += word + ' '
    if current.strip():
        chunks.append(current.strip())
    try:
        def render_fast():
            with voice_lock:
                return [voice_model.apply_tts(text=c, speaker=body.speaker, sample_rate=48000, put_accent=True, put_yo=True).numpy() for c in chunks]
        audio=await asyncio.to_thread(render_fast)
        buffer = io.BytesIO()
        sf.write(buffer, np.concatenate(audio), 48000, format='WAV', subtype='PCM_16')
        return Response(buffer.getvalue(), media_type='audio/wav', headers={'Cache-Control': 'no-store'})
    except Exception as exc:
        log.error('Speech synthesis failed: %s',type(exc).__name__)
        raise HTTPException(500, 'Не удалось озвучить этот текст. Попробуйте другую формулировку.')


@app.post('/api/transcribe')
async def transcribe(audio: UploadFile = File(...)):
    if state['stt'] != 'ready':
        raise HTTPException(503, 'Распознавание ещё загружается')
    content = await audio.read(12 * 1024 * 1024 + 1)
    if len(content) > 12 * 1024 * 1024:
        raise HTTPException(413, 'Запись слишком большая. Запишите до двух минут.')
    if len(content) < 100:
        raise HTTPException(422, 'Запись пустая')

    def recognize():
        import av
        from faster_whisper.audio import decode_audio
        try:
            decoded = decode_audio(io.BytesIO(content), sampling_rate=16000)
        except Exception:
            raise HTTPException(422, 'Не удалось прочитать запись')
        if len(decoded) > 16000 * 125:
            raise HTTPException(413, 'Максимальная длина записи — две минуты')
        return recognize_audio(decoded)

    return await asyncio.to_thread(recognize)


def recognize_audio(audio):
    with whisper_lock:
        if stt_device=='cuda':
            # STT, the local planner and expressive speech share an 8 GB GPU.
            expressive.close()
            try:
                with httpx.Client(timeout=10,trust_env=False) as client:
                    client.post(OLLAMA+'/api/generate',json={'model':desktop.model,'keep_alive':0})
            except httpx.HTTPError:pass
            whisper_model.model.load_model()
        try:
            result=recognize_russian(whisper_model,audio)
            trace('VOICE',result.get('text',''),uncertain=result.get('uncertain',False))
            return result
        finally:
            if stt_device=='cuda':whisper_model.model.unload_model(to_cpu=True)

def transcribe_wake_pcm(pcm):
    return recognize_audio(np.frombuffer(pcm,dtype='<i2').astype(np.float32)/32768)

class DesktopSettingsBody(BaseModel):
    model: str
    vision: bool = True

class ApprovalBody(BaseModel):
    nonce: str = Field(min_length=1,max_length=100)
    allow: bool

@app.get('/api/desktop/settings')
async def desktop_settings():
    result=desktop.settings()
    try:
        result['installed']=await desktop.model_list()
        if desktop.model in result['installed']:
            state['llm']='ready';state['errors'].pop('llm',None)
    except httpx.HTTPError:result.update(installed=[],error='Ollama недоступна. Запустите её и обновите состояние.')
    return result

@app.post('/api/desktop/settings')
async def desktop_save(body:DesktopSettingsBody):
    try:desktop.save(body.model,body.vision)
    except CommandError as exc:raise HTTPException(409,str(exc))
    await asyncio.to_thread(warm_llm)
    return desktop.settings()

@app.post('/api/desktop/download')
async def desktop_download(body:DesktopSettingsBody):
    try:await desktop.pull(body.model)
    except CommandError as exc:raise HTTPException(409,str(exc))
    return {'ok':True}

@app.post('/api/desktop/stop')
async def desktop_stop():
    desktop.stop();return {'ok':True}

@app.post('/api/desktop/approve')
async def desktop_approve(body:ApprovalBody):
    try:desktop.approve(body.nonce,body.allow)
    except CommandError as exc:raise HTTPException(409,str(exc))
    return {'ok':True}

wake_service.mount(app,TOKEN,PORT,transcribe_wake_pcm,lambda:state['stt']=='ready',desktop.stop,lambda:bool(desktop.pending))

if (ROOT / 'dist').exists():
    app.mount('/', StaticFiles(directory=str(ROOT / 'dist'), html=True), name='frontend')

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='127.0.0.1', port=PORT, log_level='info', ws='websockets-sansio')
