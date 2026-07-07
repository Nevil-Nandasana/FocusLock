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

from backend.core.store            import EventStore
from backend.core.monitor          import WindowMonitor
from backend.ml.classifier       import classifier as clf
from backend.core.context_builder  import build_context
from backend.utils.logger           import logger
from backend.ml.intent_engine    import intent_engine, IntentProfile
from backend.utils.user_profile     import user_profile
from backend.ml.learning_manager import LearningManager

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

        # Recovery Tracking
        self.recovery_active = False
        self.recovery_snapshot = None
        self.last_intervention_timestamp = 0
        self.session_distractions = 0
        self.session_ignored = 0
        self.session_corrected = 0

        # Drift tracking
        self.recent_switches = []

        # ── Intent awareness — parsed once per session ────────────────────────
        self.intent_profile: IntentProfile | None = None

        # ── Per-session app tracking for auto-learning ────────────────────────
        self.session_productive_apps: list[str] = []
        self.session_violated_apps:   list[str] = []

        # ── Background ML training orchestrator ───────────────────────────────
        self.learning_manager = LearningManager()

        # ── WARNING escalation tracking ────────────────────────────────────────────
        # If WARNING persists for >WARNING_ESCALATION_SEC without a new window
        # change event, a background timer re-runs classification against the
        # current window so prolonged distractions eventually escalate.
        self._warning_since: float = 0.0
        self._last_raw_state: dict = {}
        self._warning_timer: threading.Timer | None = None
        self.WARNING_ESCALATION_SEC = 30

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
        self.session_distractions    = 0
        self.session_ignored         = 0
        self.session_corrected       = 0
        self.recovery_active         = False
        self.recovery_snapshot       = None

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

        try:
            self.active_monitor = WindowMonitor(
                callback_state_change=self._on_state_change
            )
            self.active_monitor.start()
        except NotImplementedError as exc:
            log.warning(
                "[Engine] Window monitoring disabled on this platform: %s. "
                "API, logging, and dashboard will continue running normally.",
                exc,
            )
            self.active_monitor = None

    # ── Event-Driven Classification Pipeline ─────────────────────────────────

    def _on_state_change(self, raw_state: dict):
        if self.is_paused:
            return
        session = self.store.get_current_session()
        if not session:
            return

        now = time.time()
        
        # 0. Context Builder
        context = build_context(raw_state)

        # 1. Drift tracking (Independent Behavior State)
        with self._lock:
            self.recent_switches.append(now)
            self.recent_switches = [
                t for t in self.recent_switches if now - t <= DRIFT_WINDOW_SEC
            ]
            switches = len(self.recent_switches)
            behavior_state = "DRIFT" if switches > 5 else "NORMAL"

        # 2. Extract features
        features = clf.extract_features(
            context        = context,
            intent         = session.get("intent", ""),
            mode           = session.get("mode", "deep"),
            whitelist      = session.get("whitelist", []),
            blacklist      = session.get("blacklist", []),
            intent_profile = self.intent_profile,
        )

        confidence = features.get("confidence", 0)
        h_score    = features.get("heuristic_score", 0)
        ml_prob    = features.get("ml_prob", 0.0)
        ml_ready   = clf.ml_ready

        # 3. Decision Logic — 4-tier deterministic fusion
        #
        # Tier 0 (absolute): whitelist / blacklist / negative_override
        #   → Label set directly. ML and heuristics are not consulted.
        # Tier 1 (heuristic strong): |h_score| > 15
        #   → Heuristic determines label. ML may adjust confidence only.
        # Tier 2 (heuristic ambiguous): -15 ≤ h_score ≤ 15, ML ready
        #   → ML is the primary decision maker when ml_prob > 0.65.
        # Tier 2 fallback: ML not ready or prob ≤ 0.65 → NEUTRAL.
        # Tier 3 (confidence adjustment): applied after label is set.
        #   ML agreement boosts confidence; disagreement reduces it.

        classification = "NEUTRAL"
        reason         = "Ambiguous"

        if features.get("whitelist_match"):
            classification = "PRODUCTIVE"
            reason         = "Whitelist match"
        elif features.get("blacklist_match"):
            classification = "DISTRACTION"
            reason         = "Blacklist match"
        elif features.get("negative_override"):
            classification = "DISTRACTION"
            reason         = "Anti-intent app"
        else:
            # Tier 1 — heuristic is decisive
            if h_score < -15:
                classification = "DISTRACTION"
                reason         = "Distraction detected"
            elif h_score > 15:
                classification = "PRODUCTIVE"
                reason         = "Aligned"
            # Tier 2 — heuristic ambiguous; let ML decide if available
            elif ml_ready and ml_prob > 0.65:
                ml_label       = clf.prob_to_label(ml_prob, features)
                classification = ml_label
                reason         = f"ML decision (prob={ml_prob:.2f})"
            # else: remains NEUTRAL

        # Tier 3 — ML confidence adjustment (does NOT flip the label)
        # Only apply when label came from heuristics or ML (not from overrides).
        if (ml_ready and ml_prob > 0.65
                and not features.get("whitelist_match")
                and not features.get("blacklist_match")):
            ml_label = clf.prob_to_label(ml_prob, features)
            if ml_label == classification:
                confidence = min(98.0, confidence + 15)   # ML agrees: boost
            else:
                confidence = max(40.0, confidence - 10)   # ML disagrees: reduce

        # 4. Confidence Handling & Escalation
        final_state = classification
        if classification == "DISTRACTION":
            if confidence > 75:
                final_state = "DISTRACTION"
            elif confidence >= 50:
                final_state = "WARNING"
                reason = "Soft warning: " + reason
            else:
                final_state = "NEUTRAL"
                reason = "Ignored (low confidence)"

        if final_state == "PRODUCTIVE" and behavior_state == "DRIFT":
            final_state = "WARNING"
            reason = "Drifting behavior"

        # 5. State updates
        with self._lock:
            self.last_state = self.current_state

            # Enforce the FSM: only allow transitions listed in ALLOWED_TRANSITIONS.
            # An illegal jump (e.g. PRODUCTIVE → DISTRACTION) is clamped to the
            # intermediate WARNING state so the FSM is never bypassed silently.
            allowed = ALLOWED_TRANSITIONS.get(self.current_state, [final_state])
            if final_state not in allowed:
                log.warning(
                    "[Engine] Illegal FSM transition %s → %s; clamping to WARNING",
                    self.current_state, final_state,
                )
                final_state = "WARNING"

            self.current_state = final_state
            self.last_classified_state = {
                "app":      raw_state.get("app", ""),
                "title":    raw_state.get("title", ""),
                "state":    final_state,
                "classification": classification,
                "behavior": behavior_state,
                "features": features,
                "reason":   reason,
            }
            last_intervention = self.last_intervention_timestamp

            # ── WARNING escalation timer management ──────────────────────────────
            # Record when we entered WARNING so the timer can fire if we stay here.
            if final_state == "WARNING" and self.last_state != "WARNING":
                self._warning_since = now
                self._last_raw_state = raw_state
                self._schedule_warning_escalation()
            elif final_state != "WARNING":
                self._warning_since = 0.0
                self._cancel_warning_escalation()

            # Auto-reset recovery overlay when user returns to PRODUCTIVE
            if final_state == "PRODUCTIVE" and self.recovery_active:
                self.recovery_active = False
                log.info("[Engine] User returned to PRODUCTIVE — recovery overlay cleared.")

        # Track apps for end-of-session auto-learning
        app_name = (raw_state.get("app") or "").lower().split(".")[0]
        if app_name:
            with self._lock:
                if final_state == "PRODUCTIVE" and app_name not in self.session_productive_apps:
                    self.session_productive_apps.append(app_name)
                elif final_state == "DISTRACTION" and app_name not in self.session_violated_apps:
                    self.session_violated_apps.append(app_name)

        # 6. Cooldown + Escalation Layer
        if final_state == "DISTRACTION":
            with self._lock:
                if (now - last_intervention) > 10:
                    self.last_intervention_timestamp = now
                    
                    self.recovery_active = True
                    self.recovery_snapshot = {
                        "app": raw_state.get("app", ""),
                        "title": raw_state.get("title", ""),
                        "reason": reason
                    }
                    
                    try:
                        from backend.core.window_utils import focus_focuslock
                        focus_focuslock()
                    except Exception:
                        pass
                        
                    self.session_distractions += 1

                    self.register_violation(f"DISTRACTION: {reason}")
                    
                    if self.intent_profile:
                        clf.apply_session_feedback(
                            app           = raw_state.get("app", ""),
                            title         = raw_state.get("title", ""),
                            correct_label = "DISTRACTION",
                            intent_key    = self.intent_profile.intent_key,
                            manual        = False,
                        )

        # 7. Logging (Refined format)
        logger.log_activity(
            timestamp      = datetime.now().isoformat(),
            title          = raw_state.get("title", ""),
            app            = raw_state.get("app", ""),
            similarity     = features.get("semantic_similarity", 0),
            heuristic      = features.get("heuristic_score", 0),
            confidence     = features.get("confidence", 0),
            classification = classification,
            behavior       = behavior_state
        )

        # 8. Live training data collection
        # Write a row for every confident PRODUCTIVE / DISTRACTION classification
        # so the retrain loop learns from real session data, not just the static
        # seed CSV.  NEUTRAL is omitted — it adds noise without signal.
        if classification in ("PRODUCTIVE", "DISTRACTION"):
            try:
                logger.log_training_row(
                    title      = raw_state.get("title", ""),
                    app        = raw_state.get("app", ""),
                    url        = raw_state.get("url", ""),
                    goal       = session.get("intent", ""),
                    mode       = session.get("mode", "normal"),
                    similarity = features.get("semantic_similarity", 0),
                    heuristic  = features.get("heuristic_score", 0),
                    confidence = features.get("confidence", 0),
                    label      = classification,
                )
            except Exception as exc:
                log.debug("[Engine] log_training_row failed: %s", exc)

    # ── WARNING Escalation Helpers ───────────────────────────────────────────────

    def _schedule_warning_escalation(self):
        """Start a one-shot timer that re-fires classification if WARNING persists."""
        self._cancel_warning_escalation()
        self._warning_timer = threading.Timer(
            self.WARNING_ESCALATION_SEC, self._escalate_warning_if_stuck
        )
        self._warning_timer.daemon = True
        self._warning_timer.start()

    def _cancel_warning_escalation(self):
        """Cancel any pending WARNING escalation timer."""
        if self._warning_timer is not None:
            self._warning_timer.cancel()
            self._warning_timer = None

    def _escalate_warning_if_stuck(self):
        """Called by the timer if WARNING hasn’t cleared in WARNING_ESCALATION_SEC seconds.

        Re-runs classification against the last known raw_state so a prolonged
        WARNING on a distracting window can escalate to DISTRACTION without
        requiring a new window-change event to trigger the callback.
        """
        with self._lock:
            if self.current_state != "WARNING":
                return  # already resolved
            raw = dict(self._last_raw_state)

        log.info(
            "[Engine] WARNING persisted for >%ds without new event — "
            "re-running classification for escalation.",
            self.WARNING_ESCALATION_SEC,
        )
        # Re-invoke the state change handler with the last known raw state.
        # This may escalate WARNING → DISTRACTION if the window is still distraction.
        try:
            self._on_state_change(raw)
        except Exception as exc:
            log.debug("[Engine] _escalate_warning_if_stuck failed: %s", exc)

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
                    "total_distractions": self.session_distractions,
                    "ignored_distractions": self.session_ignored,
                    "corrected_distractions": self.session_corrected,
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
            "recovery_active":   self.recovery_active,
            "recovery_snapshot": self.recovery_snapshot,
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
