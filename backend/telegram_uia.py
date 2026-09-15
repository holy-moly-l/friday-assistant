"""Bounded, cancellable IPC to Telegram's accessibility provider. No network API."""
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time
from desktop_native import check
from pc import CommandError


def call(window, op, cancel, **args):
    check(cancel)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateEventW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
    kernel.CreateEventW.restype = wintypes.HANDLE
    kernel.SetEvent.argtypes = kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    name = 'Local\\FridayTelegram-' + secrets.token_hex(20)
    event = kernel.CreateEventW(None, True, False, name)
    if not event: raise CommandError('Не удалось создать сигнал остановки Telegram.')
    process = None
    try:
        process = subprocess.Popen([sys.executable, str(Path(__file__).with_name('telegram_uia_worker.py'))],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            creationflags=subprocess.CREATE_NO_WINDOW,
            env={**os.environ, 'FRIDAY_UIA_PARENT_PID': str(os.getpid())})
        payload = json.dumps(dict(window=window, op=op, cancel_event=name, **args), ensure_ascii=False).encode('utf-8')
        end = time.monotonic() + 18
        first = True
        while True:
            if cancel.is_set(): kernel.SetEvent(event)
            check(cancel)
            try:
                out, _ = process.communicate(payload if first else None, timeout=.05)
                break
            except subprocess.TimeoutExpired: first = False
            if time.monotonic() > end:
                raise CommandError('Telegram не ответил через UI Automation. Отправку не повторяю.')
        if process.returncode: raise CommandError('Интерфейс Telegram недоступен. Отправку не повторяю.')
        result = json.loads(out.decode('utf-8'))
        if result.get('error'): raise CommandError(result['error'])
        return result
    finally:
        kernel.SetEvent(event)
        if process:
            if process.poll() is None: process.kill()
            process.communicate()
        kernel.CloseHandle(event)
