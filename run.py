"""
FocusLock — Flask Application Entry Point
==========================================
Production-grade startup:
  • setup_logging() called FIRST — all subsequent modules log to focuslock.log
  • No subprocess.run(train_model) — training is triggered in background by LearningManager
  • SECRET_KEY from environment (secure random fallback for dev)
  • debug mode env-controlled via FLASK_DEBUG=1
  • Optional API key middleware (FOCUSLOCK_API_KEY env var)
"""

import os
import sys

# ── Bootstrap logging BEFORE any other import ────────────────────────────────
from backend.utils.logger import setup_logging

_debug_mode = os.environ.get("FLASK_DEBUG", "0") == "1"
setup_logging(debug=_debug_mode)

import logging

log = logging.getLogger(__name__)

# ── Flask app ────────────────────────────────────────────────────────────────
from flask import Flask, render_template, request, jsonify, g
from backend.core.engine import FocusEngine

app = Flask(__name__, template_folder="templates", static_folder="static")

# Secret key — stable in prod, fallback only for dev
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-insecure-key-change-me")


# Thread-safe engine access (prevents issues in multi-thread/multi-worker)
def get_engine():
    if "engine" not in g:
        g.engine = FocusEngine()
    return g.engine


# Optional API key
_API_KEY = os.environ.get("FOCUSLOCK_API_KEY")

# Optional CORS control
ALLOWED_ORIGINS = os.environ.get("CORS_ORIGINS", "*")


# ── Security Middleware ───────────────────────────────────────────────────────


@app.before_request
def check_api_key():
    if request.method == "OPTIONS":
        return
    if not request.path.startswith("/api/"):
        return
    if not _API_KEY:
        return
    if request.headers.get("X-API-KEY") != _API_KEY:
        log.warning(
            "[run] Unauthorized API request from %s to %s",
            request.remote_addr,
            request.path,
        )
        return jsonify({"error": "Unauthorized"}), 401


@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = ALLOWED_ORIGINS
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, X-API-KEY"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return response


# ── Health Check ──────────────────────────────────────────────────────────────


@app.route("/health")
def health():
    return {"status": "ok"}, 200


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
def api_continue():
    data = request.get_json(silent=True) or {}
    success = get_engine().extend_session(data.get("duration", 10))
    return jsonify({"status": "extended" if success else "failed"})


@app.route("/api/stop", methods=["POST"])
def api_stop():
    success = get_engine().stop_session()
    log.info("[run] Session stopped — success=%s", success)
    return jsonify({"status": "stopped" if success else "failed"})


@app.route("/api/afk", methods=["POST"])
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
def api_violation():
    data = request.get_json(silent=True) or {}
    get_engine().register_violation(data.get("type", "unknown"))
    return jsonify({"status": "logged"})


@app.route("/api/heartbeat", methods=["POST"])
def api_heartbeat():
    get_engine().heartbeat()
    return jsonify({"status": "alive"})


@app.route("/api/break", methods=["POST"])
def api_break():
    data = request.get_json(silent=True) or {}
    get_engine().break_session(data.get("excuse", "No reason"))
    return jsonify({"status": "broken"})


@app.route("/api/recovery/correct", methods=["POST"])
def api_recovery_correct():
    from backend.core.window_utils import try_close_active_window

    engine = get_engine()
    engine.recovery_active = False

    if hasattr(engine, "session_corrected"):
        engine.session_corrected += 1

    try_close_active_window()
    return jsonify({"status": "corrected"})


@app.route("/api/recovery/ignore", methods=["POST"])
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


# ── Entry Point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import webbrowser
    import time
    from threading import Thread

    log.info("[run] FocusLock starting — debug=%s", _debug_mode)

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
