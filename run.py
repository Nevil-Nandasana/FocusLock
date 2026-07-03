"""
FocusLock — Flask Application Entry Point
==========================================
Production-grade startup:
  • setup_logging() called FIRST — all subsequent modules log to focuslock.log
  • FocusEngine is a module-level singleton — never recreated per request.
  • @atexit hook stops the monitor thread on clean process exit.
  • Daily background pruner keeps the event DB bounded.
  • SECRET_KEY from environment (secure random fallback for dev)
  • debug mode env-controlled via FLASK_DEBUG=1
  • Optional API key middleware (FOCUSLOCK_API_KEY env var)
"""

import os
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import sys

# ── Bootstrap logging BEFORE any other import ────────────────────────────────
from backend.utils.logger import setup_logging

_debug_mode = os.environ.get("FLASK_DEBUG", "0") == "1"
setup_logging(debug=_debug_mode)

import logging

log = logging.getLogger(__name__)

# ── Flask app ────────────────────────────────────────────────────────────────
from flask import Flask, render_template, request, jsonify
from backend.core.engine import FocusEngine

app = Flask(__name__, template_folder="templates", static_folder="static")
# Initialize CORS with allowed origins (environment variable or default '*')
CORS(app, resources={r"/api/*": {"origins": ALLOWED_ORIGINS}})
# Initialize rate limiter (default 100 requests per minute per IP)
limiter = Limiter(app=app, key_func=get_remote_address, default_limits=["100 per minute"])

# Secret key — generate a secure ephemeral key when env var is absent.
# This is safe for a local-only tool: sessions won't survive restarts, but
# the key is never predictable.  Set FLASK_SECRET_KEY for stable sessions.
_secret_key = os.environ.get("FLASK_SECRET_KEY", "").strip()
if not _secret_key:
    import secrets as _secrets
    _secret_key = _secrets.token_hex(32)
    log.warning(
        "[run] FLASK_SECRET_KEY not set — using a per-process ephemeral key. "
        "Set FLASK_SECRET_KEY in your environment for stable Flask sessions."
    )
app.secret_key = _secret_key


# ── Engine Singleton ────────────────────────────────────────────────────────
# FocusEngine is created ONCE for the lifetime of the process.
# flask.g is request-scoped — using it would spawn a new FocusEngine (and a
# new WindowMonitor thread) on every poll, creating hundreds of orphaned
# threads that never stop. The double-checked lock below is the correct fix.

import atexit as _atexit
import threading as _threading
import time as _time

# Application start timestamp for health checks
_START_TIME = _time.time()

_engine: "FocusEngine | None" = None
_engine_lock = _threading.Lock()


def get_engine() -> FocusEngine:
    """Return the process-wide FocusEngine singleton."""
    global _engine
    if _engine is None:               # fast path — no lock overhead
        with _engine_lock:
            if _engine is None:       # second check inside lock (DCLP)
                _engine = FocusEngine()
    return _engine


@_atexit.register
def _shutdown_engine():
    """
    Called by the Python interpreter on normal exit (Ctrl-C, SIGTERM, sys.exit).
    Stops the WindowMonitor thread so no OS handles or daemon threads are leaked.
    """
    if _engine is not None and _engine.active_monitor:
        _engine.active_monitor.stop()
        log.info("[run] Engine monitor stopped on shutdown.")


def boot_engine() -> "FocusEngine":
    """Initialize the FocusEngine singleton, purge old events, start pruning scheduler, and watchdog.

    Called explicitly to avoid side‑effects at import time.
    """
    engine = get_engine()
    engine.store.purge_old_events(days_to_keep=30)
    _start_pruning_scheduler(engine)
    _start_watchdog(engine)
    log.info("[run] FocusEngine boot complete: initial purge, scheduler, and watchdog started.")
    return engine


