"""Bounded Windows operations. No shells, generated code or continuous screen capture."""
from __future__ import annotations
import base64
import ctypes as c
from ctypes import wintypes as w
import io
import json
import os
import re
from pathlib import Path
import subprocess
import sys
import threading
import time
import psutil
from pc import CommandError, open_app, get_volume, APP_ALIASES, canonical_app
from desktop_trace import trace

u = c.WinDLL('user32', use_last_error=True)
u.SetProcessDpiAwarenessContext.argtypes=[w.HANDLE]
u.SetProcessDpiAwarenessContext(c.c_void_p(-4))
for name, args, restype in [
    ('GetForegroundWindow', [], w.HWND), ('GetShellWindow', [], w.HWND), ('IsWindow', [w.HWND], w.BOOL),
    ('IsWindowVisible', [w.HWND], w.BOOL), ('IsIconic', [w.HWND], w.BOOL),
    ('IsZoomed', [w.HWND], w.BOOL), ('GetWindowTextLengthW', [w.HWND], c.c_int),
    ('GetWindowTextW', [w.HWND, w.LPWSTR, c.c_int], c.c_int),
    ('GetWindowThreadProcessId', [w.HWND, c.POINTER(w.DWORD)], w.DWORD),
    ('GetWindowRect', [w.HWND, c.POINTER(w.RECT)], w.BOOL),
    ('ShowWindow', [w.HWND,c.c_int], w.BOOL), ('SetForegroundWindow',[w.HWND],w.BOOL),
    ('ShowWindowAsync', [w.HWND,c.c_int], w.BOOL),
    ('PostMessageW',[w.HWND,w.UINT,w.WPARAM,w.LPARAM],w.BOOL),
    ('SetWindowPos',[w.HWND,w.HWND,c.c_int,c.c_int,c.c_int,c.c_int,w.UINT],w.BOOL),
    ('GetWindow',[w.HWND,w.UINT],w.HWND),('GetWindowLongPtrW',[w.HWND,c.c_int],c.c_ssize_t),
    ('GetClassNameW',[w.HWND,w.LPWSTR,c.c_int],c.c_int),
]:
    f=getattr(u,name);f.argtypes=args;f.restype=restype

ALIASES = APP_ALIASES

class Stopped(CommandError): pass

def check(cancel):
    if cancel.is_set(): raise Stopped('Остановлено. Следующие шаги не выполнялись.')

def wait_for(predicate, cancel, timeout=3):
    end=time.monotonic()+timeout
    while True:
        check(cancel)
        value=predicate()
        if value:return value
        if time.monotonic()>=end:return None
        cancel.wait(.08)

def info(hwnd):
    if not hwnd or not u.IsWindow(hwnd):return None
    length=u.GetWindowTextLengthW(hwnd)
    buf=c.create_unicode_buffer(min(length+1,1024));u.GetWindowTextW(hwnd,buf,len(buf))
    pid=w.DWORD();u.GetWindowThreadProcessId(hwnd,c.byref(pid))
    rect=w.RECT();u.GetWindowRect(hwnd,c.byref(rect))
    try:
        process=psutil.Process(pid.value);exe=process.name();created=process.create_time()
    except psutil.Error:return None
    return dict(hwnd=int(hwnd),pid=pid.value,created=created,title=buf.value,process=exe,
                rect=[rect.left,rect.top,rect.right,rect.bottom],minimized=bool(u.IsIconic(hwnd)),
                maximized=bool(u.IsZoomed(hwnd)))

def same(window):
    fresh=info(window['hwnd'])
    if not fresh or (fresh['pid'],fresh['created'])!=(window['pid'],window['created']):
        raise CommandError('Нужное окно уже закрыто или заменено. Назовите приложение снова.')
    return fresh

