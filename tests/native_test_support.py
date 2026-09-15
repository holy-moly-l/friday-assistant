"""Give our own test window real mouse focus, without weakening the application's focus guard."""
import ctypes as c
from ctypes import wintypes as w
import threading
import desktop_native as n


def activate_fixture(window):
    n.same(window)
    cls=c.create_unicode_buffer(256);n.u.GetClassNameW(window['hwnd'],cls,len(cls))
    assert cls.value=='FridaySafeFixture'
    n.u.SetWindowPos(window['hwnd'],-1,0,0,0,0,0x13)
    r=n.same(window)['rect'];x=r[0]+80;y=r[1]+15
    n.u.WindowFromPoint.argtypes=[w.POINT];n.u.WindowFromPoint.restype=w.HWND
    n.u.GetAncestor.argtypes=[w.HWND,w.UINT];n.u.GetAncestor.restype=w.HWND
    assert n.u.GetAncestor(n.u.WindowFromPoint(w.POINT(x,y)),2)==window['hwnd']
    n.u.SetCursorPos(x,y);n.u.mouse_event(2,0,0,0,0);n.u.mouse_event(4,0,0,0,0)
    assert n.wait_for(lambda:n.u.GetForegroundWindow()==window['hwnd'],threading.Event())
