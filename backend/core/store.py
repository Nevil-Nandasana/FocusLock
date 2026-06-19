"""
EventStore — SQLite-backed Event Log with Crypto Chain Integrity
================================================================
Performance improvements over original:
  • session_id is extracted to a real TEXT column with an index — O(1) lookups.
  • get_violation_count / get_penalty_seconds / has_suspicious_gap /
    get_last_heartbeat all use targeted SQL rather than full Python table scans.
  • get_current_session() uses SQL for the fast path; falls back gracefully
    when there is no SESSION_STOP (crash-recovery: treats session as active).
  • Three indexes added on first init: event_type, session_id, timestamp.
  • historic_break_pattern() fixed — now stores and compares elapsed_seconds,
    not absolute Unix timestamps (which was a meaningless average).
  • All print() replaced with logging.getLogger(__name__).
"""

from __future__ import annotations

import sqlite3
import json
import hashlib
import logging
import os
import threading
from datetime import datetime, timedelta

log = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DB_FILE  = os.path.join(BASE_DIR, "data", "db", "focuslock.db")


class EventStore:

    def __init__(self):
        # Stats cache — invalidated on any session-affecting write so every
        # quiet poll is O(1) instead of O(n full table scan).
        self._stats_cache: dict | None = None
        self._stats_dirty              = True   # True → recompute on next read
        self._stats_lock               = threading.Lock()

        self._init_db()

    # ── Schema ────────────────────────────────────────────────────────────────

    def _init_db(self):
        with sqlite3.connect(DB_FILE) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS events (
                    id             INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type     TEXT    NOT NULL,
                    timestamp      TEXT    NOT NULL,
                    payload        TEXT,
                    session_id     TEXT,
                    previous_hash  TEXT,
                    hash           TEXT
                )
            """)
            self._ensure_columns(conn)
            self._ensure_indexes(conn)

    def _ensure_columns(self, conn):
        """Idempotent schema migration — adds columns missing from older DBs."""
        cursor  = conn.execute("PRAGMA table_info(events)")
        existing = {row[1] for row in cursor.fetchall()}

        migrations = {
            "previous_hash": "ALTER TABLE events ADD COLUMN previous_hash TEXT",
            "hash":          "ALTER TABLE events ADD COLUMN hash TEXT",
            "session_id":    "ALTER TABLE events ADD COLUMN session_id TEXT",
        }
        for col, sql in migrations.items():
            if col not in existing:
                conn.execute(sql)
                log.info("[EventStore] Added column '%s' to events table.", col)

        # Back-fill session_id for existing rows (one-time migration)
        conn.execute("""
            UPDATE events
            SET session_id = json_extract(payload, '$.session_id')
            WHERE session_id IS NULL AND payload IS NOT NULL
        """)

    def _ensure_indexes(self, conn):
        """Create indexes if they don't already exist."""
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_events_sid  ON events(session_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_events_ts   ON events(timestamp)"
        )

    # ── Crypto Chain ──────────────────────────────────────────────────────────

    def _calculate_hash(self, prev_hash, event_type, timestamp, payload):
        content = f"{prev_hash}|{event_type}|{timestamp}|{payload}"
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def _get_last_hash(self, conn):
        row = conn.execute(
            "SELECT hash FROM events ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return row[0] if row and row[0] else "GENESIS_HASH"

    # ── Core Write ────────────────────────────────────────────────────────────

    def append_event(self, event_type: str, payload: dict):
        timestamp    = datetime.now().isoformat()
        payload_json = json.dumps(payload)
        session_id   = payload.get("session_id")          # may be None

        with sqlite3.connect(DB_FILE) as conn:
            prev_hash    = self._get_last_hash(conn)
            current_hash = self._calculate_hash(
                prev_hash, event_type, timestamp, payload_json
            )
            conn.execute(
                """INSERT INTO events
                   (event_type, timestamp, payload, session_id, previous_hash, hash)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (event_type, timestamp, payload_json,
                 session_id, prev_hash, current_hash),
            )

        # Invalidate stats cache for any event that changes XP.
        _XP_EVENTS = {
            "SESSION_START", "SESSION_COMPLETE", "SESSION_BROKEN",
            "SESSION_STOP",  "FOCUS_VIOLATION",  "SESSION_EXTEND",
        }
        if event_type in _XP_EVENTS:
            with self._stats_lock:
                self._stats_dirty = True

    # ── Full Event Read (analytics page only) ─────────────────────────────────

    def get_events(self):
        """Return all events as dicts. Use only for analytics — not hot paths."""
        with sqlite3.connect(DB_FILE) as conn:
            rows = conn.execute(
                "SELECT event_type, timestamp, payload FROM events ORDER BY id"
            ).fetchall()
        return [
            {
                "type":      r[0],
                "timestamp": r[1],
                "payload":   json.loads(r[2]) if r[2] else {},
            }
            for r in rows
        ]

    # ── Integrity ─────────────────────────────────────────────────────────────

    def verify_integrity(self):
        with sqlite3.connect(DB_FILE) as conn:
            rows = conn.execute(
                "SELECT id, event_type, timestamp, payload, previous_hash, hash "
                "FROM events ORDER BY id"
            ).fetchall()

        last_hash = "GENESIS_HASH"
        for r in rows:
            calc_hash = self._calculate_hash(last_hash, r[1], r[2], r[3])
            if r[5]:
                if r[4] and r[4] != last_hash:
                    return False, f"Broken chain at ID {r[0]}: previous_hash mismatch"
                if r[5] != calc_hash:
                    return False, f"Integrity failure at ID {r[0]}: content modified"
            last_hash = r[5] if r[5] else "GENESIS_HASH"
        return True, "Integrity Verified"

    # ── Maintenance ───────────────────────────────────────────────────────────

    def purge_old_events(self, days_to_keep: int = 30):
        cutoff = (datetime.now() - timedelta(days=days_to_keep)).isoformat()
        with sqlite3.connect(DB_FILE) as conn:
            conn.execute("DELETE FROM events WHERE timestamp < ?", (cutoff,))
        log.info("[EventStore] Purged events older than %d days.", days_to_keep)

    # ── Session Projection — SQL-optimized ────────────────────────────────────

    def get_current_session(self) -> dict | None:
        """
        Find the currently active session.

        Fast path  — SQL query for latest SESSION_START.
        Crash-recovery — if no SESSION_STOP/SESSION_BROKEN exists for that
                         session, we assume it is still active (handles app
                         crash mid-session without losing state).
        """
        with sqlite3.connect(DB_FILE) as conn:
            row = conn.execute("""
                SELECT payload, timestamp FROM events
                WHERE event_type = 'SESSION_START'
                ORDER BY id DESC LIMIT 1
            """).fetchone()

        if not row:
            return None

        try:
            payload    = json.loads(row[0]) if row[0] else {}
        except json.JSONDecodeError:
            return None

        session_id = payload.get("session_id")
        if not session_id:
            return None

        # Check if this session was properly closed
        with sqlite3.connect(DB_FILE) as conn:
            closed = conn.execute("""
                SELECT 1 FROM events
                WHERE event_type IN ('SESSION_STOP', 'SESSION_BROKEN')
                AND session_id = ?
                LIMIT 1
            """, (session_id,)).fetchone()

        if closed:
            return None      # session ended normally

        # Session is still active (or app crashed mid-session — crash recovery)
        payload["start_time"]      = row[1]
        payload["paused_duration"] = self._get_paused_duration(session_id)

        # Apply any extensions
        with sqlite3.connect(DB_FILE) as conn:
            exts = conn.execute("""
                SELECT payload FROM events
                WHERE event_type = 'SESSION_EXTEND' AND session_id = ?
                ORDER BY id
            """, (session_id,)).fetchall()

        streak = 1
        for ext_row in exts:
            try:
                ext_payload = json.loads(ext_row[0])
                mins = ext_payload.get("extension_minutes", 0)
                payload["expected_duration"] = payload.get("expected_duration", 0) + mins
                end_dt = (
                    datetime.fromisoformat(payload["expected_end_time"])
                    + timedelta(minutes=mins)
                )
                payload["expected_end_time"] = end_dt.isoformat()
                streak += 1
            except Exception:
                pass
        payload["streak"] = streak

        return payload

    def _get_paused_duration(self, session_id: str) -> float:
        """Sum all paused_seconds from SESSION_RESUMED events for this session."""
        with sqlite3.connect(DB_FILE) as conn:
            rows = conn.execute("""
                SELECT payload FROM events
                WHERE event_type = 'SESSION_RESUMED' AND session_id = ?
            """, (session_id,)).fetchall()
        total = 0.0
        for r in rows:
            try:
                total += json.loads(r[0]).get("paused_seconds", 0)
            except Exception:
                pass
        return total

    def session_completed(self, session_id: str) -> bool:
        """True if the last SESSION_COMPLETE comes after the last SESSION_EXTEND."""
        with sqlite3.connect(DB_FILE) as conn:
            last_comp = conn.execute("""
                SELECT MAX(id) FROM events
                WHERE event_type = 'SESSION_COMPLETE' AND session_id = ?
            """, (session_id,)).fetchone()[0]

            last_ext = conn.execute("""
                SELECT MAX(id) FROM events
                WHERE event_type = 'SESSION_EXTEND' AND session_id = ?
            """, (session_id,)).fetchone()[0]

        if last_comp is None:
            return False
        return last_comp > (last_ext or -1)

    # ── Penalties — Direct SQL ────────────────────────────────────────────────

    def get_violation_count(self, session_id: str) -> int:
        with sqlite3.connect(DB_FILE) as conn:
            row = conn.execute("""
                SELECT COUNT(*) FROM events
                WHERE event_type = 'FOCUS_VIOLATION' AND session_id = ?
            """, (session_id,)).fetchone()
        return row[0] if row else 0

    def get_penalty_seconds(self, session_id: str) -> int:
        with sqlite3.connect(DB_FILE) as conn:
            row = conn.execute("""
                SELECT SUM(CAST(json_extract(payload, '$.penalty_seconds') AS INTEGER))
                FROM events
                WHERE event_type = 'FOCUS_VIOLATION' AND session_id = ?
            """, (session_id,)).fetchone()
        return row[0] or 0

    # ── Tamper / Heartbeat — Direct SQL ──────────────────────────────────────

    def get_last_heartbeat(self, session_id: str):
        with sqlite3.connect(DB_FILE) as conn:
            row = conn.execute("""
                SELECT timestamp FROM events
                WHERE event_type = 'HEARTBEAT' AND session_id = ?
                ORDER BY id DESC LIMIT 1
            """, (session_id,)).fetchone()
        return datetime.fromisoformat(row[0]) if row else None

    def has_suspicious_gap(self, session_id: str) -> bool:
        with sqlite3.connect(DB_FILE) as conn:
            row = conn.execute("""
                SELECT 1 FROM events
                WHERE event_type = 'SUSPICIOUS_GAP' AND session_id = ?
                LIMIT 1
            """, (session_id,)).fetchone()
        return row is not None

    # ── Prediction Data ───────────────────────────────────────────────────────

    def historic_break_pattern(self, elapsed_seconds: float) -> bool:
        """
        Returns True if the current elapsed time matches historical break patterns.

        FIX: The original averaged absolute Unix timestamps (epoch values), which
        is completely meaningless. We now store elapsed_seconds in SESSION_BROKEN
        payloads and compare against those. Falls back gracefully for old records
        that lack this field.
        """
        with sqlite3.connect(DB_FILE) as conn:
            rows = conn.execute("""
                SELECT payload FROM events
                WHERE event_type = 'SESSION_BROKEN'
                ORDER BY id DESC LIMIT 20
            """).fetchall()

        elapsed_history = []
        for r in rows:
            try:
                p = json.loads(r[0])
                if "elapsed_seconds" in p:
                    elapsed_history.append(float(p["elapsed_seconds"]))
            except Exception:
                pass

        if len(elapsed_history) < 3:
            return False

        avg = sum(elapsed_history) / len(elapsed_history)
        return abs(elapsed_seconds - avg) < 300   # 5-minute window

    # ── Gamification ─────────────────────────────────────────────────────────

    def get_user_stats(self) -> dict:
        """
        Return XP / level / session counts.

        Results are cached and invalidated only when an XP-affecting event is
        written (SESSION_START, SESSION_COMPLETE, SESSION_BROKEN, SESSION_STOP,
        FOCUS_VIOLATION, SESSION_EXTEND).  Between those events every call is
        O(1) — a dict copy of the cached value.
        """
        with self._stats_lock:
            if not self._stats_dirty and self._stats_cache is not None:
                return dict(self._stats_cache)          # O(1) cache hit

        stats = self._compute_user_stats_sql()          # recompute via SQL

        with self._stats_lock:
            self._stats_cache = stats
            self._stats_dirty = False
        return dict(stats)

    def _compute_user_stats_sql(self) -> dict:
        """
        Compute XP aggregates entirely in SQL using indexed session_id columns.

        XP formula (per session, matches original Python logic exactly):
          completed:  +duration*10, +100 bonus if zero violations
          always:     -violations*50
          broken:     -100
        """
        sql = """
        WITH sessions AS (
            SELECT
                session_id,
                CAST(json_extract(payload, '$.expected_duration') AS INTEGER)
                    AS base_duration
            FROM events
            WHERE event_type = 'SESSION_START'
              AND session_id IS NOT NULL
        ),
        extensions AS (
            SELECT session_id,
                   SUM(CAST(json_extract(payload, '$.extension_minutes')
                            AS INTEGER)) AS extra_minutes
            FROM events
            WHERE event_type = 'SESSION_EXTEND'
            GROUP BY session_id
        ),
        violations AS (
            SELECT session_id, COUNT(*) AS vcount
            FROM events
            WHERE event_type = 'FOCUS_VIOLATION'
            GROUP BY session_id
        ),
        completions AS (
            SELECT DISTINCT session_id, 1 AS completed
            FROM events
            WHERE event_type = 'SESSION_COMPLETE'
        ),
        breaks AS (
            SELECT DISTINCT session_id, 1 AS broken
            FROM events
            WHERE event_type = 'SESSION_BROKEN'
        ),
        per_session AS (
            SELECT
                s.session_id,
                COALESCE(s.base_duration, 25) + COALESCE(e.extra_minutes, 0)
                    AS duration,
                COALESCE(v.vcount, 0)       AS violations,
                COALESCE(c.completed, 0)    AS completed,
                COALESCE(b.broken, 0)       AS broken
            FROM sessions s
            LEFT JOIN extensions  e ON e.session_id = s.session_id
            LEFT JOIN violations  v ON v.session_id = s.session_id
            LEFT JOIN completions c ON c.session_id = s.session_id
            LEFT JOIN breaks      b ON b.session_id = s.session_id
        )
        SELECT
            COUNT(*)          AS total_sessions,
            SUM(completed)    AS completed_sessions,
            SUM(
                CASE WHEN completed THEN duration * 10 ELSE 0 END
                + CASE WHEN completed AND violations = 0 THEN 100 ELSE 0 END
                - violations * 50
                - CASE WHEN broken THEN 100 ELSE 0 END
            )                 AS raw_xp
        FROM per_session
        """
        try:
            with sqlite3.connect(DB_FILE) as conn:
                row = conn.execute(sql).fetchone()
        except Exception as exc:
            log.error("[EventStore] _compute_user_stats_sql failed: %s", exc)
            row = None

        total_sessions     = int(row[0] or 0) if row else 0
        completed_sessions = int(row[1] or 0) if row else 0
        raw_xp             = int(row[2] or 0) if row else 0
        xp                 = max(0, raw_xp)
        level              = 1 + int(xp / 1000)

        return {
            "xp":                 xp,
            "level":              level,
            "total_sessions":     total_sessions,
            "completed_sessions": completed_sessions,
        }
