"""Explicit desktop actions. No generated code, command shells, or eval."""
from __future__ import annotations
import ctypes
from datetime import datetime
from functools import lru_cache
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
from urllib.parse import quote, urlsplit
import webbrowser


class CommandError(Exception):
    pass


from command_language import CATALOG, normalize, resolve as resolve_language
FOLDERS = {e['id']: e['action'][1] for e in CATALOG if e['action'][0]=='pc_folder'}
SETTINGS = {e['action'][1] for e in CATALOG if e['action'][0]=='pc_settings'}


def resolve_pc_command(text):
    result=resolve_language(text)
    return result if result and result[0].startswith('pc_') else None


def windows_dir():
    buf = ctypes.create_unicode_buffer(32768)
    if os.name == 'nt' and ctypes.windll.kernel32.GetWindowsDirectoryW(buf, len(buf)):
        return Path(buf.value)
    return Path(os.environ.get('WINDIR', 'C:/Windows'))


def launch_executable(path, args=()):
    path = Path(path)
    if not path.is_file():
        raise CommandError(f'Приложение не найдено: {path.name}. Проверьте, установлено ли оно.')
    subprocess.Popen([str(path), *args], shell=False)


@lru_cache(maxsize=1)
def installed_shortcuts():
    found = {}
    for base in [Path(os.environ.get('APPDATA',''))/'Microsoft/Windows/Start Menu/Programs',
                 Path(os.environ.get('PROGRAMDATA','C:/ProgramData'))/'Microsoft/Windows/Start Menu/Programs']:
        if base.exists():
            for p in base.rglob('*.lnk'):
                name = p.stem.lower()
                if not any(x in name for x in ('uninstall', 'удален', 'удалить', 'деинстал', 'remove')):
                    found.setdefault(name, str(p))
    return found


def app_path(app):
    win = windows_dir()
    direct = {'calculator': win/'System32/calc.exe', 'notepad':win/'System32/notepad.exe',
              'explorer':win/'explorer.exe', 'paint':win/'System32/mspaint.exe', 'taskmgr':win/'System32/Taskmgr.exe',
              'control':win/'System32/control.exe', 'snipping':win/'System32/SnippingTool.exe'}
    if app in direct:
        return direct[app]
    executables = {'chrome':'chrome.exe','edge':'msedge.exe','firefox':'firefox.exe','yandex':'browser.exe',
                   'telegram':'Telegram.exe','discord':'Discord.exe','steam':'steam.exe','vscode':'Code.exe'}
    if app in executables and os.name == 'nt':
        import winreg
        for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
                try:
                    with winreg.OpenKey(hive, 'SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\App Paths\\'+executables[app],0,winreg.KEY_READ|view) as key:
                        p=Path(winreg.QueryValueEx(key,None)[0].strip('"'))
                        if p.is_file(): return p
                except OSError: pass
    local = Path(os.environ.get('LOCALAPPDATA',''))
    roaming = Path(os.environ.get('APPDATA',''))
    program = Path(os.environ.get('PROGRAMFILES','C:/Program Files'))
    program86 = Path(os.environ.get('PROGRAMFILES(X86)','C:/Program Files (x86)'))
    candidates = {'chrome':[program/'Google/Chrome/Application/chrome.exe',local/'Google/Chrome/Application/chrome.exe'],
                  'edge':[program86/'Microsoft/Edge/Application/msedge.exe',program/'Microsoft/Edge/Application/msedge.exe'],
                  'yandex':[local/'Yandex/YandexBrowser/Application/browser.exe'],
                  'telegram':[roaming/'Telegram Desktop/Telegram.exe',local/'Telegram Desktop/Telegram.exe'],
                  'steam':[program86/'Steam/steam.exe'],
                  'vscode':[local/'Programs/Microsoft VS Code/Code.exe',program/'Microsoft VS Code/Code.exe'],
                  'firefox':[program/'Mozilla Firefox/firefox.exe']}
    for p in candidates.get(app,[]):
        if p.is_file(): return p
    aliases = {'telegram':'telegram','vscode':'visual studio code','chrome':'google chrome','edge':'microsoft edge','yandex':'yandex','discord':'discord','steam':'steam'}
    name = aliases.get(app,app)
    shortcuts = installed_shortcuts()
    if name in shortcuts: return Path(shortcuts[name])
    matches = [Path(value) for key,value in shortcuts.items() if key.startswith(name+' ') or key.endswith(' '+name)]
    if len(matches)==1: return matches[0]
    if len(matches)>1: raise CommandError('Найдено несколько приложений. Уточните название: '+', '.join(p.stem for p in matches[:5]))
    raise CommandError(f'Не нашла установленное приложение «{app}». Можно открыть браузер, проводник, калькулятор, блокнот или назвать программу из меню «Пуск».')


