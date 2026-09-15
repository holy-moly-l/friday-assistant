"""Own disposable native window; no user's applications or data are used."""
import ctypes as c
from ctypes import wintypes as w
import json
import os
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from lifecycle import follow_parent
follow_parent(os.environ.get('FRIDAY_TEST_PARENT_PID',str(os.getppid())))
u=c.WinDLL('user32',use_last_error=True);k=c.WinDLL('kernel32',use_last_error=True)
PROC=c.WINFUNCTYPE(c.c_ssize_t,w.HWND,w.UINT,w.WPARAM,w.LPARAM)
class WNDCLASS(c.Structure):
    _fields_=[('style',w.UINT),('lpfnWndProc',PROC),('cbClsExtra',c.c_int),('cbWndExtra',c.c_int),('hInstance',w.HINSTANCE),('hIcon',w.HICON),('hCursor',w.HANDLE),('hbrBackground',w.HBRUSH),('lpszMenuName',w.LPCWSTR),('lpszClassName',w.LPCWSTR)]
u.DefWindowProcW.argtypes=[w.HWND,w.UINT,w.WPARAM,w.LPARAM];u.DefWindowProcW.restype=c.c_ssize_t
u.CreateWindowExW.argtypes=[w.DWORD,w.LPCWSTR,w.LPCWSTR,w.DWORD,c.c_int,c.c_int,c.c_int,c.c_int,w.HWND,w.HMENU,w.HINSTANCE,w.LPVOID];u.CreateWindowExW.restype=w.HWND
u.SetWindowTextW.argtypes=[w.HWND,w.LPCWSTR];u.SetFocus.argtypes=[w.HWND];u.ShowWindow.argtypes=[w.HWND,c.c_int]
k.GetModuleHandleW.argtypes=[w.LPCWSTR];k.GetModuleHandleW.restype=w.HMODULE
status=None;count=0;clock_label=None;ticks=0
@PROC
def proc(hwnd,msg,wp,lp):
    global count,ticks
    if msg==0x113 and clock_label:
        ticks+=1;u.SetWindowTextW(clock_label,f'Часы {ticks%60:02}');return 0
    if msg==0x111 and wp&0xffff in (101,102,105):
        count+=1;u.SetWindowTextW(status,f'Шаг выполнен: {count}');return 0
    if msg==2:u.PostQuitMessage(0);return 0
    return u.DefWindowProcW(hwnd,msg,wp,lp)
instance=k.GetModuleHandleW(None);wc=WNDCLASS();wc.lpfnWndProc=proc;wc.hInstance=instance;wc.hbrBackground=6;wc.lpszClassName='FridaySafeFixture'
u.RegisterClassW(c.byref(wc))
hwnd=u.CreateWindowExW(0,wc.lpszClassName,os.environ.get('FRIDAY_FIXTURE_TITLE','Friday Desktop Fixture'),0x10CF0000,100,100,650,420,None,None,instance,None)
def child(typ,name,x,y,width,height,id,extra=0):
    return u.CreateWindowExW(0,typ,name,0x50010000|extra,x,y,width,height,hwnd,id,instance,None)
child('STATIC','Тестовое окно Пятницы. Никаких реальных отправок.',20,20,590,40,100)
child('BUTTON','Продолжить',20,80,180,40,101)
child('BUTTON','Отправить',220,80,180,40,102)
child('BUTTON','Назад',420,80,150,40,105)
edit=child('EDIT','',20,150,570,40,103,0x00800000)
status=child('STATIC',os.environ.get('FRIDAY_FIXTURE_STATUS','Ошибка 810: тестовый документ не найден'),20,220,590,50,104)
if os.environ.get('FRIDAY_FIXTURE_ANIMATION')=='1':
    clock_label=child('STATIC','Часы 00',500,325,120,30,106)
    u.SetTimer.argtypes=[w.HWND,c.c_size_t,w.UINT,c.c_void_p]
    u.SetTimer(hwnd,1,250,None)
u.SetFocus(edit)
Path(sys.argv[1]).write_text(json.dumps({'hwnd':hwnd,'pid':os.getpid()}),encoding='utf-8')
msg=w.MSG()
u.IsDialogMessageW.argtypes=[w.HWND,c.POINTER(w.MSG)]
while u.GetMessageW(c.byref(msg),None,0,0)>0:
    if not u.IsDialogMessageW(hwnd,c.byref(msg)):
        u.TranslateMessage(c.byref(msg));u.DispatchMessageW(c.byref(msg))