def _start_pruning_scheduler(engine: FocusEngine) -> None:
    """
    Launch a daemon thread that calls purge_old_events() once every 24 hours.
    Startup-only pruning is insufficient for long-running deployments that
    never restart — this covers those cases.
    """
    def _loop():
        while True:
            try:
                engine.store.purge_old_events(days_to_keep=30)
                log.info("[run] Daily event pruning complete.")
            except Exception as exc:
                log.warning("[run] Daily pruning failed: %s", exc)
            _time.sleep(24 * 60 * 60)   # sleep 24 h before next run

    t = _threading.Thread(target=_loop, name="focuslock-pruner", daemon=True)
    t.start()

# ── Integrity Watchdog ────────────────────────────────────────────────────────
def _start_watchdog(engine: FocusEngine) -> None:
    """Background thread that verifies store integrity every 5 minutes.
    Logs warnings if integrity checks fail.
    """
    def _loop():
        while True:
            try:
                valid, msg = engine.store.verify_integrity()
                if not valid:
                    log.warning("[run] Integrity watchdog detected issue: %s", msg)
                else:
                    log.debug("[run] Integrity watchdog check passed.")
            except Exception as exc:
                log.error("[run] Integrity watchdog exception: %s", exc)
            _time.sleep(5 * 60)  # 5 minutes
    t2 = _threading.Thread(target=_loop, name="focuslock-watchdog", daemon=True)
    t2.start()
    log.info("[run] Integrity watchdog started (interval=5m).")
    log.info("[run] Daily event pruner started (interval=24h, keep=30d).")


# API key configuration and loopback allow-set.
_API_KEY   = os.environ.get("FOCUSLOCK_API_KEY", "").strip()
_LOOPBACK  = frozenset({"127.0.0.1", "::1", "localhost", "::ffff:127.0.0.1"})

# Optional CORS control
ALLOWED_ORIGINS = os.environ.get("CORS_ORIGINS", "*")


# ── Security Middleware ───────────────────────────────────────────────────────


@app.before_request
def check_api_key():
    if request.method == "OPTIONS":
        return
    if not request.path.startswith("/api/"):
        return

    remote = (request.remote_addr or "").strip()
    is_loopback = remote in _LOOPBACK

    if _API_KEY:
        # Key is configured — enforce it for ALL callers including loopback.
        if request.headers.get("X-API-KEY") != _API_KEY:
            log.warning(
                "[run] Unauthorized API request from %s to %s",
                remote, request.path,
            )
            return jsonify({"error": "Unauthorized"}), 401
    elif not is_loopback:
        # No key configured but request is NOT from loopback — block.
        # This protects against accidental exposure if the operator binds
        # to 0.0.0.0 without setting FOCUSLOCK_API_KEY.
        log.warning(
            "[run] Non-loopback API call without key from %s to %s — blocked.",
            remote, request.path,
        )
        return jsonify({"error": "API key required for non-loopback callers"}), 403





# ── Health Check ──────────────────────────────────────────────────────────────


@app.route("/health")
def health():
    """Return health information including uptime, DB integrity, and model status."""
    uptime = _time.time() - _START_TIME
    engine = get_engine()
    db_valid, db_msg = engine.store.verify_integrity()
    model_status = getattr(engine, "classifier", None) is not None
    return {
        "status": "ok" if db_valid and model_status else "degraded",
        "uptime_seconds": int(uptime),
        "db_integrity": db_valid,
        "db_message": db_msg,
        "model_loaded": model_status,
    }, 200


# ── UI Routes ────────────────────────────────────────────────────────────────


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/analytics")
def analytics():
    from backend.core.store import EventStore

    store = EventStore()
    events = store.get_events()

    total = sum(1 for e in events if e["type"] == "SESSION_START")
    broken = sum(1 for e in events if e["type"] == "SESSION_BROKEN")
    predicted = sum(1 for e in events if e["type"] == "FAILURE_PREDICTED")

    rate = 0 if total == 0 else int(((total - broken) / total) * 100)

    return render_template(
        "analytics.html",
        events=events,
        total_sessions=total,
        failures=broken,
        success_rate=rate,
        predicted=predicted,
    )


