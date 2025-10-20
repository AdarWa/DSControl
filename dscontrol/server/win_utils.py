import ctypes
import logging
import win32gui
import win32con
import win32com.client

def get_taskbar_rect():
    class RECT(ctypes.Structure):
        _fields_ = [
            ("left", ctypes.c_long),
            ("top", ctypes.c_long),
            ("right", ctypes.c_long),
            ("bottom", ctypes.c_long)
        ]

    class APPBARDATA(ctypes.Structure):
        _fields_ = [
            ("cbSize", ctypes.c_ulong),
            ("hWnd", ctypes.c_void_p),
            ("uCallbackMessage", ctypes.c_uint),
            ("uEdge", ctypes.c_uint),
            ("rc", RECT),
            ("lParam", ctypes.c_long)
        ]

    SHAppBarMessage = ctypes.windll.shell32.SHAppBarMessage
    ABM_GETTASKBARPOS = 0x00000005

    abd = APPBARDATA()
    abd.cbSize = ctypes.sizeof(APPBARDATA)
    res = SHAppBarMessage(ABM_GETTASKBARPOS, ctypes.byref(abd))

    if not res:
        return None  # Taskbar not found

    rect = abd.rc
    return rect.left, rect.top, rect.right, rect.bottom, abd.uEdge


def get_taskbar_size():
    rect = get_taskbar_rect()
    if not rect:
        return 0

    left, top, right, bottom, edge = rect
    width = right - left
    height = bottom - top

    # edge 0=left, 1=top, 2=right, 3=bottom
    if edge in (1, 3):  # top or bottom
        return height
    else:  # left or right
        return width
    
def get_screen_size():
    user32 = ctypes.windll.user32
    user32.SetProcessDPIAware()
    return (user32.GetSystemMetrics(0),user32.GetSystemMetrics(1))

def activate_driverstation_window():
    """
    Finds the first window whose title contains "DriverStation"
    and brings it to the foreground.
    """
    def enum_callback(hwnd, result):
        if win32gui.IsWindowVisible(hwnd):
            title = win32gui.GetWindowText(hwnd)
            if "DriverStation" in title:
                result.append(hwnd)

    windows = []
    win32gui.EnumWindows(enum_callback, windows)

    if not windows:
        logging.warning("No DriverStation window found.")
        return False

    hwnd = windows[0]

    # Sometimes SetForegroundWindow fails due to Windows focus rules
    shell = win32com.client.Dispatch("WScript.Shell")
    shell.SendKeys('%')  # send Alt to allow SetForegroundWindow

    win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)  # restore if minimized
    win32gui.SetForegroundWindow(hwnd)
    logging.debug(f"Activated window: {win32gui.GetWindowText(hwnd)}")
    return True