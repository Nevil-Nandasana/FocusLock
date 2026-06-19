"""
WindowMonitor — Active Window State Detector
=============================================
Polls the Windows foreground window every second and fires a callback
only when the active window changes (debounced on hash).

Improvements over original:
  • Auto-restart watchdog: consecutive error counter; if 3 errors fire
    back-to-back, the loop logs a CRITICAL and resets (keeps running).
  • All print() replaced with logging.getLogger(__name__).
  • Windows-only guard retained.
"""

from __future__ import annotations

import ctypes
import logging
import platform
import threading
import time
from ctypes import wintypes

import psutil

log = logging.getLogger(__name__)

# Maximum consecutive errors before the watchdog resets the error counter
# and logs a CRITICAL. The thread never stops — it resets and keeps watching.
_MAX_CONSECUTIVE_ERRORS = 3


class WindowMonitor:
    """
    Monitor Layer: Extracts raw state (Window Title, App Name).
    Emits an event ONLY when the active state changes.
    Does NOT contain classification logic.
    """

    def __init__(self, callback_state_change=None):
        if platform.system() != "Windows":
            raise NotImplementedError(
                f"WindowMonitor is only supported on Windows. "
                f"Current platform: {platform.system()}"
            )

        self.callback_state_change = callback_state_change
        self.running               = False
        self.thread: threading.Thread | None = None
        self.last_state_hash       = None

        # Load Windows API
        self.user32 = ctypes.windll.user32
        self.user32.GetForegroundWindow.restype = wintypes.HWND
        self.user32.GetWindowThreadProcessId.restype = wintypes.DWORD

    # ── Window Info ───────────────────────────────────────────────────────────

    def _get_active_window_info(self) -> tuple[int, str, str]:
        try:
            hwnd = self.user32.GetForegroundWindow()
            if not hwnd:
                return 0, "", "Unknown"

            # Title
            length = self.user32.GetWindowTextLengthW(hwnd)
            buff   = ctypes.create_unicode_buffer(length + 1)
            self.user32.GetWindowTextW(hwnd, buff, length + 1)
            title = buff.value

            # Process name
            pid = wintypes.DWORD()
            self.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            try:
                app_name = psutil.Process(pid.value).name()
            except Exception:
                app_name = "Unknown"

            return hwnd, title, app_name

        except Exception as e:
            log.debug("[WindowMonitor] _get_active_window_info error: %s", e)
            return 0, "", "Unknown"

    # ── Monitor Loop with Auto-Restart Watchdog ────────────────────────────────

    def _monitor_loop(self):
        consecutive_errors = 0

        while self.running:
            try:
                hwnd, title, app_name = self._get_active_window_info()

                # Skip OS-level overlays
                if title in ("Task Switching", "Task View", "Program Manager"):
                    time.sleep(1)
                    consecutive_errors = 0
                    continue

                from backend.core.tab_url_scraper import scrape_browser_tab_url_safe
                url = scrape_browser_tab_url_safe(hwnd, app_name)

                state      = {"title": title, "app": app_name, "url": url}
                state_hash = f"{title}_{app_name}_{url}"

                if state_hash != self.last_state_hash:
                    self.last_state_hash = state_hash
                    if self.callback_state_change:
                        self.callback_state_change(state)

                consecutive_errors = 0   # reset on clean iteration
                time.sleep(1)

            except Exception as e:
                consecutive_errors += 1
                log.error(
                    "[WindowMonitor] Error in monitor loop (#%d): %s",
                    consecutive_errors, e,
                )

                if consecutive_errors >= _MAX_CONSECUTIVE_ERRORS:
                    log.critical(
                        "[WindowMonitor] %d consecutive errors — watchdog "
                        "resetting error counter and continuing.",
                        consecutive_errors,
                    )
                    consecutive_errors = 0

                time.sleep(1)

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def start(self):
        if self.running:
            return
        self.running = True
        self.thread  = threading.Thread(
            target=self._monitor_loop,
            name="focuslock-monitor",
            daemon=True,
        )
        self.thread.start()
        log.info("[WindowMonitor] Started.")

    def stop(self):
        self.running = False
        if self.thread:
            self.thread.join(timeout=2.0)
        log.info("[WindowMonitor] Stopped.")
