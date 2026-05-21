"""
ContextBuilder — Activity Sanitizer
===================================
Cleans raw window title:
- Extracts platform (YouTube, Chrome, etc.)
- Content hints (tutorial, video, etc.)
- Normalizes input before classifier
"""
import re

def build_context(raw_state: dict) -> dict:
    title = raw_state.get("title", "").strip()
    app = raw_state.get("app", "").strip()
    url = raw_state.get("url", "").strip()
    
    # Extract Platform
    platform = app.split(".")[0].lower() if app else "unknown"
    title_lower = title.lower()
    
    if "youtube" in title_lower or "youtube" in platform:
        platform = "youtube"
    elif "chrome" in title_lower or "msedge" in title_lower or "firefox" in title_lower or "browser" in platform:
        platform = "browser"
    elif "code" in platform or "pycharm" in platform or "intellij" in platform:
        platform = "ide"
        
    # Extract Hints
    hints = []
    if any(w in title_lower for w in ["tutorial", "course", "learn", "how to", "guide", "documentation", "docs"]):
        hints.append("learning")
    if "react" in title_lower:
        hints.append("react")
    if any(w in title_lower for w in ["instagram", "tiktok", "twitter", "facebook", "reddit", "netflix"]):
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
