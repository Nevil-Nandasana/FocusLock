"""
FocusLogger — Structured Logging Foundation
============================================
Provides:
  1. setup_logging()      — called once from run.py to configure the root logger.
                            RotatingFileHandler → focuslock.log (5 MB × 3 backups)
                            StreamHandler     → console (DEBUG in dev, WARNING in prod)
  2. FocusLogger class    — domain-specific activity/training/feedback JSONL logging.
  3. logger singleton     — global instance used by engine, classifier, etc.
"""

import os
import json
import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime

# ── Path Setup ────────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "backend", "data")
LOGS_DIR = os.path.join(DATA_DIR, "logs")
LOG_FILE = os.path.join(BASE_DIR, "focuslock.log")

os.makedirs(LOGS_DIR, exist_ok=True)


# ── Root Logging Bootstrap ────────────────────────────────────────────────────

def setup_logging(debug: bool = False) -> None:
    """
    Configure the root logger once at app startup.
    Call this from run.py BEFORE creating the Flask app.

    Args:
        debug: If True, console log level is DEBUG. Otherwise WARNING.
    """
    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Rotating file handler — 5 MB per file, 3 backups
    file_handler = RotatingFileHandler(
        LOG_FILE,
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(fmt)

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.DEBUG if debug else logging.WARNING)
    console_handler.setFormatter(fmt)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    # Avoid adding duplicate handlers if called more than once (e.g. in tests)
    if not root.handlers:
        root.addHandler(file_handler)
        root.addHandler(console_handler)

    # Silence verbose third-party loggers
    for lib in ("werkzeug", "sentence_transformers", "transformers", "torch",
                "filelock", "urllib3"):
        logging.getLogger(lib).setLevel(logging.WARNING)

    logging.getLogger("focuslock").info(
        "Logging initialised — file: %s | debug=%s", LOG_FILE, debug
    )


# ── Domain Logger (JSONL activity + training data) ───────────────────────────

class FocusLogger:
    """
    Writes structured JSONL activity logs and training CSV rows.
    Uses Python's logging module for internal errors.
    """

    def __init__(self):
        self._log = logging.getLogger(f"{__name__}.FocusLogger")

        self.log_file      = os.path.join(
            LOGS_DIR, f"activity_log_{datetime.now().strftime('%Y-%m-%d')}.jsonl"
        )
        self.training_file = os.path.join(DATA_DIR, "training_data.csv")
        self.feedback_file = os.path.join(DATA_DIR, "feedback.json")

        self._init_files()

    def _init_files(self):
        # Create CSV header if it doesn't exist
        if not os.path.exists(self.training_file):
            try:
                with open(self.training_file, "w", encoding="utf-8") as f:
                    f.write(
                        "timestamp,title,app,url,goal,mode,"
                        "similarity,heuristic,confidence,label\n"
                    )
            except OSError as e:
                self._log.error("Could not create training file: %s", e)

        # Create feedback JSON array
        if not os.path.exists(self.feedback_file):
            try:
                with open(self.feedback_file, "w", encoding="utf-8") as f:
                    json.dump([], f)
            except OSError as e:
                self._log.error("Could not create feedback file: %s", e)

    # ── Public API ────────────────────────────────────────────────────────────

    def log_activity(
        self,
        timestamp: str,
        title: str,
        app: str,
        similarity: float,
        heuristic: float,
        confidence: float,
        classification: str,
        behavior: str,
    ):
        """Append one classification event to today's JSONL activity log."""
        entry = {
            "time":           timestamp,
            "title":          title,
            "app":            app,
            "similarity":     similarity,
            "heuristic":      heuristic,
            "confidence":     confidence,
            "classification": classification,
            "behavior":       behavior,
        }
        
        # Log to Python logging stream cleanly
        self._log.info(
            f"[{behavior}] {classification} (Conf: {confidence} | Sim: {similarity} | Heur: {heuristic}) -> {app}: {title}"
        )
        
        try:
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
        except OSError as e:
            self._log.error("log_activity write failed: %s", e)

    def log_training_row(
        self,
        title: str,
        app: str,
        url: str,
        goal: str,
        mode: str,
        similarity: float,
        heuristic: float,
        confidence: float,
        label: str,
    ):
        """Append one row to the living training CSV for future retrains."""
        timestamp = datetime.now().isoformat()
        row = (
            f'{timestamp},"{title}","{app}","{url}",'
            f'"{goal}",{mode},{max(0, similarity)},'
            f"{heuristic},{confidence},{label}\n"
        )
        try:
            with open(self.training_file, "a", encoding="utf-8") as f:
                f.write(row)
        except OSError as e:
            self._log.error("log_training_row write failed: %s", e)

    def log_user_feedback(
        self,
        log_id: str,
        correct_label: str,
        comment: str = "",
    ):
        """Persist a user correction to feedback.json (read-modify-write with fallback)."""
        feedback = {
            "timestamp":     datetime.now().isoformat(),
            "log_id":        log_id,
            "correct_label": correct_label,
            "comment":       comment,
        }
        try:
            with open(self.feedback_file, "r+", encoding="utf-8") as f:
                data = json.load(f)
                data.append(feedback)
                f.seek(0)
                json.dump(data, f, indent=2)
                f.truncate()
        except Exception:
            try:
                with open(self.feedback_file, "w", encoding="utf-8") as f:
                    json.dump([feedback], f, indent=2)
            except OSError as e:
                self._log.error("log_user_feedback write failed: %s", e)


# ── Global Singleton ──────────────────────────────────────────────────────────
logger = FocusLogger()