def open_app(app):
    uris = {'settings':'ms-settings:', 'sound_settings':'ms-settings:sound', 'mic_settings':'ms-settings:privacy-microphone'}
    if app in uris:
        os.startfile(uris[app]); return 'Параметры Windows'
    if app=='browser':
        if not webbrowser.open('about:blank',new=2):raise CommandError('Не удалось открыть браузер по умолчанию.')
        return 'Браузер'
    p=app_path(app)
    if p.suffix.lower()=='.lnk':os.startfile(str(p))
    else:launch_executable(p)
    labels={'calculator':'калькулятор','notepad':'блокнот','explorer':'проводник','taskmgr':'диспетчер задач'}
    return labels.get(app,app)


def get_volume():
    from pycaw.pycaw import AudioUtilities
    return AudioUtilities.GetSpeakers().EndpointVolume


def adjust_volume(kind,arg):
    if kind=='pc_volume_delta' and not 1<=abs(arg)<=100:
        raise CommandError('Изменение громкости должно быть от 1 до 100 процентных пунктов.')
    import comtypes
    comtypes.CoInitialize()
    try:
        endpoint=get_volume()
        if kind=='pc_mute':
            endpoint.SetMute(int(arg),None)
            return ('Звук выключен.' if arg else 'Звук включён.'), 'Звук'
        current=round(endpoint.GetMasterVolumeLevelScalar()*100)
        if kind=='pc_volume_get': return f'Громкость — {current}%.', 'Громкость'
        target=arg if kind=='pc_volume' else max(0,min(100,current+arg))
        if not 0<=target<=100: raise CommandError('Громкость можно установить от 0 до 100 процентов.')
        endpoint.SetMasterVolumeLevelScalar(target/100,None)
        if target>0: endpoint.SetMute(0,None)
        return f'Громкость установлена на {target}%.', 'Громкость изменена'
    finally:comtypes.CoUninitialize()


def desktop_path():
    if os.name=='nt':
        buf=ctypes.create_unicode_buffer(32768)
        if ctypes.windll.shell32.SHGetFolderPathW(None,0x10,None,0,buf)==0:return Path(buf.value)
    return Path.home()/'Desktop'