# ── API Routes ────────────────────────────────────────────────────────────────


@app.route("/api/start", methods=["POST"])
@limiter.limit("10 per minute", methods=["POST"])
def api_start():
    data = request.get_json(silent=True) or {}

    duration = data.get("duration")
    if duration is None:
        return jsonify({"error": "duration is required"}), 400

    try:
        duration = int(duration)
    except (TypeError, ValueError):
        return jsonify({"error": "duration must be an integer"}), 400

    if duration <= 0 or duration > 1440:
        return jsonify({"error": "duration must be between 1 and 1440 minutes"}), 400

    wl = data.get("whitelist", [])
    bl = data.get("blacklist", [])

    if isinstance(wl, str):
        wl = [x.strip() for x in wl.split(",") if x.strip()]
    if isinstance(bl, str):
        bl = [x.strip() for x in bl.split(",") if x.strip()]

    get_engine().start_session(
        duration,
        data.get("mode", "deep"),
        whitelist=wl,
        blacklist=bl,
        intent=data.get("intent", ""),
    )

    log.info(
        "[run] Session started — duration=%d mode=%s",
        duration,
        data.get("mode", "deep"),
    )

    return jsonify({"status": "started"})


@app.route("/api/continue", methods=["POST"])
@limiter.limit("10 per minute", methods=["POST"])
def api_continue():
    data = request.get_json(silent=True) or {}
    success = get_engine().extend_session(data.get("duration", 10))
    return jsonify({"status": "extended" if success else "failed"})


@app.route("/api/stop", methods=["POST"])
@limiter.limit("10 per minute", methods=["POST"])
def api_stop():
    success = get_engine().stop_session()
    log.info("[run] Session stopped — success=%s", success)
    return jsonify({"status": "stopped" if success else "failed"})


@app.route("/api/afk", methods=["POST"])
@limiter.limit("10 per minute", methods=["POST"])
def api_afk():
    data = request.get_json(silent=True) or {}
    if data.get("status"):
        get_engine().pause_session()
        return jsonify({"status": "paused"})
    else:
        get_engine().resume_session()
        return jsonify({"status": "resumed"})


@app.route("/api/status")
def api_status():
    return jsonify(get_engine().get_status())


@app.route("/api/violation", methods=["POST"])
@limiter.limit("10 per minute", methods=["POST"])
def api_violation():
    data = request.get_json(silent=True) or {}
    get_engine().register_violation(data.get("type", "unknown"))
    return jsonify({"status": "logged"})


@app.route("/api/heartbeat", methods=["POST"])
@limiter.limit("10 per minute", methods=["POST"])
def api_heartbeat():
    get_engine().heartbeat()
    return jsonify({"status": "alive"})


@app.route("/api/break", methods=["POST"])
@limiter.limit("10 per minute", methods=["POST"])
def api_break():
    data = request.get_json(silent=True) or {}
    get_engine().break_session(data.get("excuse", "No reason"))
    return jsonify({"status": "broken"})


@app.route("/api/recovery/correct", methods=["POST"])
@limiter.limit("10 per minute", methods=["POST"])
def api_recovery_correct():
    # try_close_active_tab sends Ctrl+W to the foreground browser window,
    # closing only the active tab — never the entire browser window.
    from backend.core.window_utils import try_close_active_tab

    engine = get_engine()
    engine.recovery_active = False

    if hasattr(engine, "session_corrected"):
        engine.session_corrected += 1

    try_close_active_tab()
    return jsonify({"status": "corrected"})


