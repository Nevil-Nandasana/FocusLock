"""
UserProfile — Per-Intent Personalization Layer
===============================================
Manages per-user, per-intent weight deltas layered on top of DEFAULT_PROFILES.

Persistence improvements over original:
  • _save() is now atomic: writes to a temp file then renames (os.replace).
    A crash mid-write can never corrupt the live profile file.
  • Disk I/O is dispatched to a single worker thread via a Queue.
    Multiple rapid feedback calls coalesce into one disk write (debounced).
    The monitor/classification thread never blocks on disk I/O.
  • All print() replaced with logging.getLogger(__name__).
"""

from __future__ import annotations

import json
import logging
import os
import queue
import shutil
import tempfile
import threading
from datetime import datetime

log = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PROFILE_FILE = os.path.join(BASE_DIR, "data", "ml", "user_profile.json")

# ── Pre-seeded base weights per intent domain ─────────────────────────────────
DEFAULT_PROFILES = {
    "global": {
        "python": 10, "javascript": 10, "c++": 10, "java": 10, "rust": 10,
        "code": 15, "github": 15, "vs code": 20, "pycharm": 20,
        "debug": 20, "docs": 15, "stackoverflow": 20,
        "aws": 10, "azure": 10, "cloud": 10,
        "youtube": -20, "netflix": -30, "twitch": -25, "video": -15,
        "movie": -20, "twitter": -20, "facebook": -20, "instagram": -25,
        "tiktok": -40, "reddit": -15, "game": -30, "steam": -30,
        "discord": 0,
        "shopping": -20, "amazon": -15, "news": -15,
    },
    "coding": {
        "pycharm": 25, "vs code": 25, "vscode": 25, "github": 20,
        "stackoverflow": 25, "terminal": 20, "docker": 15,
        "python": 15, "javascript": 15, "c++": 15, "java": 15, "rust": 15,
        "debug": 25, "git": 20, "code": 20, "intellij": 20, "jupyter": 15,
        "postman": 15, "insomnia": 15,
        "youtube": -20, "reddit": -20, "twitter": -25,
        "instagram": -30, "tiktok": -45, "netflix": -35,
        "steam": -35, "game": -35, "discord": -5,
    },
    "design": {
        "figma": 30, "photoshop": 25, "illustrator": 25, "canva": 20,
        "sketch": 25, "dribbble": 15, "behance": 15, "xd": 20,
        "affinity": 20, "zeplin": 20, "framer": 20,
        "color": 10, "font": 10, "icon": 10, "ui": 15, "ux": 15,
        "instagram": -10, "pinterest": 10,
        "youtube": -15, "reddit": -20, "twitter": -20,
        "tiktok": -40, "netflix": -30, "steam": -35, "game": -35, "discord": -5,
    },
    "writing": {
        "docs": 30, "notion": 25, "word": 25, "grammarly": 20,
        "obsidian": 20, "typora": 20, "medium": 15,
        "google docs": 30, "hemingway": 20, "scrivener": 20,
        "reddit": -10,
        "youtube": -25, "twitter": -20, "instagram": -30,
        "tiktok": -45, "netflix": -35, "steam": -35, "game": -35, "discord": -10,
    },
    "learning": {
        "youtube": 15, "udemy": 30, "coursera": 30,
        "github": 20, "stackoverflow": 25, "docs": 25, "medium": 15,
        "khan academy": 30, "wikipedia": 10, "edx": 30, "pluralsight": 25,
        "reddit": 5,
        "twitter": -20, "instagram": -30, "tiktok": -45,
        "netflix": -35, "steam": -35, "game": -35, "discord": -5,
    },
    "research": {
        "google": 10, "wikipedia": 15, "scholar": 25, "docs": 20,
        "notion": 20, "medium": 15, "github": 15, "reddit": 10,
        "stackoverflow": 15,
        "twitter": -15, "instagram": -30, "tiktok": -45,
        "netflix": -35, "steam": -35, "game": -35,
    },
}


