"""Capture only the KOMPAS window; never silently return another app's pixels."""
import ctypes
from ctypes import wintypes
from io import BytesIO


def capture_window(hwnd: int, max_size=(1920,1080)) -> bytes:
    import win32gui
    import win32ui
    from PIL import Image

    if not win32gui.IsWindow(hwnd) or win32gui.IsIconic(hwnd):
        raise RuntimeError("Окно КОМПАС недоступно или свёрнуто. Разверните его.")
    left, top, right, bottom = win32gui.GetWindowRect(hwnd)
    width, height = right-left, bottom-top
    if width <= 0 or height <= 0:
        raise RuntimeError("Пустое окно")
    source_handle = win32gui.GetWindowDC(hwnd)
    source = win32ui.CreateDCFromHandle(source_handle)
    memory = source.CreateCompatibleDC()
    bitmap = win32ui.CreateBitmap()
    bitmap.CreateCompatibleBitmap(source, width, height)
    old = memory.SelectObject(bitmap)
    try:
        print_window = ctypes.windll.user32.PrintWindow
        print_window.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]
        print_window.restype = wintypes.BOOL
        if not print_window(hwnd, memory.GetSafeHdc(), 2) and not print_window(hwnd, memory.GetSafeHdc(), 0):
            raise RuntimeError("PrintWindow не смог захватить КОМПАС")
        image = Image.frombuffer("RGB", (width, height), bitmap.GetBitmapBits(True),
                                 "raw", "BGRX", 0, 1)
        if not image.getbbox():
            raise RuntimeError("КОМПАС вернул чёрный снимок. Разверните окно и повторите.")
        if max_size:
            image.thumbnail(max_size)
        out = BytesIO()
        image.save(out, format="PNG")
        return out.getvalue()
    finally:
        memory.SelectObject(old)
        win32gui.DeleteObject(bitmap.GetHandle())
        memory.DeleteDC()
        source.DeleteDC()
        win32gui.ReleaseDC(hwnd, source_handle)
