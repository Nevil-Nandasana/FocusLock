"""
WindowUtils - Safe OS Window interactions
=========================================
1. Attempt to close ONLY the active window (best-effort)
2. If closing fails → just bring FocusLock to front
3. NEVER force kill processes
4. Always allow user override
"""
import ctypes
import platform
import logging

log = logging.getLogger(__name__)

def try_close_active_window():
    """Attempts to close the current active foreground window using WM_CLOSE."""
    if platform.system() != "Windows":
        return False
        
    try:
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        if hwnd:
            # WM_CLOSE = 0x0010
            ctypes.windll.user32.PostMessageW(hwnd, 0x0010, 0, 0)
            log.info(f"[Recovery] Sent WM_CLOSE to active window handle: {hwnd}")
            return True
    except Exception as e:
        log.error(f"[Recovery] Failed to close active window: {e}")
    return False

def focus_focuslock():
    """Brings FocusLock application to front."""
    if platform.system() != "Windows":
        return False
        
    try:
        EnumWindows = ctypes.windll.user32.EnumWindows
        EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int))
        GetWindowText = ctypes.windll.user32.GetWindowTextW
        GetWindowTextLength = ctypes.windll.user32.GetWindowTextLengthW
        IsWindowVisible = ctypes.windll.user32.IsWindowVisible

        target_hwnd = None

        def foreach_window(hwnd, lParam):
            nonlocal target_hwnd
            if IsWindowVisible(hwnd):
                length = GetWindowTextLength(hwnd)
                buff = ctypes.create_unicode_buffer(length + 1)
                GetWindowText(hwnd, buff, length + 1)
                title = buff.value.lower()
                # Assuming browser title contains FocusLock. Exclude self IDE/CMD if developing and running this. 
                if "focuslock" in title and "visual studio" not in title and "cmd" not in title and "powershell" not in title:
                    target_hwnd = hwnd
                    return False
            return True

        EnumWindows(EnumWindowsProc(foreach_window), 0)
        
        if target_hwnd:
            ctypes.windll.user32.ShowWindow(target_hwnd, 9) # SW_RESTORE
            ctypes.windll.user32.SetForegroundWindow(target_hwnd)
            log.info(f"[Recovery] Focused FocusLock window handle: {target_hwnd}")
            return True
    except Exception as e:
        log.error(f"[Recovery] Failed to focus FocusLock: {e}")
    return False