class UserProfile:
    """
    Per-intent weight profiles with global fallback.

    Layer 1 (Automatic): session completions reward productive apps;
                         violations penalize distraction apps.
    Layer 2 (Manual):    user thumbs-up/down corrections via /api/feedback.
    """

    LEARNING_RATE_AUTO   = 3    # small, continuous nudges
    LEARNING_RATE_MANUAL = 8    # user corrections — bigger, immediate signal
    MAX_DELTA            = 40   # cap so deltas cannot override base weights entirely

    def __init__(self):
        self._lock   = threading.Lock()
        self._deltas: dict = {}
        self._meta: dict   = {
            "total_sessions": 0,
            "intent_aliases": {},
            "last_updated":   None,
        }

        # ── Async save worker ─────────────────────────────────────────────────
        self._save_queue  = queue.Queue()
        self._save_thread = threading.Thread(
            target=self._save_loop,
            name="focuslock-profile-saver",
            daemon=True,
        )
        self._save_thread.start()

        self._load()

    # ── Persistence ───────────────────────────────────────────────────────────

    def _load(self):
        os.makedirs(os.path.dirname(PROFILE_FILE), exist_ok=True)
        if os.path.exists(PROFILE_FILE):
            try:
                with open(PROFILE_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._meta   = data.pop("_meta", self._meta)
                self._deltas = data
                log.info(
                    "[UserProfile] Loaded — %d intent bucket(s).",
                    len(self._deltas),
                )
            except Exception as e:
                log.error("[UserProfile] Load failed, starting fresh: %s", e)
        else:
            log.info("[UserProfile] No profile found — starting fresh.")

    def _enqueue_save(self):
        """Put a save request on the queue (non-blocking, called from any thread)."""
        self._save_queue.put(1)

    def _save_loop(self):
        """
        Single worker thread: drains the queue then performs one atomic write.
        Multiple rapid updates coalesce into a single disk write.
        """
        while True:
            self._save_queue.get()          # block until a save is requested
            # Drain any extra requests that arrived during I/O latency
            while not self._save_queue.empty():
                try:
                    self._save_queue.get_nowait()
                except queue.Empty:
                    break
            self._save()                    # one write per burst

    def _save(self):
        """
        Atomic write: serialize to a temp file in the same directory,
        then os.replace() — which is atomic on POSIX and Windows (same drive).
        A crash mid-write can never corrupt the live profile file.
        """
        try:
            with self._lock:
                data = dict(self._deltas)
                meta = dict(self._meta)

            data["_meta"] = meta
            data["_meta"]["last_updated"] = datetime.now().isoformat()

            dir_ = os.path.dirname(PROFILE_FILE)
            os.makedirs(dir_, exist_ok=True)

            # Write to temp file in same directory (ensures same filesystem)
            fd, tmp_path = tempfile.mkstemp(dir=dir_, suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2)
                os.replace(tmp_path, PROFILE_FILE)   # atomic rename
            except Exception:
                os.unlink(tmp_path)                   # clean up on failure
                raise

        except Exception as e:
            log.error("[UserProfile] Save failed: %s", e, exc_info=True)

    # ── Weight Lookup ─────────────────────────────────────────────────────────

    def get_weight(self, concept: str, intent_key: str = "global") -> int:
        concept    = concept.lower()
        intent_key = self._resolve_intent_key(intent_key)

        base = (
            DEFAULT_PROFILES.get(intent_key, {}).get(concept)
            or DEFAULT_PROFILES["global"].get(concept, 0)
        )

        with self._lock:
            g_delta = self._deltas.get("global",   {}).get(concept, 0)
            i_delta = self._deltas.get(intent_key, {}).get(concept, 0)

        return base + g_delta + i_delta

    def get_all_weights(self, intent_key: str = "global") -> dict:
        intent_key = self._resolve_intent_key(intent_key)

        merged = dict(DEFAULT_PROFILES.get("global", {}))
        merged.update(DEFAULT_PROFILES.get(intent_key, {}))

        with self._lock:
            for concept, delta in self._deltas.get("global", {}).items():
                merged[concept] = merged.get(concept, 0) + delta
            for concept, delta in self._deltas.get(intent_key, {}).items():
                merged[concept] = merged.get(concept, 0) + delta

        return merged

    # ── Learning ──────────────────────────────────────────────────────────────

    def apply_feedback(
        self,
        concept:    str,
        direction:  str,           # "positive" | "negative"
        intent_key: str  = "global",
        manual:     bool = False,
    ):
        concept    = concept.lower().strip()
        intent_key = self._resolve_intent_key(intent_key)
        rate       = self.LEARNING_RATE_MANUAL if manual else self.LEARNING_RATE_AUTO
        delta      = rate if direction == "positive" else -rate

        with self._lock:
            bucket  = self._deltas.setdefault(intent_key, {})
            current = bucket.get(concept, 0)
            bucket[concept] = max(
                -self.MAX_DELTA, min(self.MAX_DELTA, current + delta)
            )

        # Dispatch save to worker thread — does NOT block the caller
        self._enqueue_save()

    def record_session_outcome(
        self,
        intent_key:      str,
        productive_apps: list,
        violated_apps:   list,
        completed:       bool,
    ):
        intent_key = self._resolve_intent_key(intent_key)

        if completed:
            for app in productive_apps:
                self.apply_feedback(app, "positive", intent_key, manual=False)
            for app in violated_apps:
                self.apply_feedback(app, "negative", intent_key, manual=False)
        else:
            for app in violated_apps:
                self.apply_feedback(app, "negative", intent_key, manual=False)
                self.apply_feedback(app, "negative", intent_key, manual=False)

        with self._lock:
            self._meta["total_sessions"] = self._meta.get("total_sessions", 0) + 1

        self._enqueue_save()

    # ── Utilities ─────────────────────────────────────────────────────────────

    def _resolve_intent_key(self, intent_key: str) -> str:
        if not intent_key:
            return "global"
        key     = intent_key.lower().strip()
        aliases = self._meta.get("intent_aliases", {})
        if key in aliases:
            return aliases[key]
        known = set(DEFAULT_PROFILES.keys()) | set(self._deltas.keys())
        return key if key in known else "global"

    def get_summary(self) -> dict:
        with self._lock:
            return {
                "meta":           dict(self._meta),
                "intent_buckets": sorted(
                    set(DEFAULT_PROFILES.keys()) | set(self._deltas.keys())
                ),
                "user_deltas": {
                    k: dict(v)
                    for k, v in self._deltas.items()
                    if k != "_meta"
                },
            }


# ── Global Singleton ──────────────────────────────────────────────────────────
user_profile = UserProfile()
