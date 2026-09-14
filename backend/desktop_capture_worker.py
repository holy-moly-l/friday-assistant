"""One-shot PrintWindow, isolated because window providers can block indefinitely."""
import base64
import ctypes as c
from ctypes import wintypes as w
import io
import json
import os
import sys
from lifecycle import follow_parent

follow_parent(os.environ.get('FRIDAY_CAPTURE_PARENT_PID'))


def capture(window):
    from desktop_native import u, same
    from PIL import Image
    current = same(window)
    rect = current['rect']
    width, height = rect[2]-rect[0], rect[3]-rect[1]
    if current['minimized'] or not (0 < width <= 16384 and 0 < height <= 16384 and width*height<=32000000):
        raise ValueError('Окно свёрнуто или его размер недоступен.')
    g = c.WinDLL('gdi32', use_last_error=True)
    for dll, name, args, result in [
        (u, 'GetWindowDC', [w.HWND], w.HDC),
        (u, 'ReleaseDC', [w.HWND, w.HDC], c.c_int),
        (u, 'PrintWindow', [w.HWND, w.HDC, w.UINT], w.BOOL),
        (g, 'CreateCompatibleDC', [w.HDC], w.HDC),
        (g, 'CreateCompatibleBitmap', [w.HDC, c.c_int, c.c_int], w.HBITMAP),
        (g, 'SelectObject', [w.HDC, w.HANDLE], w.HANDLE),
        (g, 'DeleteObject', [w.HANDLE], w.BOOL),
        (g, 'DeleteDC', [w.HDC], w.BOOL),
        (g, 'GetDIBits', [w.HDC, w.HBITMAP, w.UINT, w.UINT, c.c_void_p, c.c_void_p, w.UINT], c.c_int),
    ]:
        fn = getattr(dll, name); fn.argtypes = args; fn.restype = result
    class Header(c.Structure):
        _fields_ = [('size', w.DWORD), ('width', w.LONG), ('height', w.LONG),
                    ('planes', w.WORD), ('bits', w.WORD), ('compression', w.DWORD),
                    ('image_size', w.DWORD), ('xppm', w.LONG), ('yppm', w.LONG),
                    ('colors', w.DWORD), ('important', w.DWORD)]
    dc = u.GetWindowDC(window['hwnd']); memory = None; bitmap = None; previous = None
    try:
        if not dc: raise ValueError('Windows не предоставила изображение окна.')
        memory = g.CreateCompatibleDC(dc); bitmap = g.CreateCompatibleBitmap(dc, width, height)
        if not memory or not bitmap: raise ValueError('Не удалось выделить память для снимка.')
        previous = g.SelectObject(memory, bitmap)
        # PW_RENDERFULLCONTENT captures the window even when another app covers it.
        if not u.PrintWindow(window['hwnd'], memory, 2):
            raise ValueError('Приложение не поддерживает снимок своего окна. Попробуйте снимок монитора.')
        g.SelectObject(memory, previous); previous = None
        header = Header(c.sizeof(Header), width, -height, 1, 32, 0, 0, 0, 0, 0, 0)
        pixels = c.create_string_buffer(width * height * 4)
        if g.GetDIBits(memory, bitmap, 0, height, pixels, c.byref(header), 0) != height:
            raise ValueError('Windows не вернула пиксели окна.')
        im = Image.frombytes('RGB', (width, height), pixels.raw, 'raw', 'BGRX')
        if all(low == high for low, high in im.getextrema()):
            raise ValueError('Получен пустой снимок окна. Приложение может блокировать захват; попробуйте снимок монитора.')
        if same(window)['rect'] != rect: raise ValueError('Окно переместилось во время снимка. Повторите запрос.')
        im.thumbnail((1920, 1440)); buf = io.BytesIO(); im.save(buf, format='PNG')
        return dict(image=base64.b64encode(buf.getvalue()).decode('ascii'), rect=rect,
                    size=list(im.size), original_size=[width, height], scope='window',
                    target={'hwnd':window['hwnd'], 'title':current['title']}, method='PrintWindow')
    finally:
        if previous: g.SelectObject(memory, previous)
        if bitmap: g.DeleteObject(bitmap)
        if memory: g.DeleteDC(memory)
        if dc: u.ReleaseDC(window['hwnd'], dc)


if __name__ == '__main__':
    try: result = capture(json.loads(sys.stdin.buffer.read().decode('utf-8')))
    except Exception as exc: result = {'error':str(exc)}
    sys.stdout.buffer.write(json.dumps(result, ensure_ascii=False).encode('utf-8'))