def windows():
    result=[]
    dwm=c.WinDLL('dwmapi');dwm.DwmGetWindowAttribute.argtypes=[w.HWND,w.DWORD,c.c_void_p,w.DWORD]
    callback=c.WINFUNCTYPE(w.BOOL,w.HWND,w.LPARAM)
    @callback
    def collect(hwnd,_):
        if hwnd==u.GetShellWindow():return True
        if u.IsWindowVisible(hwnd):
            style=u.GetWindowLongPtrW(hwnd,-20)
            if not style&0x40000 and (style&0x80 or u.GetWindow(hwnd,4)):return True
            cls=c.create_unicode_buffer(256);u.GetClassNameW(hwnd,cls,len(cls))
            if cls.value in ('Shell_TrayWnd','Shell_SecondaryTrayWnd','Progman','WorkerW','IME','MSCTFIME UI'):return True
            cloaked=w.DWORD()
            if dwm.DwmGetWindowAttribute(hwnd,14,c.byref(cloaked),c.sizeof(cloaked))==0 and cloaked.value:
                return True
            item=info(hwnd)
            if item and item['pid']!=os.getpid() and item['title'] and item['process'].lower() not in ('friday.exe','electron.exe','textinputhost.exe','searchhost.exe','shellexperiencehost.exe','startmenuexperiencehost.exe'):
                result.append(item)
        return True
    u.EnumWindows(collect,0)
    return result


def app_label(window):
    labels={'telegram':'Telegram','discord':'Discord','chrome':'Chrome','edge':'Edge','firefox':'Firefox',
            'vscode':'Visual Studio Code','calculator':'Калькулятор','notepad':'Блокнот','explorer':'Проводник',
            'paint':'Paint','steam':'Steam','settings':'Параметры Windows','taskmgr':'Диспетчер задач'}
    return next((label for key,label in labels.items() if matches(window,key)),Path(window['process']).stem)


def list_windows():
    grouped={}
    for window in windows():
        name=app_label(window);grouped[name]=grouped.get(name,0)+1
    return [{'name':name,'count':count} for name,count in grouped.items()]


def windows_text():
    items=list_windows()
    def suffix(n):return 'окно' if n%10==1 and n%100!=11 else 'окна' if n%10 in (2,3,4) and n%100 not in (12,13,14) else 'окон'
    return 'Сейчас открыты: '+', '.join(r['name']+(f' — {r["count"]} {suffix(r["count"])}' if r['count']>1 else '') for r in items)+'.' if items else 'Открытых пользовательских окон не нашла.'

def matches(window, name):
    name=canonical_app(name);exe=window['process'].lower()
    executables={'calculator':('calculatorapp.exe','calculator.exe','calc.exe'),
        'notepad':('notepad.exe',),'explorer':('explorer.exe',),'telegram':('telegram.exe',),
        'discord':('discord.exe',),'paint':('mspaint.exe','paint.exe'),'chrome':('chrome.exe',),
        'edge':('msedge.exe',),'firefox':('firefox.exe',),'steam':('steam.exe',),
        'vscode':('code.exe',),'taskmgr':('taskmgr.exe',),'settings':('systemsettings.exe',),
        'browser':('chrome.exe','msedge.exe','firefox.exe','browser.exe')}
    if name in executables:
        if exe in executables[name]:return True
        # Older Windows versions host packaged apps in ApplicationFrameHost.
        return exe=='applicationframehost.exe' and any(word in window['title'].lower() for word in ALIASES[name])
    return name in window['title'].lower() or name==exe.removesuffix('.exe')

