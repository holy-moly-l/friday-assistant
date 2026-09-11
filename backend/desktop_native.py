"""Bounded Windows operations. No shells, generated code or continuous screen capture."""
from __future__ import annotations
import base64
import ctypes as c
from ctypes import wintypes as w
import io
import threading
import time
import psutil
from pc import CommandError, open_app, get_volume

u = c.WinDLL('user32', use_last_error=True)
u.SetProcessDpiAwarenessContext.argtypes=[w.HANDLE]
u.SetProcessDpiAwarenessContext(c.c_void_p(-4))
for name, args, restype in [
    ('GetForegroundWindow', [], w.HWND), ('IsWindow', [w.HWND], w.BOOL),
    ('IsWindowVisible', [w.HWND], w.BOOL), ('IsIconic', [w.HWND], w.BOOL),
    ('IsZoomed', [w.HWND], w.BOOL), ('GetWindowTextLengthW', [w.HWND], c.c_int),
    ('GetWindowTextW', [w.HWND, w.LPWSTR, c.c_int], c.c_int),
    ('GetWindowThreadProcessId', [w.HWND, c.POINTER(w.DWORD)], w.DWORD),
    ('GetWindowRect', [w.HWND, c.POINTER(w.RECT)], w.BOOL),
    ('ShowWindow', [w.HWND,c.c_int], w.BOOL), ('SetForegroundWindow',[w.HWND],w.BOOL),
    ('ShowWindowAsync', [w.HWND,c.c_int], w.BOOL),
    ('PostMessageW',[w.HWND,w.UINT,w.WPARAM,w.LPARAM],w.BOOL),
    ('SetWindowPos',[w.HWND,w.HWND,c.c_int,c.c_int,c.c_int,c.c_int,w.UINT],w.BOOL),
]:
    f=getattr(u,name);f.argtypes=args;f.restype=restype

ALIASES = {
 'calculator': ('калькулятор','calculator','calc'), 'notepad':('блокнот','notepad'),
 'explorer':('проводник','explorer'), 'telegram':('телеграм','telegram'),
 'discord':('дискорд','discord'), 'paint':('paint','паинт'), 'chrome':('chrome','хром'),
 'edge':('edge','msedge'), 'firefox':('firefox','файрфокс'), 'steam':('steam','стим'),
 'vscode':('visual studio code','vscode','code'), 'taskmgr':('диспетчер задач','taskmgr'),
 'browser':('браузер','chrome','msedge','firefox','browser'),
 'settings':('параметры','settings','systemsettings'),
}

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
    callback=c.WINFUNCTYPE(w.BOOL,w.HWND,w.LPARAM)
    @callback
    def collect(hwnd,_):
        if u.IsWindowVisible(hwnd):
            item=info(hwnd)
            if item and item['title'] and item['process'].lower() not in ('friday.exe','electron.exe'):
                result.append(item)
        return True
    u.EnumWindows(collect,0)
    return result

def matches(window, name):
    name=name.lower();exe=window['process'].lower()
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
    _fields_=[('cbSize',w.DWORD),('rcMonitor',w.RECT),('rcWork',w.RECT),('dwFlags',w.DWORD)]

def monitors():
    result=[]
    callback=c.WINFUNCTYPE(w.BOOL,w.HANDLE,w.HDC,c.POINTER(w.RECT),w.LPARAM)
    u.GetMonitorInfoW.argtypes=[w.HANDLE,c.POINTER(MONITORINFO)]
    @callback
    def collect(handle,dc,rect,data):
        m=MONITORINFO();m.cbSize=c.sizeof(m)
        if u.GetMonitorInfoW(handle,c.byref(m)):
            r=m.rcWork;result.append(dict(primary=bool(m.dwFlags&1),rect=[r.left,r.top,r.right,r.bottom]))
        return True
    u.EnumDisplayMonitors(None,None,collect,0)
    result.sort(key=lambda x:(not x['primary'],x['rect'][0],x['rect'][1]))
    return [dict(index=i+1,**x) for i,x in enumerate(result)]

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

def launch(name,cancel):
    check(cancel)
    name=name.strip().casefold()
    # Names only: app_path resolves installed shortcuts. Never accept a path or CLI arguments.
    if not name or len(name)>80 or any(x in name for x in ('/', '\\', ':', '\n','\r',';','|')):
        raise CommandError('Укажите название установленной программы, без пути и аргументов.')
    existing=[x for x in windows() if matches(x,name)]
    if len(existing)==1:
        focus(existing[0],cancel);return existing[0]
    previous={x['hwnd'] for x in existing}
    open_app(name)
    def appeared():
        candidates=[x for x in windows() if matches(x,name)]
        fresh=[x for x in candidates if x['hwnd'] not in previous]
        if len(fresh)==1:return fresh[0]
        return next((x for x in candidates if x['hwnd']==u.GetForegroundWindow()),None)
    found=wait_for(appeared,cancel,12)
    if not found:raise CommandError(f'Запуск «{name}» запрошен, но окно не появилось. Успех не подтверждён.')
    return found

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
        if not monitor or monitor>len(screens):raise CommandError(f'Подключено мониторов: {len(screens)}. Монитор {monitor} недоступен.')
        maximized=bool(u.IsZoomed(h));u.ShowWindowAsync(h,1)
        if not wait_for(lambda:not u.IsIconic(h) and not u.IsZoomed(h),cancel):raise CommandError('Не удалось восстановить окно перед переносом.')
        r=same(window)['rect'];dest=screens[monitor-1]['rect']
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

def screenshot(window,cancel):
    from PIL import ImageGrab
    focus(window,cancel);r=same(window)['rect']
    if r[2]<=r[0] or r[3]<=r[1]:raise CommandError('Окно не видно.')
    check(cancel);im=ImageGrab.grab(bbox=tuple(r),all_screens=True)
    im.thumbnail((1280,900));buf=io.BytesIO();im.convert('RGB').save(buf,format='JPEG',quality=80)
    return base64.b64encode(buf.getvalue()).decode('ascii'),r

def point_click(window,x,y,expected_rect,expected_image,cancel):
    if not expected_rect or not expected_image:raise CommandError('Для следующего нажатия нужен новый снимок и новая команда.')
    focus(window,cancel)
    if same(window)['rect']!=expected_rect:raise CommandError('Окно переместилось после просмотра. Повторите запрос.')
    current,_=screenshot(window,cancel)
    if current!=expected_image:raise CommandError('Изображение окна изменилось после подтверждения. Повторите запрос, чтобы выбрать актуальную кнопку.')
    r=expected_rect;px=round(r[0]+x*(r[2]-r[0]));py=round(r[1]+y*(r[3]-r[1]))
    check(cancel);u.SetCursorPos(px,py)
    u.mouse_event(2,0,0,0,0);u.mouse_event(4,0,0,0,0)
