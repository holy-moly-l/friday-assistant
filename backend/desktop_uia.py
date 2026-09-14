import json
import os
from pathlib import Path
import subprocess
import sys
import time
from desktop_native import check
from pc import CommandError
from desktop_trace import trace

def call(window,op,cancel,**args):
    check(cancel)
    trace('UIA',op,hwnd=window['hwnd'])
    process=subprocess.Popen([sys.executable,str(Path(__file__).with_name('desktop_uia_worker.py'))],
        stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,creationflags=subprocess.CREATE_NO_WINDOW,
        env={**os.environ,'FRIDAY_UIA_PARENT_PID':str(os.getpid())})
    payload=json.dumps(dict(window=window,op=op,**args),ensure_ascii=False).encode('utf-8')
    end=time.monotonic()+9;first=True
    try:
        while True:
            check(cancel)
            try:
                out,err=process.communicate(payload if first else None,timeout=.1);break
            except subprocess.TimeoutExpired:first=False
            if time.monotonic()>end:raise CommandError('Приложение не ответило на чтение интерфейса за 9 секунд.')
        if process.returncode:raise CommandError('Не удалось прочитать интерфейс приложения.')
        result=json.loads(out.decode('utf-8'))
        if result.get('error'):raise CommandError(result['error'])
        return result
    finally:
        if process.poll() is None:process.kill()
        process.communicate()
