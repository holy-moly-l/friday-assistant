"""Bounded gesture actions: explicit target, expiring lease, no mouse clicks or text entry."""
from __future__ import annotations
import asyncio
import math
import secrets
import threading
import time
import desktop_native as native
import gesture_media
from pc import CommandError


def drag_position(rect, work, dx, dy):
    width, height = rect[2]-rect[0], rect[3]-rect[1]
    x = round(rect[0]+dx*(work[2]-work[0])*2)
    y = round(rect[1]+dy*(work[3]-work[1])*2)
    return max(work[0], min(work[2]-min(width, work[2]-work[0]), x)), max(work[1], min(work[3]-min(height, work[3]-work[1]), y))


def move_drag(window, anchor, x, y, cancel):
    native.check(cancel)
    fresh = native.same(window)
    if fresh['minimized'] or fresh['maximized']:raise CommandError('Состояние окна изменилось. Отпустите щипок и повторите.')
    if not any(s['device_id']==anchor['screen']['device_id'] for s in native.monitors()):
        raise CommandError('Монитор отключён. Выберите окно заново.')
    px, py = drag_position(anchor['rect'], anchor['screen']['rect'], x-anchor['x'], y-anchor['y'])
    native.check(cancel)
    if not native.u.SetWindowPos(fresh['hwnd'], None, px, py, 0, 0, 0x4015):
        raise CommandError('Windows не разрешила переместить окно.')
    def arrived():
        r = native.same(window)['rect']
        return abs(r[0]-px)<=2 and abs(r[1]-py)<=2
    if not native.wait_for(arrived, cancel, .4):raise CommandError('Окно не подтвердило перемещение.')


class GestureControl:
    def __init__(self, busy=lambda:False):
        self.busy=busy;self.lock=asyncio.Lock();self.session=None;self.revision=0

    def stop(self):
        self.revision+=1
        session=self.session
        self.session=None
        if session:
            session['cancel'].set()
            if session.get('task'):session['task'].cancel()

    def status(self):
        if self.session and (time.monotonic()-self.session['seen']>1.8 or self.busy()):self.stop()
        return dict(armed=bool(self.session), dragging=bool(self.session and self.session['drag']))

    async def watchdog(self):
        try:
            while True:
                self.status();await asyncio.sleep(.2)
        finally:self.stop()

    async def arm(self, mode, hwnd=0, media=''):
        self.stop()
        revision=self.revision
        if self.busy() or self.lock.locked():raise CommandError('Сначала завершите текущее действие.')
        target=None
        if mode=='windows':
            target=next((w for w in native.windows() if w['hwnd']==hwnd), None)
            if not target:raise CommandError('Выберите открытое пользовательское окно.')
        elif mode=='media':
            found=[s for s in await gesture_media.sessions() if s['id']==media and not s['ambiguous']]
            if len(found)!=1:raise CommandError('Выберите доступный медиаплеер.')
        else:raise CommandError('Неизвестный режим жестов.')
        if revision!=self.revision or self.busy():raise CommandError('Включение управления отменено.')
        token=secrets.token_urlsafe(24)
        self.session=dict(token=token, mode=mode, target=target, media=media, cancel=threading.Event(),
            seen=time.monotonic(), sequence=-1, cooldown=0., drag=None, task=None)
        return dict(token=token, armed=True)

    def require(self, token):
        self.status()
        s=self.session
        if not s or not secrets.compare_digest(s['token'],token):raise CommandError('Управление остановлено. Включите его снова во вкладке камеры.')
        return s

    def heartbeat(self, token):
        s=self.require(token);s['seen']=time.monotonic()
        return self.status()

    async def action(self, token, sequence, kind, x=.5, y=.5):
        if not all(math.isfinite(v) and 0<=v<=1 for v in (x,y)):raise CommandError('Неверные координаты руки.')
        # Never queue old movement or a second gesture behind an unfinished media operation.
        if self.lock.locked():raise CommandError('Предыдущее действие ещё выполняется.')
        async with self.lock:
            s=self.require(token)
            if sequence<=s['sequence']:raise CommandError('Устаревший жест.')
            s['sequence']=sequence;s['seen']=time.monotonic();cancel=s['cancel']
            native.check(cancel)
            if kind=='release':s['drag']=None;return dict(message='Окно отпущено')
            if s['mode']=='media':
                if kind not in ('play_pause','seek_forward','seek_backward'):raise CommandError('Жест недоступен в режиме видео.')
            elif kind not in ('drag_start','drag_move','maximize','monitor_left','monitor_right'):
                raise CommandError('Жест недоступен в режиме окон.')
            if kind not in ('drag_start','drag_move'):
                if time.monotonic()<s['cooldown']:return dict(message='Подождите перед следующим жестом')
                s['cooldown']=time.monotonic()+1.0;s['drag']=None
            try:
                if s['mode']=='media':
                    task=asyncio.create_task(gesture_media.perform(s['media'],kind,cancel));s['task']=task
                    try:message=await asyncio.wait_for(task,5)
                    finally:s['task']=None
                else:
                    window=native.same(s['target'])
                    if kind=='drag_start':
                        if window['minimized'] or window['maximized']:
                            window=await asyncio.to_thread(native.window_action,window,'restore',1,cancel)
                        screen=native.window_monitor(window)
                        if not screen:raise CommandError('Не удалось определить монитор окна.')
                        s['drag']=dict(rect=window['rect'],screen=screen,x=x,y=y)
                        message='Перемещение окна'
                    elif kind=='drag_move':
                        if not s['drag']:raise CommandError('Сначала отпустите пальцы, затем захватите окно щипком.')
                        await asyncio.to_thread(move_drag,window,s['drag'],x,y,cancel)
                        message='Перемещение окна'
                    elif kind=='maximize':
                        mode='restore' if window['maximized'] else 'maximize'
                        await asyncio.to_thread(native.window_action,window,mode,1,cancel)
                        message='Окно восстановлено' if mode=='restore' else 'Окно развёрнуто'
                    else:
                        screens=sorted(native.monitors(), key=lambda s:(s['bounds'][0],s['bounds'][1]))
                        current=native.window_monitor(window)
                        index=next((i for i,scr in enumerate(screens) if current and scr['device_id']==current['device_id']),-1)
                        dest=index+(1 if kind=='monitor_right' else -1)
                        if index<0 or not 0<=dest<len(screens):raise CommandError('В этом направлении нет другого монитора.')
                        await asyncio.to_thread(native.window_action,window,'move',screens[dest]['index'],cancel)
                        message=f"Окно на мониторе {screens[dest]['index']}"
                native.check(cancel)
                return dict(message=message)
            except asyncio.CancelledError:
                self.stop();raise CommandError('Управление остановлено.')
            except Exception:
                self.stop();raise