@app.route("/api/recovery/ignore", methods=["POST"])
@limiter.limit("10 per minute", methods=["POST"])
def api_recovery_ignore():
    engine = get_engine()
    engine.recovery_active = False

    if hasattr(engine, "session_ignored"):
        engine.session_ignored += 1

    return jsonify({"status": "ignored"})


@app.route("/api/integrity")
def api_integrity():
    valid, message = get_engine().store.verify_integrity()
    return jsonify({"valid": valid, "message": message})


@app.route("/api/feedback", methods=["POST"])
@limiter.limit("10 per minute", methods=["POST"])
def api_feedback():
    from backend.utils.logger import logger

    data = request.get_json(silent=True) or {}
    label = data.get("label", "")
    app_ = data.get("app", "")
    title = data.get("title", "")

    if label in ("PRODUCTIVE", "DISTRACTION") and (app_ or title):
        get_engine().apply_manual_feedback(app=app_, title=title, correct_label=label)

    logger.log_user_feedback(
        log_id=data.get("log_id", ""),
        correct_label=label,
        comment=data.get("comment", ""),
    )

    return jsonify({"status": "saved"})


@app.route("/api/profile")
def api_profile():
    from backend.utils.user_profile import user_profile
    from backend.ml.classifier import classifier as clf

    engine = get_engine()
    profile_data = user_profile.get_summary()

    intent_info = None
    if engine.intent_profile:
        ip = engine.intent_profile
        intent_info = {
            "intent_key": ip.intent_key,
            "raw_intent": ip.raw_intent,
            "goal_verb": ip.goal_verb,
            "goal_subject": ip.goal_subject,
            "strength": ip.strength,
            "positive_signals": ip.positive_signals[:10],
            "negative_signals": ip.negative_signals[:10],
        }

    return jsonify(
        {
            "profile": profile_data,
            "ml_status": clf.ml_status(),
            "intent_profile": intent_info,
        }
    )


@app.route("/api/profile/weights")
@limiter.limit("10 per minute", methods=["GET"])
def api_profile_weights():
    """Return effective merged heuristic weights for a given intent bucket.

    Query param ``intent`` selects the bucket (default ``global``).
    Weights are sorted by |weight| descending so the most influential
    concepts appear first.  ``user_deltas`` shows only the learned deltas.
    """
    from backend.utils.user_profile import user_profile, DEFAULT_PROFILES
    intent_key = (request.args.get("intent", "global") or "global").strip().lower()
    effective  = user_profile.get_all_weights(intent_key)
    with user_profile._lock:
        user_deltas = dict(user_profile._deltas.get(intent_key, {}))
    return jsonify({
        "intent":      intent_key,
        "buckets":     sorted(set(DEFAULT_PROFILES.keys()) | set(user_profile._deltas.keys())),
        "weights":     dict(sorted(effective.items(), key=lambda kv: -abs(kv[1]))),
        "user_deltas": user_deltas,
    })

    @app.route("/api/reload_model", methods=["POST"])
    @limiter.limit("5 per minute", methods=["POST"])
    def api_reload_model():
        """Reload the ML model on demand.

        Protected by the existing API‑key middleware.
        Returns JSON with status "reloaded" or "failed".
        """
        success = clf.reload_classifier()
        if success:
            return jsonify({"status": "reloaded"}), 200
        else:
            return jsonify({"status": "failed"}), 500
# ── Entry Point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import webbrowser
    import time
    from threading import Thread

    log.info("[run] FocusLock starting — debug=%s", _debug_mode)

    # Initialise engine, purge old events, and start background pruning.
    boot_engine()

    if _debug_mode and os.environ.get("WERKZEUG_RUN_MAIN") != "true":
        def open_browser():
            time.sleep(1.5)
            webbrowser.open("http://127.0.0.1:5000/")
            log.info("[run] Browser opened.")
        Thread(target=open_browser, daemon=True).start()

    app.run(
        host="127.0.0.1",
        port=5000,
        debug=_debug_mode,
        use_reloader=_debug_mode,
    )
