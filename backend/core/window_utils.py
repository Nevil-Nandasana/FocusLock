"""
WindowUtils — Safe OS Window interactions
=========================================
Design contract (safe by design):
  1. Close ONLY the active TAB inside a browser — never the whole window.
  2. Identify browsers by process name, not window title (title changes per tab).
  3. If close is impossible or unsafe → just bring FocusLock to front.
  4. NEVER force-kill processes.
  5. Always allow user override.

Implementation notes
--------------------
``try_close_active_tab()`` injects a ``Ctrl+W`` keystroke via ``keybd_event``.
This is the universal "close current tab" shortcut supported by Chrome, Edge,
Firefox, Brave, Opera, and all Chromium derivatives.  It closes *only* the
foreground tab; if the window has exactly one tab it closes the window too —
which is the desired behaviour and identical to what WM_CLOSE did before.

The old ``try_close_active_window()`` (which sent WM_CLOSE to the HWND) is
retained as a thin alias for call-sites that haven't been updated yet, but it
now delegates to the tab-aware implementation.
"""
import ctypes
import logging
import platform

log = logging.getLogger(__name__)


def _user32():
    """Lazy accessor for the Windows user32 DLL handle.

    Returns the handle on Windows; returns None on every other platform.
    Deferred so that importing this module on Linux / macOS does not raise
    ``AttributeError: module 'ctypes' has no attribute 'windll'``.
    """
    if platform.system() != "Windows":
        return None
    from ctypes import wintypes  # noqa: F401 — imported for side-effects / callers
    return ctypes.windll.user32

# Virtual-key codes used for Ctrl+W injection
_VK_CONTROL = 0x11
_VK_W       = 0x57
_KEYEVENTF_KEYUP = 0x0002

SW_RESTORE = 9

# ── Safety gates ──────────────────────────────────────────────────────────────

# Process names of browser executables (all lower-case).
# These are the ONLY processes for which we will attempt a tab close.
BROWSER_PROCESSES: frozenset[str] = frozenset({
    "chrome.exe",
    "msedge.exe",
    "firefox.exe",
    "brave.exe",
    "opera.exe",
    "vivaldi.exe",
    "waterfox.exe",
    "thorium.exe",
})

# Process-name fragments that must NEVER be touched regardless of any other
# check.  Matched as substrings of the lower-cased process name.
_BLOCKED_PROCESS_FRAGMENTS: tuple[str, ...] = (
    "focuslock",
    "code",          # VS Code / VSCodium
    "powershell",
    "cmd",
    "python",
    "java",
    "node",
    "devenv",        # Visual Studio
)


def is_browser_process(app_name: str) -> bool:
    """Return True iff *app_name* (psutil process name) is a known browser.

    Matching is done on the lower-cased process name against the
    ``BROWSER_PROCESSES`` set, so it is immune to window-title changes.
    """
    return app_name.lower() in BROWSER_PROCESSES


def _is_blocked_process(app_name: str) -> bool:
    """Return True if this process must never be touched (hard block)."""
    name = app_name.lower()
    return any(frag in name for frag in _BLOCKED_PROCESS_FRAGMENTS)


# ── Window helpers ────────────────────────────────────────────────────────────

def _get_foreground_window_info() -> tuple[int, str, str]:
    """Return (hwnd, title_lower, process_name_lower) for the foreground window.

    Returns (0, '', '') on any failure.
    """
    import psutil
    from ctypes import wintypes

    u32 = _user32()
    if u32 is None:
        return 0, "", ""

    try:
        hwnd = u32.GetForegroundWindow()
        if not hwnd:
            return 0, "", ""

        # Title
        length = u32.GetWindowTextLengthW(hwnd)
        buff   = ctypes.create_unicode_buffer(length + 1)
        u32.GetWindowTextW(hwnd, buff, length + 1)
        title = buff.value.lower()

        # Process name
        pid = wintypes.DWORD()
        u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        try:
            proc_name = psutil.Process(pid.value).name().lower()
        except Exception:
            proc_name = ""

        return hwnd, title, proc_name

    except Exception as exc:
        log.debug("[WindowUtils] _get_foreground_window_info error: %s", exc)
        return 0, "", ""


