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
from ctypes import wintypes

log = logging.getLogger(__name__)

user32 = ctypes.windll.user32

WM_CLOSE = 0x0010
SW_RESTORE = 9

SAFE_KEYWORDS = ["chrome", "brave", "edge", "youtube", "netflix"]
BLOCKED_KEYWORDS = ["visual studio", "cmd", "powershell", "focuslock"]


def get_window_title(hwnd):
    length = user32.GetWindowTextLengthW(hwnd)
    buff = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buff, length + 1)
    return buff.value.lower()


def is_safe_to_close(title):
    """Only allow closing known distraction-type windows."""
    if any(bad in title for bad in BLOCKED_KEYWORDS):
        return False
    return any(ok in title for ok in SAFE_KEYWORDS)


def try_close_active_window():
    """Safely attempts to close current window."""
    if platform.system() != "Windows":
        return False

    try:
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return False

        title = get_window_title(hwnd)

        # Safety check
        if not is_safe_to_close(title):
            log.info(f"[Recovery] Skip close (unsafe): {title}")
            return False

        user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
        log.info(f"[Recovery] Closed window: {title}")
        return True

    except Exception as e:
        log.error(f"[Recovery] Close failed: {e}")
        return False


def focus_focuslock():
    """Reliably bring FocusLock to front."""
    if platform.system() != "Windows":
        return False

    target_hwnd = None

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    def enum_proc(hwnd, lParam):
        nonlocal target_hwnd

        if user32.IsWindowVisible(hwnd):
            title = get_window_title(hwnd)

            if "focuslock" in title and not any(x in title for x in BLOCKED_KEYWORDS):
                target_hwnd = hwnd
                return False

        return True

    try:
        user32.EnumWindows(enum_proc, 0)

        if target_hwnd:
            # Trick: attach thread input to bypass focus restrictions
            foreground = user32.GetForegroundWindow()

            current_thread = user32.GetWindowThreadProcessId(foreground, None)
            target_thread = user32.GetWindowThreadProcessId(target_hwnd, None)

            user32.AttachThreadInput(current_thread, target_thread, True)

            user32.ShowWindow(target_hwnd, SW_RESTORE)
            user32.SetForegroundWindow(target_hwnd)

            user32.AttachThreadInput(current_thread, target_thread, False)

            log.info(f"[Recovery] Focused FocusLock window")
            return True

    except Exception as e:
        log.error(f"[Recovery] Focus failed: {e}")

    return False
