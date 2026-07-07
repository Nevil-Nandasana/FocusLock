"""
ContextBuilder — Activity Sanitizer
===================================
Cleans raw window title:
- Extracts platform (YouTube, Chrome, etc.)
- Content hints (tutorial, video, etc.)
- Normalizes input before classifier
"""
import urllib.parse

# Common two-segment public suffixes that naive split(".")[-2] mis-handles.
# e.g. "bbc.co.uk" \u2192 registrable domain = "bbc", not "co"
_KNOWN_DOUBLE_SUFFIXES = frozenset({
    "co.uk", "co.jp", "co.in", "co.nz", "co.za", "co.ke",
    "com.au", "com.br", "com.mx", "com.ar", "com.sg", "com.hk",
    "com.ng", "com.eg", "com.pk", "com.ua", "com.tw",
    "org.uk", "net.au", "gov.uk", "ac.uk", "me.uk",
})


def _extract_registrable_domain(hostname: str) -> str:
    """Return the registrable part of a hostname.

    For most domains this is parts[-2] (e.g. "youtube" from "www.youtube.com").
    For ccTLD domains like "bbc.co.uk" the two-segment suffix is recognised and
    the part before it is returned ("bbc").
    """
    parts = hostname.split(".")
    if len(parts) >= 3:
        two_seg = f"{parts[-2]}.{parts[-1]}"
        if two_seg in _KNOWN_DOUBLE_SUFFIXES:
            # hostname like "bbc.co.uk" \u2192 registrable = parts[-3] = "bbc"
            return parts[-3]
    if len(parts) >= 2:
        return parts[-2]
    return hostname


def build_context(raw_state: dict) -> dict:
    title = raw_state.get("title", "").strip()
    app = raw_state.get("app", "").strip()
    url = raw_state.get("url", "").strip()

    # Extract Platform
    platform = app.split(".")[0].lower() if app else "unknown"
    title_lower = title.lower()

    hostname = ""
    if url:
        try:
            parsed = urllib.parse.urlparse(url)
            hostname = parsed.hostname.lower() if parsed.hostname else ""
        except Exception:
            pass

    if "youtube" in hostname or "youtube" in title_lower or "youtube" in platform:
        platform = "youtube"
    elif hostname:
        # Use the registrable domain (handles ccTLDs like co.uk, com.au)
        platform = _extract_registrable_domain(hostname)
    elif "chrome" in title_lower or "msedge" in title_lower or "firefox" in title_lower or "browser" in platform:
        platform = "browser"
    elif "code" in platform or "pycharm" in platform or "intellij" in platform:
        platform = "ide"

    # Extract Hints
    hints = []
    text_to_search = f"{title_lower} {url.lower()}"
    if any(w in text_to_search for w in ["tutorial", "course", "learn", "how to", "guide", "documentation", "docs"]):
        hints.append("learning")
    if "react" in text_to_search:
        hints.append("react")
    if any(w in text_to_search for w in ["instagram", "tiktok", "twitter", "facebook", "reddit", "netflix"]):
        hints.append("distraction_source")

    normalized_text = f"{title} {app} {url} {' '.join(hints)}".strip().lower()

    return {
        "title": title,
        "app": app,
        "url": url,
        "platform": platform,
        "hints": hints,
        "normalized_text": normalized_text
    }
