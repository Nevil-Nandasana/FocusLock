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
# This ensures every subsequent module's logging.getLogger() calls route to
# our RotatingFileHandler. Order matters — do NOT move this block.
from backend.logger import setup_logging

_debug_mode = os.environ.get("FLASK_DEBUG", "0") == "1"
setup_logging(debug=_debug_mode)

import logging
log = logging.getLogger(__name__)

# ── Flask app ──────────────────────────────────────────────────────────────────
from flask import Flask, render_template, request, jsonify, make_response
from backend.engine import FocusEngine

app = Flask(__name__, template_folder="templates", static_folder="static")

# Secret key — required for session cookies; pulled from env in production
app.secret_key = os.environ.get("FLASK_SECRET_KEY") or os.urandom(24)

engine = FocusEngine()

# Optional API key for protecting the /api/* endpoints from other local processes.
# Set FOCUSLOCK_API_KEY in the environment to enable. Leave unset (dev default) to disable.
_API_KEY = os.environ.get("FOCUSLOCK_API_KEY")


# ── Security Middleware ───────────────────────────────────────────────────────

@app.before_request
def check_api_key():
    """
    If FOCUSLOCK_API_KEY is set, require X-API-KEY header on all /api/* routes.
    Browser preflight (OPTIONS) and UI routes are always allowed.
    """
    if request.method == "OPTIONS":
        return
    if not request.path.startswith("/api/"):
        return
    if not _API_KEY:
        return   # key not configured → open (development mode)
    if request.headers.get("X-API-KEY") != _API_KEY:
        log.warning("[run] Unauthorized API request from %s to %s",
                    request.remote_addr, request.path)
        return jsonify({"error": "Unauthorized"}), 401


@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"]  = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, X-API-KEY"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return response


# ── UI Routes ─────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/analytics")
def analytics():
    from backend.store import EventStore
    store  = EventStore()
    events = store.get_events()

    total     = sum(1 for e in events if e["type"] == "SESSION_START")
    broken    = sum(1 for e in events if e["type"] == "SESSION_BROKEN")
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


# ── API Routes ─────────────────────────────────────────────────────────────────

@app.route("/api/start", methods=["POST"])
def api_start():
    data = request.json or {}

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

    engine.start_session(
        duration,
        data.get("mode", "deep"),
        whitelist=wl,
        blacklist=bl,
        intent=data.get("intent", ""),
    )
    log.info("[run] Session started — duration=%d mode=%s", duration, data.get("mode", "deep"))
    return jsonify({"status": "started"})


@app.route("/api/continue", methods=["POST"])
def api_continue():
    data    = request.json
    success = engine.extend_session(data.get("duration", 10))
    return jsonify({"status": "extended" if success else "failed"})


@app.route("/api/stop", methods=["POST"])
def api_stop():
    success = engine.stop_session()
    log.info("[run] Session stopped — success=%s", success)
    return jsonify({"status": "stopped" if success else "failed"})


@app.route("/api/afk", methods=["POST"])
def api_afk():
    data = request.json
    if data.get("status"):
        engine.pause_session()
        return jsonify({"status": "paused"})
    else:
        engine.resume_session()
        return jsonify({"status": "resumed"})


@app.route("/api/status")
def api_status():
    return jsonify(engine.get_status())


@app.route("/api/violation", methods=["POST"])
def api_violation():
    engine.register_violation(request.json["type"])
    return jsonify({"status": "logged"})


@app.route("/api/heartbeat", methods=["POST"])
def api_heartbeat():
    engine.heartbeat()
    return jsonify({"status": "alive"})


@app.route("/api/break", methods=["POST"])
def api_break():
    engine.break_session(request.json.get("excuse", "No reason"))
    return jsonify({"status": "broken"})


@app.route("/api/integrity")
def api_integrity():
    valid, message = engine.store.verify_integrity()
    return jsonify({"valid": valid, "message": message})


@app.route("/api/feedback", methods=["POST"])
def api_feedback():
    """
    Layer 2 manual feedback — user corrects a classification.
    Body: { "label": "PRODUCTIVE"|"DISTRACTION", "app": "...", "title": "...",
            "log_id": "...", "comment": "..." }
    """
    from backend.logger import logger
    data  = request.json or {}
    label = data.get("label", "")
    app_  = data.get("app",   "")
    title = data.get("title", "")

    if label in ("PRODUCTIVE", "DISTRACTION") and (app_ or title):
        engine.apply_manual_feedback(app=app_, title=title, correct_label=label)

    logger.log_user_feedback(
        log_id        = data.get("log_id", ""),
        correct_label = label,
        comment       = data.get("comment", ""),
    )
    return jsonify({"status": "saved", "applied": bool(label and (app_ or title))})


@app.route("/api/profile")
def api_profile():
    """
    Expose the current user profile and ML health state.
    """
    from backend.user_profile import user_profile
    from backend.classifier   import classifier as clf

    profile_data = user_profile.get_summary()

    intent_info = None
    if engine.intent_profile:
        ip = engine.intent_profile
        intent_info = {
            "intent_key":       ip.intent_key,
            "raw_intent":       ip.raw_intent,
            "goal_verb":        ip.goal_verb,
            "goal_subject":     ip.goal_subject,
            "strength":         ip.strength,
            "positive_signals": ip.positive_signals[:10],
            "negative_signals": ip.negative_signals[:10],
        }

    return jsonify({
        "profile":        profile_data,
        "ml_status":      clf.ml_status(),
        "intent_profile": intent_info,
    })


# ── Entry Point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import webbrowser
    import time
    from threading import Thread

    log.info("[run] FocusLock starting — debug=%s", _debug_mode)

    # Open browser only on the main process (not Werkzeug's reloader child)
    if os.environ.get("WERKZEUG_RUN_MAIN") != "true":
        def open_browser():
            time.sleep(1.5)
            webbrowser.open("http://127.0.0.1:5000/")
            log.info("[run] Browser opened.")

        Thread(target=open_browser, daemon=True).start()

    app.run(debug=_debug_mode, use_reloader=_debug_mode)