class Foreground:
    def __init__(self):self.last=None;self.closed=threading.Event();self.thread=None
    def start(self):
        if self.thread:return
        def poll():
            while not self.closed.is_set():
                item=info(u.GetForegroundWindow())
                if item and item['title'] and item['process'].lower() not in ('friday.exe','electron.exe'):
                    self.last=item
                self.closed.wait(.25)
        self.thread=threading.Thread(target=poll,daemon=True);self.thread.start()
    def target(self, name, context):
        if name in ('context','его','ее','её'):
            if not context:raise CommandError('В этом разговоре пока нет выбранного окна. Назовите приложение.')
            return same(context)
        if name in ('active','',None):
            current=info(u.GetForegroundWindow())
            item=current if current and current['process'].lower() not in ('friday.exe','electron.exe') else self.last
            if not item:raise CommandError('Сначала выберите нужное окно или назовите программу.')
            return same(item)
        found=[x for x in windows() if matches(x,name)]
        if context and any(x['hwnd']==context['hwnd'] for x in found):return same(context)
        if len(found)==1:return found[0]
        if not found:raise CommandError(f'Не нашла открытое окно «{name}».')
        raise CommandError(f'Найдено несколько окон «{name}». Выберите нужное окно и скажите «это окно».')

class MONITORINFO(c.Structure):
    _fields_=[('cbSize',w.DWORD),('rcMonitor',w.RECT),('rcWork',w.RECT),('dwFlags',w.DWORD),('szDevice',w.WCHAR*32)]

class DISPLAY_DEVICE(c.Structure):
    _fields_=[('cb',w.DWORD),('DeviceName',w.WCHAR*32),('DeviceString',w.WCHAR*128),
              ('StateFlags',w.DWORD),('DeviceID',w.WCHAR*128),('DeviceKey',w.WCHAR*128)]

def monitors():
    result=[]
    callback=c.WINFUNCTYPE(w.BOOL,w.HANDLE,w.HDC,c.POINTER(w.RECT),w.LPARAM)
    u.GetMonitorInfoW.argtypes=[w.HANDLE,c.POINTER(MONITORINFO)]
    u.EnumDisplayDevicesW.argtypes=[w.LPCWSTR,w.DWORD,c.POINTER(DISPLAY_DEVICE),w.DWORD]
    @callback
    def collect(handle,dc,rect,data):
        m=MONITORINFO();m.cbSize=c.sizeof(m)
        if u.GetMonitorInfoW(handle,c.byref(m)):
            r=m.rcWork;full=m.rcMonitor
            number=re.search(r'DISPLAY(\d+)$',m.szDevice,re.I)
            device=DISPLAY_DEVICE();device.cb=c.sizeof(device)
            u.EnumDisplayDevicesW(m.szDevice,0,c.byref(device),1)
            result.append(dict(index=int(number[1]) if number else None,device=m.szDevice,
                device_id=device.DeviceID or m.szDevice,name=device.DeviceString or m.szDevice,handle=int(handle),
                primary=bool(m.dwFlags&1),rect=[r.left,r.top,r.right,r.bottom],bounds=[full.left,full.top,full.right,full.bottom]))
        return True
    u.EnumDisplayMonitors(None,None,collect,0)
    # Windows GDI DISPLAY number, not position or primary status. DeviceID retains hardware identity.
    return sorted(result,key=lambda x:(x['index'] is None,x['index'] or 0,x['device']))


def window_monitor(window):
    u.MonitorFromWindow.argtypes=[w.HWND,w.DWORD];u.MonitorFromWindow.restype=w.HANDLE
    fresh=same(window);handle=u.MonitorFromWindow(fresh['hwnd'],2)
    return next((s for s in monitors() if s.get('handle')==handle),None)

def focus(window,cancel):
    check(cancel);same(window);h=window['hwnd']
    if u.IsIconic(h):
        u.ShowWindowAsync(h,9)
        if not wait_for(lambda:not u.IsIconic(h),cancel):raise CommandError('Не удалось восстановить окно.')
    u.SetForegroundWindow(h)
    if u.GetForegroundWindow()!=h:
        # Join input queues only for this authorized focus change, then detach.
        kernel=c.WinDLL('kernel32');kernel.GetCurrentThreadId.restype=w.DWORD
        current=kernel.GetCurrentThreadId();foreground=u.GetWindowThreadProcessId(u.GetForegroundWindow(),None)
        u.AttachThreadInput.argtypes=[w.DWORD,w.DWORD,w.BOOL];u.AttachThreadInput.restype=w.BOOL
        attached=bool(foreground and foreground!=current and u.AttachThreadInput(current,foreground,True))
        try:
            check(cancel)
            if attached:u.SetForegroundWindow(h)
        finally:
            if attached:u.AttachThreadInput(current,foreground,False)
    if not wait_for(lambda:u.GetForegroundWindow()==h,cancel,1):
        raise CommandError('Windows не разрешила выбрать окно. Нажмите на него и повторите команду.')
    trace('FOCUS',status='success',hwnd=h)


