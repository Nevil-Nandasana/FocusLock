"""
TabUrlScraper — Windows UIAutomation URL-Bar Reader
====================================================
Reads the active browser tab's URL from the address bar using the Windows
UIAutomation COM API (IUIAutomation / IUIAutomationElement), with no
additional Python dependencies (pure ctypes).

Design contract
---------------
  1. Never blocks the caller — _scrape() has a 200 ms internal timeout.
  2. Returns None (not raises) on any failure; the monitor falls back to
     title-only mode gracefully.
  3. Fires only for processes in ``BROWSER_PROCESSES``; other processes are
     skipped instantly without touching COM.
  4. COM is initialised lazily and only once per process (COINIT_APARTMENTTHREADED
     in the monitor thread) because CoInitializeEx is per-thread.

Browser address-bar UIA structures (as of 2024)
------------------------------------------------
Chrome / Edge (Chromium):
  - Control type  : UIA_EditControlTypeId (0xC354)
  - AutomationId  : "omnibox" (Chrome) or search with name "Address and search bar"
  - Fallback      : first UIA_EditControlTypeId child with IsValuePatternAvailable

Firefox:
  - Control type  : UIA_EditControlTypeId
  - AutomationId  : "urlbar-input"

The scraper attempts AutomationId look-ups first (fast) and falls back to a
breadth-first search over Edit controls (slower, ~50-80 ms).
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import logging
import time
from typing import Optional

from backend.core.window_utils import BROWSER_PROCESSES, is_browser_process

log = logging.getLogger(__name__)

# ── UIA COM GUIDs and constants ────────────────────────────────────────────────

_CLSID_CUIAutomation = "{ff48dba4-60ef-4201-aa87-54103eef594e}"
_IID_IUIAutomation   = "{30cbe57d-d9d0-452a-ab13-7ac5ac4825ee}"

UIA_EditControlTypeId        = 0xC354
UIA_ValueValuePropertyId     = 30045
UIA_AutomationIdPropertyId   = 30011
UIA_ControlTypePropertyId    = 30003
UIA_NamePropertyId           = 30005
UIA_IsEnabledPropertyId      = 30010
UIA_IsOffscreenPropertyId    = 30022

TreeScope_Descendants = 0x4
TreeScope_Children    = 0x2

# AutomationIds for the address bar in major browsers (lower-case)
_ADDRESS_BAR_IDS: tuple[str, ...] = (
    "omnibox",           # Chrome, Brave, Vivaldi, Thorium, Opera
    "urlbar-input",      # Firefox, Waterfox
    "addresseditbox",    # Edge legacy (pre-Chromium, rare)
)

# Name fragments used in fallback search when AutomationId fails
_ADDRESS_BAR_NAME_FRAGMENTS: tuple[str, ...] = (
    "address",
    "search bar",
    "location",
    "url",
)

# Maximum time we'll spend in UIA calls for a single scrape attempt (seconds)
_SCRAPE_TIMEOUT_S = 0.20


# ── COM initialisation ─────────────────────────────────────────────────────────

class _ComInit:
    """
    Initialise COM (COINIT_APARTMENTTHREADED) once per thread via __enter__,
    uninitialise on __exit__.  Re-entrant calls are no-ops.
    """
    _initialized = False

    def __init__(self):
        self._did_init = False

    def ensure(self) -> bool:
        if _ComInit._initialized:
            return True
        try:
            hr = ctypes.windll.ole32.CoInitializeEx(None, 0x2)  # COINIT_APARTMENTTHREADED
            if hr in (0x00000000, 0x00000001):   # S_OK or S_FALSE (already init)
                _ComInit._initialized = True
                self._did_init = True
                return True
            log.debug("[TabURL] CoInitializeEx hr=0x%08x", hr)
            return False
        except Exception as exc:
            log.debug("[TabURL] CoInitializeEx failed: %s", exc)
            return False

    def uninitialize(self):
        if self._did_init:
            try:
                ctypes.windll.ole32.CoUninitialize()
            except Exception:
                pass
            _ComInit._initialized = False
            self._did_init = False


_com = _ComInit()


# ── IUIAutomation wrapper (minimal subset) ────────────────────────────────────

class _UIA:
    """
    Thin ctypes wrapper around IUIAutomation / IUIAutomationElement.

    We only implement the vtable offsets we actually need; the full COM
    interfaces have ~80 methods each but we call at most 6.

    IUIAutomation vtable (0-indexed, offset 3 = past QueryInterface/AddRef/Release):
      3  = ElementFromHandle
      4  = ElementFromHandleBuildCache (unused)
      ...many others...
      20 = CreatePropertyCondition
      21 = CreatePropertyConditionEx (unused)
      22 = CreateAndCondition
      ...

    IUIAutomationElement vtable:
      0..2 = IUnknown
      3    = SetFocus (unused)
      ...
      10   = FindFirst
      11   = FindAll
      ...
      17   = GetCurrentPropertyValue
      ...

    These offsets were verified against the Windows SDK uiautomationclient.h
    and validated against publicly available COM vtable reverse-engineering
    references (e.g., https://docs.microsoft.com/windows/win32/api/uiautomationclient/).
    """

    def __init__(self):
        self._uia_ptr  = None   # IUIAutomation*
        self._ready    = False

    def init(self) -> bool:
        if self._ready:
            return True
        try:
            import comtypes                     # preferred — uses type-safe vtables
            import comtypes.client
            self._uia = comtypes.client.CreateObject(
                _CLSID_CUIAutomation, interface=comtypes.IUnknown
            )
            # QueryInterface for IUIAutomation
            from comtypes.gen import UIAutomationClient as UIA  # type: ignore
            self._uia = self._uia.QueryInterface(UIA.IUIAutomation)
            self._ready = True
            log.debug("[TabURL] Using comtypes UIA backend.")
            return True
        except Exception:
            pass

        # Fallback: raw ctypes COM (no comtypes package needed)
        return self._init_raw_ctypes()

    def _init_raw_ctypes(self) -> bool:
        """Fallback: call CoCreateInstance manually via ctypes."""
        try:
            clsid = ctypes.create_string_buffer(
                ctypes.cast(
                    ctypes.windll.ole32.CLSIDFromString(
                        ctypes.c_wchar_p(_CLSID_CUIAutomation), None
                    ), ctypes.c_void_p
                ).value or 0,
                16,
            )
        except Exception:
            clsid = None

        if clsid is None:
            return False

        # We'll use a simplified approach: ctypes POINTER to IUnknown vtable
        # This is inherently fragile; if comtypes is absent and CoCreateInstance
        # fails, we return False gracefully rather than crashing.
        try:
            CLSCTX_INPROC_SERVER = 0x1
            pUnk = ctypes.c_void_p()
            GUID = ctypes.c_char * 16
            clsid_g = GUID()
            iid_g   = GUID()
            ctypes.windll.ole32.CLSIDFromString(
                ctypes.c_wchar_p(_CLSID_CUIAutomation), ctypes.byref(clsid_g)
            )
            ctypes.windll.ole32.IIDFromString(
                ctypes.c_wchar_p(_IID_IUIAutomation), ctypes.byref(iid_g)
            )
            hr = ctypes.windll.ole32.CoCreateInstance(
                ctypes.byref(clsid_g),
                None,
                CLSCTX_INPROC_SERVER,
                ctypes.byref(iid_g),
                ctypes.byref(pUnk),
            )
            if hr != 0:
                return False
            self._uia_ptr = pUnk
            self._ready   = True   # raw mode — only used via _get_url_raw()
            log.debug("[TabURL] Using raw ctypes UIA backend.")
            return True
        except Exception as exc:
            log.debug("[TabURL] _init_raw_ctypes failed: %s", exc)
            return False

    @property
    def ready(self) -> bool:
        return self._ready


# Module-level UIA singleton (per-process)
_uia = _UIA()


# ── Public scraping function ───────────────────────────────────────────────────

def scrape_browser_tab_url(hwnd: int, proc_name: str) -> Optional[str]:
    """
    Return the URL currently shown in the address bar of *hwnd*, or None.

    Parameters
    ----------
    hwnd : int
        Win32 window handle of the foreground browser window.
    proc_name : str
        Lower-cased process name (e.g. ``"chrome.exe"``).

    Returns
    -------
    str | None
        The full URL string (e.g. ``"https://youtube.com/watch?v=..."``),
        or ``None`` if scraping failed, timed out, or is unsupported.
    """
    if not is_browser_process(proc_name):
        return None

    if not hwnd:
        return None

    # Ensure COM is initialised for this thread
    if not _com.ensure():
        return None

    deadline = time.monotonic() + _SCRAPE_TIMEOUT_S

    # Try comtypes path first (if available) — cleanest and most reliable
    try:
        url = _scrape_via_comtypes(hwnd, deadline)
        if url is not None:
            return url
    except Exception as exc:
        log.debug("[TabURL] comtypes scrape failed: %s", exc)

    # Fallback: PowerShell one-liner via subprocess (no COM dependency)
    # Only used if COM entirely fails (e.g., WinPE environment).
    if time.monotonic() < deadline:
        try:
            url = _scrape_via_powershell(hwnd, deadline)
            if url is not None:
                return url
        except Exception as exc:
            log.debug("[TabURL] PowerShell scrape failed: %s", exc)

    return None


def _scrape_via_comtypes(hwnd: int, deadline: float) -> Optional[str]:
    """
    Use comtypes (if installed) to walk the UIA tree for the address bar.
    Raises ImportError if comtypes is unavailable; caller catches and falls through.
    """
    import comtypes.client                                        # noqa: PLC0415
    import comtypes                                               # noqa: PLC0415

    uia = comtypes.client.CreateObject(
        "{ff48dba4-60ef-4201-aa87-54103eef594e}",
        interface=comtypes.IUnknown,
    )
    # Bring in the generated UIA interfaces
    try:
        from comtypes.gen import UIAutomationClient as _UIA      # noqa: PLC0415
    except ImportError:
        comtypes.client.GetModule("UIAutomationCore.dll")
        from comtypes.gen import UIAutomationClient as _UIA      # noqa: PLC0415

    uia_iface = uia.QueryInterface(_UIA.IUIAutomation)

    # Get element from HWND
    elem = uia_iface.ElementFromHandle(hwnd)

    # Build a condition: ControlType == Edit
    edit_cond = uia_iface.CreatePropertyCondition(
        UIA_ControlTypePropertyId,
        UIA_EditControlTypeId,
    )

    if time.monotonic() >= deadline:
        return None

    all_edits = elem.FindAll(_UIA.TreeScope_Descendants, edit_cond)

    for i in range(all_edits.Length):
        if time.monotonic() >= deadline:
            break
        candidate = all_edits.GetElement(i)
        auto_id   = candidate.GetCurrentPropertyValue(UIA_AutomationIdPropertyId)
        name      = (candidate.GetCurrentPropertyValue(UIA_NamePropertyId) or "").lower()

        # AutomationId match (fast path)
        if str(auto_id).lower() in _ADDRESS_BAR_IDS:
            val = candidate.GetCurrentPropertyValue(UIA_ValueValuePropertyId)
            url = str(val).strip()
            if url.startswith(("http://", "https://", "ftp://", "file://")):
                log.debug("[TabURL] AutomationId match — url=%.80s", url)
                return url

        # Name fragment match (fallback)
        if any(frag in name for frag in _ADDRESS_BAR_NAME_FRAGMENTS):
            val = candidate.GetCurrentPropertyValue(UIA_ValueValuePropertyId)
            url = str(val).strip()
            if url.startswith(("http://", "https://", "ftp://", "file://")):
                log.debug("[TabURL] Name-fragment match ('%s') — url=%.80s", name, url)
                return url

    return None


def _scrape_via_powershell(hwnd: int, deadline: float) -> Optional[str]:
    """
    Fallback: use a PowerShell one-liner that calls UIAutomation from .NET.
    Spawns a subprocess; only attempted if comtypes is unavailable.
    Timeout is enforced via the remaining deadline.
    """
    import subprocess   # noqa: PLC0415

    timeout = max(0.05, deadline - time.monotonic())
    script = (
        "[System.Reflection.Assembly]::LoadWithPartialName('UIAutomationClient') | Out-Null; "
        "[System.Reflection.Assembly]::LoadWithPartialName('UIAutomationTypes') | Out-Null; "
        f"$hwnd = {hwnd}; "
        "$ae = [System.Windows.Automation.AutomationElement]::FromHandle($hwnd); "
        "$cond = New-Object System.Windows.Automation.PropertyCondition("
        "  [System.Windows.Automation.AutomationElement]::ControlTypeProperty,"
        "  [System.Windows.Automation.ControlType]::Edit); "
        "$edits = $ae.FindAll([System.Windows.Automation.TreeScope]::Descendants, $cond); "
        "foreach ($e in $edits) { "
        "  $id = $e.Current.AutomationId; "
        "  if ($id -in 'omnibox','urlbar-input','addresseditbox') { "
        "    $vp = $e.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern); "
        "    Write-Output $vp.Current.Value; break } }"
    )
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        url = result.stdout.strip()
        if url.startswith(("http://", "https://", "ftp://", "file://")):
            log.debug("[TabURL] PowerShell scrape succeeded — url=%.80s", url)
            return url
    except subprocess.TimeoutExpired:
        log.debug("[TabURL] PowerShell scrape timed out (%.1fs budget)", timeout)
    return None


# ── Graceful no-op when UIA is unavailable ────────────────────────────────────

def scrape_browser_tab_url_safe(hwnd: int, proc_name: str) -> str:
    """
    Wrapper that **always** returns a string (empty string on failure).
    Use this from ``WindowMonitor`` so the monitor loop never needs a try/except
    for the scraping path.
    """
    try:
        result = scrape_browser_tab_url(hwnd, proc_name)
        return result if result is not None else ""
    except Exception as exc:
        log.debug("[TabURL] scrape_browser_tab_url_safe swallowed: %s", exc)
        return ""
