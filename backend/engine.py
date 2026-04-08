"""
FocusEngine — Event-Driven Cognitive Behaviour Orchestrator
============================================================
Upgraded capabilities:
  ✅ Real-time feedback loop (violations → negative signals, completions → positive)
  ✅ User personalization (per-intent weight profiles)
  ✅ Deep intent awareness (IntentProfile parsed once per session)
  ✅ Background learning via LearningManager (thread-safe, cooldown-guarded)
  ✅ Structured logging (all print() removed)
  ✅ elapsed_seconds recorded in SESSION_BROKEN for accurate failure prediction
"""

import logging
import threading
import time
import uuid
from datetime import datetime, timedelta

from .store            import EventStore
from .monitor          import WindowMonitor
from .classifier       import classifier as clf
from .logger           import logger
from .intent_engine    import intent_engine, IntentProfile
from .user_profile     import user_profile
from .learning_manager import LearningManager

log = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────
PENALTY_RULES        = [60, 120, 300]
HEARTBEAT_THRESHOLD  = 15
PREDICTION_THRESHOLD = 2

DRIFT_WINDOW_SEC = 60
DRIFT_THRESHOLD  = 5

# Explicit FSM: only these transitions are allowed
ALLOWED_TRANSITIONS = {
    "PRODUCTIVE":  ["PRODUCTIVE", "WARNING"],
    "WARNING":     ["WARNING", "DISTRACTION", "PRODUCTIVE"],
    "DISTRACTION": ["DISTRACTION", "WARNING"],
}