def try_focus(window,cancel):
    """Best effort for launch only; cancellation and stale HWNDs remain fatal."""
    check(cancel);same(window)
    try:
        focus(window,cancel)
        return True
    except Stopped:raise
    except CommandError as exc:
        check(cancel);same(window)
        trace('FOCUS',status='error',non_fatal=True,hwnd=window['hwnd'])
        return False

def launch(name,cancel):
    check(cancel)
    name=canonical_app(name)
    # Names only: app_path resolves installed shortcuts. Never accept a path or CLI arguments.
    if not name or len(name)>80 or any(x in name for x in ('/', '\\', ':', '\n','\r',';','|')):
        raise CommandError('Укажите название установленной программы, без пути и аргументов.')
    existing=[x for x in windows() if matches(x,name)]
    if existing:
        chosen=next((x for x in existing if x['hwnd']==u.GetForegroundWindow()),existing[0])
        trace('VERIFY',status='success',tool='open_app',hwnd=chosen['hwnd'])
        focused=try_focus(chosen,cancel)
        return dict(same(chosen),launch_status='already_running',focused=focused,app=name)
    previous={x['hwnd'] for x in existing}
    try:open_app(name,cancel=cancel)
    except CommandError:
        check(cancel)
        raise
    def appeared():
        candidates=[x for x in windows() if matches(x,name)]
        fresh=[x for x in candidates if x['hwnd'] not in previous]
        if len(fresh)==1:return fresh[0]
        return next((x for x in candidates if x['hwnd']==u.GetForegroundWindow()),None)
    found=wait_for(appeared,cancel,12)
    if not found:raise CommandError(f'Программа «{name}» найдена, запуск запрошен, но окно не появилось. Успех не подтверждён.')
    trace('VERIFY',status='success',tool='open_app',hwnd=found['hwnd'])
    focused=try_focus(found,cancel)
    return dict(same(found),launch_status='started',focused=focused,app=name)

