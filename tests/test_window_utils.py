"""
tests/test_window_utils.py
==========================
Unit tests for the tab-aware window utility (backend/core/window_utils.py).

All Win32 / psutil calls are mocked so these tests run on any platform
(including CI Linux runners) without a real display.
"""

import sys
import types
import unittest
from unittest.mock import MagicMock, patch, call

# ---------------------------------------------------------------------------
# Minimal ctypes / win32 stubs so the module can be imported on non-Windows
# ---------------------------------------------------------------------------

# Stub wintypes.DWORD if not available
if sys.platform != "win32":
    ctypes_stub = types.ModuleType("ctypes")
    ctypes_stub.windll = MagicMock()
    ctypes_stub.create_unicode_buffer = MagicMock(return_value=MagicMock(value=""))
    ctypes_stub.byref = MagicMock()
    ctypes_stub.WINFUNCTYPE = MagicMock(return_value=lambda f: f)
    ctypes_stub.c_bool = MagicMock()

    wintypes_stub = types.ModuleType("ctypes.wintypes")
    wintypes_stub.HWND   = MagicMock()
    wintypes_stub.LPARAM = MagicMock()
    wintypes_stub.DWORD  = MagicMock(return_value=MagicMock(value=1234))

    ctypes_stub.wintypes = wintypes_stub
    sys.modules.setdefault("ctypes", ctypes_stub)
    sys.modules.setdefault("ctypes.wintypes", wintypes_stub)

    # Stub psutil
    psutil_stub = types.ModuleType("psutil")
    psutil_stub.Process = MagicMock()
    sys.modules.setdefault("psutil", psutil_stub)


import backend.core.window_utils as wu  # noqa: E402  (import after stubs)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

class _PsutilProcess:
    """Minimal psutil.Process stand-in that returns a fixed process name."""
    def __init__(self, name: str):
        self._name = name
    def name(self) -> str:
        return self._name


# ---------------------------------------------------------------------------
# Tests: is_browser_process
# ---------------------------------------------------------------------------

class TestIsBrowserProcess(unittest.TestCase):
    """Verify process-name gate correctly classifies executables."""

    def test_known_browsers_accepted(self):
        browsers = [
            "chrome.exe", "msedge.exe", "firefox.exe",
            "brave.exe", "opera.exe", "vivaldi.exe",
        ]
        for proc in browsers:
            with self.subTest(proc=proc):
                self.assertTrue(
                    wu.is_browser_process(proc),
                    f"{proc} should be identified as a browser",
                )

    def test_case_insensitive(self):
        self.assertTrue(wu.is_browser_process("Chrome.EXE"))
        self.assertTrue(wu.is_browser_process("MSEDGE.EXE"))

    def test_non_browsers_rejected(self):
        non_browsers = [
            "code.exe",       # VS Code
            "powershell.exe",
            "cmd.exe",
            "python.exe",
            "notepad.exe",
            "focuslock.exe",
            "devenv.exe",     # Visual Studio
            "explorer.exe",
        ]
        for proc in non_browsers:
            with self.subTest(proc=proc):
                self.assertFalse(
                    wu.is_browser_process(proc),
                    f"{proc} must NOT be identified as a browser",
                )

    def test_empty_string_rejected(self):
        self.assertFalse(wu.is_browser_process(""))

    def test_partial_match_rejected(self):
        # "chrome_helper.exe" is NOT chrome.exe — must be exact
        self.assertFalse(wu.is_browser_process("chrome_helper.exe"))


# ---------------------------------------------------------------------------
# Tests: try_close_active_tab — safety gates
# ---------------------------------------------------------------------------