class FocusEngine:

    def __init__(self):
        self.store          = EventStore()
        self.active_monitor = None

        # Thread safety — shared state written from monitor thread
        self._lock = threading.Lock()

        # Runtime session state
        self.is_paused             = False
        self.total_paused_duration = 0
        self.pause_start_time      = None

        # FSM state
        self.current_state        = "PRODUCTIVE"
        self.last_state           = "PRODUCTIVE"
        self.last_alert_time      = 0
        self.alert_cooldown       = 10

        self.last_classified_state = None

        # Drift tracking
        self.recent_switches = []

        # ── Intent awareness — parsed once per session ────────────────────────
        self.intent_profile: IntentProfile | None = None

        # ── Per-session app tracking for auto-learning ────────────────────────
        self.session_productive_apps: list[str] = []
        self.session_violated_apps:   list[str] = []

        # ── Background ML training orchestrator ───────────────────────────────
        self.learning_manager = LearningManager()

        self._check_resume_session()

    # ── Session Management ────────────────────────────────────────────────────

    def _check_resume_session(self):
        """State persistence: recover session if the app restarts mid-session."""
        session = self.store.get_current_session()
        if session:
            self._parse_intent(session.get("intent", ""))
            self.set_monitor(
                whitelist=session.get("whitelist", []),
                blacklist=session.get("blacklist", []),
                intent=session.get("intent", ""),
                mode=session.get("mode", "deep"),
            )

    def start_session(
        self,
        duration_minutes: int,
        mode:      str  = "deep",
        whitelist: list = None,
        blacklist: list = None,
        intent:    str  = "",
    ):
        # Close any existing open session
        active_session = self.store.get_current_session()
        if active_session:
            self._apply_session_feedback(active_session, completed=False)
            self.store.append_event(
                "SESSION_BROKEN",
                {
                    "session_id": active_session["session_id"],
                    "excuse":     "Force Restart",
                },
            )

        self.is_paused             = False
        self.total_paused_duration = 0
        self.current_state         = "PRODUCTIVE"
        self.session_productive_apps = []
        self.session_violated_apps   = []

        # ── Parse intent once — used for every classification this session ────
        self._parse_intent(intent)

        session_id = str(uuid.uuid4())
        now        = datetime.now()
        end_time   = now + timedelta(minutes=int(duration_minutes))

        self.store.append_event(
            "SESSION_START",
            {
                "session_id":       session_id,
                "expected_duration": int(duration_minutes),
                "expected_end_time": end_time.isoformat(),
                "mode":              mode,
                "intent":            intent,
                "intent_key":        self.intent_profile.intent_key
                                     if self.intent_profile else "global",
                "whitelist":         whitelist,
                "blacklist":         blacklist,
            },
        )

        self.set_monitor(whitelist, blacklist, intent, mode)

    def _parse_intent(self, intent: str):
        """Parse intent string into structured IntentProfile (stored on self)."""
        self.intent_profile = intent_engine.parse(intent)
        log.info(
            "[Engine] Intent parsed → key=%s  strength=%.2f  "
            "verb='%s'  subject='%s'",
            self.intent_profile.intent_key,
            self.intent_profile.strength,
            self.intent_profile.goal_verb,
            self.intent_profile.goal_subject,
        )

    def set_monitor(self, whitelist, blacklist, intent, mode):
        if self.active_monitor:
            self.active_monitor.stop()

        self.active_monitor = WindowMonitor(
            callback_state_change=self._on_state_change
        )
        self.active_monitor.start()

    # ── Event-Driven Classification Pipeline ─────────────────────────────────

    def _on_state_change(self, raw_state: dict):
        if self.is_paused:
            return
        session = self.store.get_current_session()
        if not session:
            return

        now = time.time()

        # 1. Drift tracking (time-decayed, thread-safe)
        with self._lock:
            self.recent_switches.append(now)
            self.recent_switches = [
                t for t in self.recent_switches if now - t <= DRIFT_WINDOW_SEC
            ]
            is_drifting = len(self.recent_switches) > DRIFT_THRESHOLD

        # 2. Extract features (personalized + intent-aware)
        features = clf.extract_features(
            state          = raw_state,
            intent         = session.get("intent", ""),
            mode           = session.get("mode", "deep"),
            whitelist      = session.get("whitelist", []),
            blacklist      = session.get("blacklist", []),
            intent_profile = self.intent_profile,   # ← structured intent
        )

        # 3. Decision logic
        new_state = "PRODUCTIVE"
        reason    = "Aligned"
        confidence = features["confidence"]

        if features["whitelist_match"]:
            new_state = "PRODUCTIVE"
            reason    = "Whitelist match"
        elif features["blacklist_match"]:
            new_state = "DISTRACTION"
            reason    = "Blacklist match"
        elif features.get("negative_override"):
            # Intent engine detected a hard anti-intent signal
            new_state = "DISTRACTION"
            reason    = features.get("intent_reason", "Anti-intent app")
        else:
            h_score = features["heuristic_score"]
            if h_score < -15:
                if confidence < 75:
                    new_state = "WARNING"
                    reason    = "Low-confidence distraction"
                else:
                    new_state = "DISTRACTION"
                    reason    = "Distraction detected"
            elif h_score > 15:
                new_state = "PRODUCTIVE"
                reason    = features.get("intent_reason", "Aligned")
            else:
                new_state = "PRODUCTIVE"  # ambiguous → productive by default

        if is_drifting and new_state == "PRODUCTIVE":
            new_state = "WARNING"
            reason    = "Drift detected (frequent switching)"

        # 4. FSM enforcement
        with self._lock:
            allowed = ALLOWED_TRANSITIONS.get(self.current_state, [])
            if new_state not in allowed:
                new_state = self.current_state  # snap to legal state

            self.last_state        = self.current_state
            self.current_state     = new_state
            self.last_classified_state = {
                "app":      raw_state.get("app", ""),
                "title":    raw_state.get("title", ""),
                "state":    new_state,
                "features": features,
                "reason":   reason,
            }
            last_alert_snapshot = self.last_alert_time

        # 5. Track apps for end-of-session auto-learning
        app_name = (raw_state.get("app") or "").lower().split(".")[0]
        if app_name:
            with self._lock:
                if new_state == "PRODUCTIVE" and app_name not in self.session_productive_apps:
                    self.session_productive_apps.append(app_name)
                elif new_state == "DISTRACTION" and app_name not in self.session_violated_apps:
                    self.session_violated_apps.append(app_name)

        # 6. Intervention + cooldown layer
        if self.current_state != "PRODUCTIVE":
            if (
                self.current_state != self.last_state
                or (now - last_alert_snapshot) > self.alert_cooldown
            ):
                with self._lock:
                    self.last_alert_time = now
                if self.current_state == "DISTRACTION":
                    self.register_violation(f"DISTRACTION: {reason}")
                    # Layer 1 auto-learning: immediate negative signal on violation
                    clf.apply_session_feedback(
                        app           = raw_state.get("app", ""),
                        title         = raw_state.get("title", ""),
                        correct_label = "DISTRACTION",
                        intent_key    = self.intent_profile.intent_key
                                        if self.intent_profile else "global",
                        manual        = False,
                    )

        # 7. Logging
        logger.log_activity(
            timestamp      = datetime.now().isoformat(),
            title          = raw_state.get("title", ""),
            app            = raw_state.get("app", ""),
            url            = raw_state.get("url", ""),
            features       = features,
            classification = self.current_state,
            reason         = reason,
        )

        logger.log_training_row(
            title      = raw_state.get("title", ""),
            app        = raw_state.get("app", ""),
            url        = raw_state.get("url", ""),
            goal       = session.get("intent", ""),
            mode       = session.get("mode", "deep"),
            similarity = features["semantic_similarity"],
            heuristic  = features["heuristic_score"],
            confidence = features["confidence"],
            label      = self.current_state,
        )

    # ── Status ────────────────────────────────────────────────────────────────

    def get_status(self):
        session = self.store.get_current_session()
        if not session:
            if self.active_monitor:
                self.active_monitor.stop()
                self.active_monitor = None
            return {"active": False, "user_stats": self.store.get_user_stats()}

        now              = datetime.now()
        base_end         = datetime.fromisoformat(session["expected_end_time"])
        penalty_seconds  = self.store.get_penalty_seconds(session["session_id"])
        paused_from_store = session.get("paused_duration", 0)

        current_pause_delta = 0
        if self.is_paused and self.pause_start_time:
            current_pause_delta = (now - self.pause_start_time).total_seconds()

        total_extension = penalty_seconds + paused_from_store + current_pause_delta
        adjusted_end    = base_end + timedelta(seconds=total_extension)

        if now >= adjusted_end and not self.is_paused:
            if not self.store.session_completed(session["session_id"]):
                self.store.append_event(
                    "SESSION_COMPLETE", {"session_id": session["session_id"]}
                )
                # Layer 1 auto-learning: reward productive apps on clean completion
                self._apply_session_feedback(session, completed=True)
                # Trigger background ML retrain (thread-safe, cooldown-guarded)
                self.learning_manager.trigger_training()
                if self.active_monitor:
                    self.active_monitor.stop()

            return {
                "active":     False,
                "completed":  True,
                "summary": {
                    "duration":   session.get("expected_duration", 0),
                    "violations": self.store.get_violation_count(session["session_id"]),
                    "penalties":  self.store.get_penalty_seconds(session["session_id"]),
                    "mode":       session.get("mode", "deep"),
                    "intent":     session.get("intent", "None"),
                    "intent_key": session.get("intent_key", "global"),
                    "streak":     session.get("streak", 1),
                },
                "user_stats": self.store.get_user_stats(),
            }

        remaining  = max(0, int((adjusted_end - now).total_seconds()))
        prediction = self._predict_failure(session)

        return {
            "active":            True,
            "mode":              session.get("mode", "deep"),
            "remaining":         remaining,
            "penalties":         penalty_seconds,
            "prediction":        prediction,
            "paused":            self.is_paused,
            "current_state":     self.current_state,
            "activity_snapshot": self.last_classified_state,
            "streak":            session.get("streak", 1),
            "intent_profile": {
                "intent_key":   self.intent_profile.intent_key
                                if self.intent_profile else "global",
                "strength":     self.intent_profile.strength
                                if self.intent_profile else 0.0,
                "goal_verb":    self.intent_profile.goal_verb
                                if self.intent_profile else "",
                "goal_subject": self.intent_profile.goal_subject
                                if self.intent_profile else "",
            },
            "user_stats": self.store.get_user_stats(),
        }

    # ── Auto-Learning: End-of-Session ─────────────────────────────────────────

    def _apply_session_feedback(self, session: dict, completed: bool):
        """
        Layer 1: Record session outcome into UserProfile.
        Called on session complete (reward) or broken (penalize).
        """
        intent_key = session.get("intent_key", "global") or "global"
        with self._lock:
            productive = list(self.session_productive_apps)
            violated   = list(self.session_violated_apps)

        user_profile.record_session_outcome(
            intent_key      = intent_key,
            productive_apps = productive,
            violated_apps   = violated,
            completed       = completed,
        )

        label = "completed" if completed else "broken/stopped"
        log.info(
            "[Engine] Session %s — auto-learned: %d productive, %d violated "
            "apps in intent '%s'",
            label, len(productive), len(violated), intent_key,
        )

        # Reset tracking lists for next session
        with self._lock:
            self.session_productive_apps = []
            self.session_violated_apps   = []

    # ── Manual Feedback (Layer 2) ─────────────────────────────────────────────

    def apply_manual_feedback(self, app: str, title: str, correct_label: str):
        """
        Layer 2: User explicitly corrects a classification.
        Larger learning step; applied immediately and persisted.
        """
        intent_key = (
            self.intent_profile.intent_key if self.intent_profile else "global"
        )
        clf.apply_session_feedback(
            app           = app,
            title         = title,
            correct_label = correct_label,
            intent_key    = intent_key,
            manual        = True,
        )

    # ── Violations & Control ──────────────────────────────────────────────────

    def register_violation(self, violation_type: str):
        session = self.store.get_current_session()
        if not session:
            return

        count   = self.store.get_violation_count(session["session_id"])
        penalty = PENALTY_RULES[min(count, len(PENALTY_RULES) - 1)]

        self.store.append_event(
            "FOCUS_VIOLATION",
            {
                "session_id":     session["session_id"],
                "violation":      violation_type,
                "penalty_seconds": penalty,
            },
        )

    def heartbeat(self):
        session = self.store.get_current_session()
        if not session:
            return

        last = self.store.get_last_heartbeat(session["session_id"])
        now  = datetime.now()

        if last:
            gap = (now - last).total_seconds()
            if gap > HEARTBEAT_THRESHOLD:
                self.store.append_event(
                    "SUSPICIOUS_GAP",
                    {"session_id": session["session_id"], "gap_seconds": int(gap)},
                )

        self.store.append_event("HEARTBEAT", {"session_id": session["session_id"]})

    def extend_session(self, additional_minutes: int):
        session = self.store.get_current_session()
        if not session:
            return False
        self.store.append_event(
            "SESSION_EXTEND",
            {
                "session_id":       session["session_id"],
                "extension_minutes": int(additional_minutes),
            },
        )
        return True

    def stop_session(self):
        session = self.store.get_current_session()
        if not session:
            return False
        self._apply_session_feedback(session, completed=False)
        self.store.append_event(
            "SESSION_STOP", {"session_id": session["session_id"]}
        )
        if self.active_monitor:
            self.active_monitor.stop()
            self.active_monitor = None
        return True

    def break_session(self, excuse: str):
        session = self.store.get_current_session()
        if not session:
            return
        # Compute elapsed time for accurate historic_break_pattern analysis
        elapsed_seconds = 0.0
        try:
            elapsed_seconds = (
                datetime.now() - datetime.fromisoformat(session["start_time"])
            ).total_seconds() - session.get("paused_duration", 0)
        except Exception:
            pass
        self._apply_session_feedback(session, completed=False)
        self.store.append_event(
            "SESSION_BREAK_ATTEMPT", {"session_id": session["session_id"]}
        )
        self.store.append_event(
            "SESSION_BROKEN",
            {
                "session_id":      session["session_id"],
                "excuse":          excuse,
                "elapsed_seconds": round(elapsed_seconds, 1),
            },
        )

    def pause_session(self):
        if self.is_paused:
            return
        self.is_paused        = True
        self.pause_start_time = datetime.now()
        session = self.store.get_current_session()
        if session:
            self.store.append_event(
                "SESSION_PAUSED", {"session_id": session["session_id"]}
            )

    def resume_session(self):
        if not self.is_paused:
            return
        duration              = datetime.now() - self.pause_start_time
        self.is_paused        = False
        self.pause_start_time = None
        session = self.store.get_current_session()
        if session:
            self.store.append_event(
                "SESSION_RESUMED",
                {
                    "session_id":    session["session_id"],
                    "paused_seconds": duration.total_seconds(),
                },
            )

    # ── Failure Prediction ────────────────────────────────────────────────────

    def _predict_failure(self, session: dict):
        session_id   = session["session_id"]
        now          = datetime.now()
        total_paused = session.get("paused_duration", 0)
        elapsed_real = (now - datetime.fromisoformat(session["start_time"])).total_seconds()
        elapsed_active = elapsed_real - total_paused

        total         = session["expected_duration"] * 60
        elapsed_ratio = elapsed_active / total if total > 0 else 0

        signals = 0
        reasons = []

        if self.store.get_violation_count(session_id) >= 2:
            signals += 1
            reasons.append("Repeated focus violations")
        if self.store.get_penalty_seconds(session_id) >= 180:
            signals += 1
            reasons.append("High accumulated penalties")
        if elapsed_ratio >= 0.7:
            signals += 1
            reasons.append("Late-session fatigue window")
        if self.store.has_suspicious_gap(session_id):
            signals += 1
            reasons.append("Suspicious inactivity detected")
        if self.store.historic_break_pattern(elapsed_active):
            signals += 1
            reasons.append("Matches historical failure pattern")

        if signals >= PREDICTION_THRESHOLD:
            self.store.append_event(
                "FAILURE_PREDICTED",
                {"session_id": session_id, "signals": signals, "reasons": reasons},
            )
            return {"warning": True, "signals": signals, "reasons": reasons}
        return None