def window_action(window,mode,monitor,cancel):
    check(cancel);same(window);h=window['hwnd']
    if mode=='focus':focus(window,cancel);return same(window)
    if mode=='close':
        u.PostMessageW(h,0x10,0,0)
        if not wait_for(lambda:not u.IsWindow(h),cancel,3):
            raise CommandError('Окно осталось открытым. Возможно, нужно сохранить документ или ответить на диалог.')
        return None
    if mode=='move':
        screens=monitors()
        selected=next((s for s in screens if s['index']==monitor),None)
        if selected is None:raise CommandError(f'Монитор {monitor} недоступен. Номера подключённых дисплеев: '+', '.join(str(s['index']) for s in screens))
        maximized=bool(u.IsZoomed(h));u.ShowWindowAsync(h,1)
        if not wait_for(lambda:not u.IsIconic(h) and not u.IsZoomed(h),cancel):raise CommandError('Не удалось восстановить окно перед переносом.')
        r=same(window)['rect'];dest=selected['rect']
        width=min(r[2]-r[0],dest[2]-dest[0]);height=min(r[3]-r[1],dest[3]-dest[1])
        x=dest[0]+max(0,(dest[2]-dest[0]-width)//2);y=dest[1]+max(0,(dest[3]-dest[1]-height)//2)
        if not u.SetWindowPos(h,None,x,y,width,height,0x4014):raise CommandError('Windows не разрешила переместить окно.')
        def moved():
            item=same(window);r=item['rect'];cx=(r[0]+r[2])/2;cy=(r[1]+r[3])/2
            return item if dest[0]<=cx<dest[2] and dest[1]<=cy<dest[3] else None
        result=wait_for(moved,cancel)
        if result and maximized:
            u.ShowWindowAsync(h,3)
            if not wait_for(lambda:u.IsZoomed(h),cancel):raise CommandError('Окно перенесено, но не удалось развернуть его снова.')
            result=wait_for(moved,cancel)
    else:
        code={'minimize':6,'maximize':3,'restore':1}.get(mode)
        if code is None:raise CommandError('Неизвестное действие с окном.')
        u.ShowWindowAsync(h,code)
        def changed():
            item=same(window)
            ok=item['minimized'] if mode=='minimize' else item['maximized'] if mode=='maximize' else not item['minimized'] and not item['maximized']
            return item if ok else None
        result=wait_for(changed,cancel)
    if not result:raise CommandError('Windows не подтвердила изменение окна.')
    return result

def volume(mode,value,cancel):
    import comtypes
    check(cancel);comtypes.CoInitialize()
    try:
        endpoint=get_volume()
        if mode in ('mute','unmute'):
            wanted=mode=='mute';endpoint.SetMute(int(wanted),None)
            if bool(endpoint.GetMute())!=wanted:raise CommandError('Не удалось изменить состояние звука.')
            return 'Звук выключен.' if wanted else 'Звук включён.'
        old=round(endpoint.GetMasterVolumeLevelScalar()*100)
        wanted=max(0,min(100,value if mode=='set' else old+value))
        endpoint.SetMasterVolumeLevelScalar(wanted/100,None)
        actual=round(endpoint.GetMasterVolumeLevelScalar()*100)
        if abs(actual-wanted)>1:raise CommandError('Уровень громкости не изменился.')
        return f'Громкость {actual}%.'
    finally:comtypes.CoUninitialize()

def _print_window(window,cancel):
    check(cancel);same(window)
    process=subprocess.Popen([sys.executable,str(Path(__file__).with_name('desktop_capture_worker.py'))],
        stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,creationflags=subprocess.CREATE_NO_WINDOW,
        env={**os.environ,'FRIDAY_CAPTURE_PARENT_PID':str(os.getpid())})
    payload=json.dumps(window).encode('utf-8');first=True;end=time.monotonic()+6
    try:
        while True:
            check(cancel)
            try:
                output,_=process.communicate(payload if first else None,timeout=.1);break
            except subprocess.TimeoutExpired:first=False
            if time.monotonic()>end:raise CommandError('Приложение не вернуло снимок окна за 6 секунд. Попробуйте снимок монитора.')
        if process.returncode:raise CommandError('Не удалось получить снимок окна.')
        result=json.loads(output.decode('utf-8'))
        if result.get('error'):raise CommandError(result['error'])
        check(cancel)
        if same(window)['rect']!=result['rect']:raise CommandError('Окно переместилось во время снимка. Повторите запрос.')
        trace('SCREEN',**{k:v for k,v in result.items() if k!='image'})
        return result
    finally:
        if process.poll() is None:process.kill()
        process.communicate()


class WINDOWPLACEMENT(c.Structure):
    _fields_=[('length',w.UINT),('flags',w.UINT),('showCmd',w.UINT),('minPosition',w.POINT),('maxPosition',w.POINT),('normalPosition',w.RECT)]


def placement(window):
    u.GetWindowPlacement.argtypes=[w.HWND,c.POINTER(WINDOWPLACEMENT)]
    result=WINDOWPLACEMENT();result.length=c.sizeof(result)
    if not u.GetWindowPlacement(window['hwnd'],c.byref(result)):raise CommandError('Не удалось сохранить состояние окна.')
    return result


def restore_placement(window,saved):
    same(window)
    u.SetWindowPlacement.argtypes=[w.HWND,c.POINTER(WINDOWPLACEMENT)]
    if not u.SetWindowPlacement(window['hwnd'],c.byref(saved)):raise CommandError('Не удалось вернуть исходное состояние окна.')


def _frame_rect(hwnd):
    rect=w.RECT();dwm=c.WinDLL('dwmapi')
    dwm.DwmGetWindowAttribute.argtypes=[w.HWND,w.DWORD,c.c_void_p,w.DWORD]
    if dwm.DwmGetWindowAttribute(hwnd,9,c.byref(rect),c.sizeof(rect))!=0:u.GetWindowRect(hwnd,c.byref(rect))
    return [rect.left,rect.top,rect.right,rect.bottom]


def _intersection(a,b):
    r=[max(a[0],b[0]),max(a[1],b[1]),min(a[2],b[2]),min(a[3],b[3])]
    return r if r[0]<r[2] and r[1]<r[3] else None


def _subtract(a,b):
    r=_intersection(a,b)
    if not r:return [a]
    parts=[[a[0],a[1],a[2],r[1]],[a[0],r[3],a[2],a[3]],
           [a[0],r[1],r[0],r[3]],[r[2],r[1],a[2],r[3]]]
    return [p for p in parts if p[0]<p[2] and p[1]<p[3]]


def unobscured(window):
    """Check all windows above the target, including Friday and thin overlays (no sampling gaps)."""
    fresh=same(window)
    if fresh['minimized']:return False
    frame=_frame_rect(window['hwnd']);remaining=[frame]
    for screen in monitors():remaining=[part for r in remaining for part in _subtract(r,screen['bounds'])]
    if remaining:return False
    found=False;blocked=False
    dwm=c.WinDLL('dwmapi');dwm.DwmGetWindowAttribute.argtypes=[w.HWND,w.DWORD,c.c_void_p,w.DWORD]
    callback=c.WINFUNCTYPE(w.BOOL,w.HWND,w.LPARAM)
    @callback
    def visit(hwnd,_):
        nonlocal found,blocked
        if hwnd==window['hwnd']:found=True;return False
        if u.IsWindowVisible(hwnd) and not u.IsIconic(hwnd):
            cloaked=w.DWORD()
            dwm.DwmGetWindowAttribute(hwnd,14,c.byref(cloaked),c.sizeof(cloaked))
            if not cloaked.value and _intersection(frame,_frame_rect(hwnd)):blocked=True;return False
        return True
    u.EnumWindows(visit,0)
    return found and not blocked


def _monitor_crop(window,cancel):
    check(cancel);rect=same(window)['rect']
    if not unobscured(window):raise CommandError('PrintWindow недоступен, а окно перекрыто или находится за пределами экрана. Выведите его на передний план и повторите запрос.')
    result=_capture_bounds(rect,'window',{'hwnd':window['hwnd']},cancel,method='MonitorCropFallback')
    if same(window)['rect']!=rect or not unobscured(window):raise CommandError('Во время снимка окно переместилось или было перекрыто. Повторите запрос.')
    return result


def capture_window(window,cancel):
    check(cancel);fresh=same(window);saved=None
    try:
        if fresh['minimized']:
            saved=placement(window)
            u.ShowWindowAsync(window['hwnd'],4)
            if not wait_for(lambda:not u.IsIconic(window['hwnd']),cancel):raise CommandError('Не удалось временно восстановить окно для снимка.')
        try:return _print_window(window,cancel)
        except Stopped:raise
        except (CommandError,OSError,ValueError):
            check(cancel);trace('SCREEN',method='PrintWindow',status='unavailable',fallback=True)
            return _monitor_crop(window,cancel)
    finally:
        if saved is not None and info(window['hwnd']):
            # Cleanup is independent of cancellation, including provider errors and timeout.
            same(window);u.ShowWindowAsync(window['hwnd'],7)
            restore_placement(window,saved)
            if not wait_for(lambda:u.IsIconic(window['hwnd']),threading.Event()):
                raise CommandError('Снимок завершён, но Windows не подтвердила повторное сворачивание окна.')
            trace('SCREEN',restored=True,hwnd=window['hwnd'])


def _capture_bounds(rect,scope,target,cancel,method='ImageGrab'):
    from PIL import ImageGrab
    check(cancel)
    try:im=ImageGrab.grab(bbox=tuple(rect),all_screens=True)
    except OSError as exc:raise CommandError('Windows не предоставила снимок рабочего стола.') from exc
    check(cancel);original=list(im.size)
    buf=io.BytesIO();im.convert('RGB').save(buf,format='PNG')
    result=dict(image=base64.b64encode(buf.getvalue()).decode('ascii'),rect=rect,size=list(im.size),
        original_size=original,scope=scope,target=target,method=method)
    trace('SCREEN',**{k:v for k,v in result.items() if k!='image'})
    return result


def capture_screen(cancel,monitor=None,window=None):
    screens=monitors()
    if not screens:raise CommandError('Windows не сообщила о подключённых мониторах.')
    if monitor is None:
        active=window or info(u.GetForegroundWindow())
        selected=window_monitor(active) if active else None
        if selected is None:selected=next((s for s in screens if s['primary']),screens[0])
    else:
        selected=next((s for s in screens if s['index']==monitor),None)
        if selected is None:raise CommandError(f'Монитор {monitor} не подключён.')
    return _capture_bounds(selected['bounds'],'monitor',{'monitor':selected['index']},cancel)


def capture_all_screens(cancel):
    screens=monitors()
    if not screens:raise CommandError('Windows не сообщила о подключённых мониторах.')
    bounds=[min(s['bounds'][0] for s in screens),min(s['bounds'][1] for s in screens),
        max(s['bounds'][2] for s in screens),max(s['bounds'][3] for s in screens)]
    return _capture_bounds(bounds,'all_screens',{'monitors':screens},cancel)


def screenshot(window,cancel):
    """Compatibility for the coordinate executor: image and physical window bounds."""
    result=capture_window(window,cancel)
    return result['image'],result['rect']

def point_click(window,x,y,expected_rect,expected_image,cancel):
    if not expected_rect or not expected_image:raise CommandError('Для следующего нажатия нужен новый снимок и новая команда.')
    focus(window,cancel)
    if same(window)['rect']!=expected_rect:raise CommandError('Окно переместилось после просмотра. Повторите запрос.')
    current,_=screenshot(window,cancel)
    from desktop_images import scene_stable,changed_ratio
    ratio=scene_stable(expected_image,current)
    # Guard the short interval after re-localization too, but tolerate cursor blink and small animations.
    box=[max(0,x-.05),max(0,y-.04),min(1,x+.05),min(1,y+.04)]
    if changed_ratio(expected_image,current,(box,box))>.35:
        raise CommandError('Место нажатия изменилось во время поиска. Повторите команду.')
    trace('VERIFY',changed_ratio=ratio)
    r=expected_rect;px=round(r[0]+x*(r[2]-r[0]));py=round(r[1]+y*(r[3]-r[1]))
    u.WindowFromPoint.argtypes=[w.POINT];u.WindowFromPoint.restype=w.HWND
    u.GetAncestor.argtypes=[w.HWND,w.UINT];u.GetAncestor.restype=w.HWND
    if u.GetAncestor(u.WindowFromPoint(w.POINT(px,py)),2)!=window['hwnd'] or u.GetForegroundWindow()!=window['hwnd']:
        raise CommandError('Место нажатия перекрыто другим окном. Выберите нужное окно и повторите запрос.')
    check(cancel);u.SetCursorPos(px,py)
    u.mouse_event(2,0,0,0,0);u.mouse_event(4,0,0,0,0)