class TestTryCloseActiveTab(unittest.TestCase):

    def _patch_foreground(self, hwnd: int, title: str, proc_name: str):
        """Return a context-manager stack that patches _get_foreground_window_info."""
        return patch.object(
            wu, "_get_foreground_window_info",
            return_value=(hwnd, title, proc_name),
        )

    # ------------------------------------------------------------------

    def test_non_browser_process_not_closed(self):
        """try_close_active_tab must return False and NOT inject keys for non-browsers."""
        with self._patch_foreground(999, "some document - notepad", "notepad.exe"), \
             patch.object(wu.user32, "keybd_event") as mock_kbd, \
             patch("platform.system", return_value="Windows"):
            result = wu.try_close_active_tab()

        self.assertFalse(result)
        mock_kbd.assert_not_called()

    def test_blocked_process_not_closed(self):
        """VS Code / PowerShell must be hard-blocked even if title looks browser-like."""
        for proc in ("code.exe", "powershell.exe", "python.exe"):
            with self.subTest(proc=proc), \
                 self._patch_foreground(42, "chrome – visual studio code", proc), \
                 patch.object(wu.user32, "keybd_event") as mock_kbd, \
                 patch("platform.system", return_value="Windows"):
                result = wu.try_close_active_tab()

            self.assertFalse(result, f"{proc} must be blocked")
            mock_kbd.assert_not_called()

    def test_browser_tab_close_sends_ctrl_w(self):
        """A Chrome foreground window must receive exactly Ctrl+W (4 keybd_event calls)."""
        _VK_CONTROL     = 0x11
        _VK_W           = 0x57
        _KEYEVENTF_KEYUP = 0x0002

        with self._patch_foreground(1001, "youtube - google chrome", "chrome.exe"), \
             patch.object(wu.user32, "GetForegroundWindow", return_value=1001), \
             patch.object(wu.user32, "keybd_event") as mock_kbd, \
             patch("platform.system", return_value="Windows"):
            result = wu.try_close_active_tab()

        self.assertTrue(result)
        expected_calls = [
            call(_VK_CONTROL, 0, 0,              0),   # Ctrl down
            call(_VK_W,       0, 0,              0),   # W down
            call(_VK_W,       0, _KEYEVENTF_KEYUP, 0), # W up
            call(_VK_CONTROL, 0, _KEYEVENTF_KEYUP, 0), # Ctrl up
        ]
        mock_kbd.assert_has_calls(expected_calls, any_order=False)
        self.assertEqual(mock_kbd.call_count, 4)

    def test_race_condition_guard_aborts_if_hwnd_changed(self):
        """If the foreground window changes between check and inject, abort."""
        with self._patch_foreground(1001, "youtube - google chrome", "chrome.exe"), \
             patch.object(wu.user32, "GetForegroundWindow", return_value=9999), \
             patch.object(wu.user32, "keybd_event") as mock_kbd, \
             patch("platform.system", return_value="Windows"):
            result = wu.try_close_active_tab()

        self.assertFalse(result)
        mock_kbd.assert_not_called()

    def test_returns_false_on_non_windows(self):
        """The function must be a no-op on non-Windows platforms."""
        with patch("platform.system", return_value="Linux"), \
             patch.object(wu.user32, "keybd_event") as mock_kbd:
            result = wu.try_close_active_tab()

        self.assertFalse(result)
        mock_kbd.assert_not_called()

    def test_zero_hwnd_returns_false(self):
        """If GetForegroundWindow returns 0, we must bail immediately."""
        with self._patch_foreground(0, "", ""), \
             patch.object(wu.user32, "keybd_event") as mock_kbd, \
             patch("platform.system", return_value="Windows"):
            result = wu.try_close_active_tab()

        self.assertFalse(result)
        mock_kbd.assert_not_called()


# ---------------------------------------------------------------------------
# Tests: backward-compat alias
# ---------------------------------------------------------------------------

class TestBackwardCompatAlias(unittest.TestCase):

    def test_alias_delegates_to_tab_close(self):
        """try_close_active_window must delegate to try_close_active_tab."""
        with patch.object(wu, "try_close_active_tab", return_value=True) as mock_tab:
            result = wu.try_close_active_window()

        mock_tab.assert_called_once()
        self.assertTrue(result)


# ---------------------------------------------------------------------------

if __name__ == "__main__":
    unittest.main()