def get_window_title(hwnd: int) -> str:
    """Return the lower-cased title of *hwnd*."""
    u32 = _user32()
    if u32 is None:
        return ""
    length = u32.GetWindowTextLengthW(hwnd)
    buff   = ctypes.create_unicode_buffer(length + 1)
    u32.GetWindowTextW(hwnd, buff, length + 1)
    return buff.value.lower()


# ── Tab-aware close ───────────────────────────────────────────────────────────

def try_close_active_tab() -> bool:
    """Inject Ctrl+W into the foreground browser window to close the active tab.

    Safety contract:
    - Only acts on processes listed in ``BROWSER_PROCESSES`` (process-name gate).
    - Refuses to act on processes matching ``_BLOCKED_PROCESS_FRAGMENTS``.
    - Verifies the HWND is still foreground immediately before keystroke
      injection to guard against the race where the user alt-tabs away.
    - Falls back to False (no action) if any guard fails.

    Returns True if the keystroke was injected, False otherwise.
    """
    if platform.system() != "Windows":
        return False

    hwnd, title, proc_name = _get_foreground_window_info()
    if not hwnd:
        return False

    # Hard block: never touch IDEs, terminals, FocusLock itself, etc.
    if _is_blocked_process(proc_name):
        log.info("[Recovery] Skip close — blocked process: %s", proc_name)
        return False

    # Process-name gate: only browsers get a tab close
    if not is_browser_process(proc_name):
        log.info("[Recovery] Skip close — not a browser process: %s", proc_name)
        return False

    # Race-condition guard: re-check that the same HWND is still foreground.
    # If the user alt-tabbed in the ~1 ms since our first check, abort.
    u32 = _user32()
    if u32 is None:
        return False
    current_hwnd = u32.GetForegroundWindow()
    if current_hwnd != hwnd:
        log.info(
            "[Recovery] Skip close — foreground changed (was %s, now %s)",
            hwnd, current_hwnd,
        )
        return False

    # Inject Ctrl+W — close current tab only.
    try:
        u32.keybd_event(_VK_CONTROL, 0, 0,              0)  # Ctrl down
        u32.keybd_event(_VK_W,       0, 0,              0)  # W down
        u32.keybd_event(_VK_W,       0, _KEYEVENTF_KEYUP, 0)  # W up
        u32.keybd_event(_VK_CONTROL, 0, _KEYEVENTF_KEYUP, 0)  # Ctrl up
        log.info(
            "[Recovery] Ctrl+W sent to browser tab — process=%s title=%.60s",
            proc_name, title,
        )
        return True
    except Exception as exc:
        log.error("[Recovery] keybd_event failed: %s", exc)
        return False


# ── Backward-compat alias ─────────────────────────────────────────────────────

def try_close_active_window() -> bool:
    """Deprecated alias for ``try_close_active_tab()``.

    .. deprecated::
        Use ``try_close_active_tab()`` directly.  This alias exists only to
        avoid breaking any call-site that was not updated alongside this
        refactor.  It delegates fully to the tab-aware implementation.
    """
    log.debug("[Recovery] try_close_active_window() called — delegating to try_close_active_tab()")
    return try_close_active_tab()


# ── Focus FocusLock ──────────────────────────────────────────────────────────

def focus_focuslock() -> bool:
    """Reliably bring the FocusLock browser/UI window to front."""
    if platform.system() != "Windows":
        return False

    from ctypes import wintypes

    u32 = _user32()
    if u32 is None:
        return False

    target_hwnd = None

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    def enum_proc(hwnd, lParam):
        nonlocal target_hwnd
        if u32.IsWindowVisible(hwnd):
            title = get_window_title(hwnd)
            if "focuslock" in title:
                target_hwnd = hwnd
                return False  # stop enumeration
        return True

    try:
        u32.EnumWindows(enum_proc, 0)

        if target_hwnd:
            foreground    = u32.GetForegroundWindow()
            current_tid   = u32.GetWindowThreadProcessId(foreground, None)
            target_tid    = u32.GetWindowThreadProcessId(target_hwnd, None)

            u32.AttachThreadInput(current_tid, target_tid, True)
            u32.ShowWindow(target_hwnd, SW_RESTORE)
            u32.SetForegroundWindow(target_hwnd)
            u32.AttachThreadInput(current_tid, target_tid, False)

            log.info("[Recovery] FocusLock window brought to front.")
            return True

    except Exception as exc:
        log.error("[Recovery] focus_focuslock failed: %s", exc)

    return False
