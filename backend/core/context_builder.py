"""
ContextBuilder — Activity Sanitizer
===================================
Cleans raw window title:
- Extracts platform (YouTube, Chrome, etc.)
- Content hints (tutorial, video, etc.)
- Normalizes input before classifier
"""
import urllib.parse

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
        # If we have a URL hostname, use the main domain as the platform 
        # (e.g. "reddit.com" -> "reddit")
        parts = hostname.split(".")
        platform = parts[-2] if len(parts) >= 2 else hostname
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