def run_pc(command, data_dir):
    kind,arg=command
    if kind=='pc_settings':
        if arg not in SETTINGS:raise CommandError('Эта страница параметров не поддерживается.')
        os.startfile(arg)
        return 'Открываю параметры Windows.', 'Параметры Windows'
    if kind=='pc_app':return f'Открываю {open_app(arg)}.', 'Приложение открыто'
    if kind=='pc_folder':
        if arg not in FOLDERS.values():raise CommandError('Неизвестная папка')
        launch_executable(windows_dir()/'explorer.exe',['shell:'+arg])
        return 'Открываю папку.', 'Папка открыта'
    if kind in ('pc_url','pc_web_search'):
        url='https://www.google.com/search?q='+quote(arg) if kind=='pc_web_search' else arg
        parsed=urlsplit(url)
        if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username:raise CommandError('Нужна корректная ссылка на сайт.')
        if not webbrowser.open(url,new=2):raise CommandError('Не удалось открыть браузер по умолчанию.')
        return ('Открываю результаты поиска.' if kind=='pc_web_search' else 'Открываю сайт.'), 'Браузер'
    if kind.startswith('pc_volume') or kind=='pc_mute':return adjust_volume(kind,arg)
    if kind=='pc_media':
        # WM_APPCOMMAND supports explicit PLAY and PAUSE (not a toggle).
        code={'play':46,'pause':47,'next':11,'previous':12}[arg]
        user32=ctypes.windll.user32
        user32.GetShellWindow.restype=ctypes.c_void_p
        user32.SendMessageW.argtypes=[ctypes.c_void_p,ctypes.c_uint,ctypes.c_size_t,ctypes.c_ssize_t]
        user32.SendMessageW(user32.GetShellWindow(),0x0319,0,code<<16)
        return 'Команда передана медиаплееру. Если музыка не запущена, сначала откройте плеер.', 'Управление воспроизведением'
    if kind in ('pc_desktop','pc_restore'):
        import comtypes.client
        comtypes.CoInitialize()
        try:
            shell=comtypes.client.CreateObject('Shell.Application')
            if kind=='pc_desktop':shell.MinimizeAll()
            else:shell.UndoMinimizeALL()
        finally:comtypes.CoUninitialize()
        return ('Показываю рабочий стол.' if kind=='pc_desktop' else 'Восстанавливаю окна.'), 'Окна'
    if kind=='pc_screenshot':
        from PIL import ImageGrab
        folder=Path(data_dir)/'screenshots';folder.mkdir(exist_ok=True)
        dest=folder/('Снимок-'+datetime.now().strftime('%Y-%m-%d_%H-%M-%S-%f')+'.png')
        ImageGrab.grab(all_screens=True).save(dest)
        return f'Скриншот сохранён: {dest}', 'Скриншот сохранён'
    if kind=='pc_disk':
        usage=shutil.disk_usage(windows_dir().anchor)
        return f'На системном диске свободно {usage.free/1024**3:.1f} ГБ из {usage.total/1024**3:.0f} ГБ.', 'Свободное место'
    if kind=='pc_battery':
        import psutil
        b=psutil.sensors_battery()
        return (f'Заряд батареи — {b.percent:.0f}%. '+('Питание от сети.' if b.power_plugged else 'Питание от батареи.') if b else 'Батарея не обнаружена. Похоже, это стационарный компьютер.'), 'Батарея'
    if kind=='pc_create_folder':
        if not arg or len(arg)>100 or re.search(r'[<>:"/\\|?*\x00-\x1f]',arg) or arg.endswith(('.', ' ')) or arg in ('.','..') or re.match(r'(?i)^(con|prn|aux|nul|com[0-9]|lpt[0-9])(?:\.|$)',arg):
            raise CommandError('Укажите простое название папки без пути и специальных символов.')
        folder=desktop_path()/arg
        if folder.exists():return f'Папка «{arg}» уже существует на рабочем столе.', 'Папка'
        folder.mkdir()
        return f'Создала папку «{arg}» на рабочем столе.', 'Папка создана'
    if kind=='pc_find_file':
        query=arg.strip('«»"').lower().replace('ё','е')
        if len(query)<2:raise CommandError('Назовите хотя бы два символа из имени файла.')
        roots=[desktop_path(),Path.home()/'Documents',Path.home()/'Downloads']
        results=[];started=time.monotonic();scanned=0
        for base in roots:
            if len(results)>=10 or scanned>=15000 or time.monotonic()-started>4:break
            for folder,dirs,files in os.walk(base):
                dirs[:]=[d for d in dirs if not d.startswith('.') and d not in ('node_modules','venv','release','models') and not (Path(folder)/d).is_symlink()]
                for name in files:
                    scanned+=1
                    if query in name.lower().replace('ё','е'):results.append(str(Path(folder)/name))
                    if len(results)>=10 or scanned>=15000 or time.monotonic()-started>4:break
                if len(results)>=10 or scanned>=15000 or time.monotonic()-started>4:break
        suffix=' Поиск ограничен рабочим столом, документами и загрузками; показано до десяти результатов.'
        return ('Найдено:\n'+'\n'.join(results)+suffix if results else 'Не нашла такой файл в просмотренных папках.'+suffix), 'Поиск файлов'
    raise CommandError('Эта команда пока не поддерживается.')
