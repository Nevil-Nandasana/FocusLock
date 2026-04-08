"""
LearningManager — Thread-Safe Background ML Training Orchestrator
=================================================================
Decouples ML retraining from the request/response cycle.

Design guarantees:
  • Thread-safe: threading.Lock() wraps the entire check-and-set block —
    no race condition possible (as opposed to a bare is_training flag check).
  • Cooldown: minimum TRAINING_COOLDOWN_SEC between runs to prevent spam.
  • Daemon thread: never blocks app shutdown.
  • Full traceback logged on failure — caller never crashes.
"""

from __future__ import annotations

import logging
import threading
import time

log = logging.getLogger(__name__)

TRAINING_COOLDOWN_SEC: int = 60   # minimum gap between successive training runs


class LearningManager:

    def __init__(self):
        self._lock         = threading.Lock()   # protects is_training + last_training
        self.is_training   = False
        self.last_training = 0.0                # unix timestamp of last completed run

    # ── Public API ────────────────────────────────────────────────────────────

    def trigger_training(self, data=None) -> bool:
        """
        Request a background training run.

        The check-and-set of is_training happens atomically under self._lock,
        which eliminates the race condition that a bare flag check would have.

        Args:
            data: Optional supplementary data passed to train_model() — reserved
                  for future use; currently train_model() reads from the CSV.

        Returns:
            True  — training thread was launched.
            False — skipped (already running, or cooldown active).
        """
        with self._lock:
            # Guard 1: already running
            if self.is_training:
                log.info(
                    "[LearningManager] Skipped — training already in progress."
                )
                return False

            # Guard 2: cooldown window
            elapsed = time.time() - self.last_training
            if elapsed < TRAINING_COOLDOWN_SEC:
                log.info(
                    "[LearningManager] Skipped — cooldown active "
                    "(%.0fs < %ds).", elapsed, TRAINING_COOLDOWN_SEC
                )
                return False

            # Commit to training — set flag inside the lock
            self.is_training = True

        thread = threading.Thread(
            target=self._train,
            args=(data,),
            name="focuslock-trainer",
            daemon=True,           # never blocks app shutdown
        )
        thread.start()
        log.info("[LearningManager] Background training thread launched.")
        return True

    # ── Private ───────────────────────────────────────────────────────────────

    def _train(self, data) -> None:
        """
        Runs inside the daemon thread.
        Imports train_model lazily to avoid circular imports.
        """
        try:
            from backend.train_model import train_model
            metrics = train_model(data)
            if metrics:
                log.info(
                    "[LearningManager] Training complete — samples=%s  "
                    "accuracy=%.2f%%  path=%s",
                    metrics.get("samples", "?"),
                    metrics.get("accuracy", 0) * 100,
                    metrics.get("model_path", "?"),
                )
            else:
                log.warning(
                    "[LearningManager] train_model() returned empty — "
                    "check training data."
                )
        except Exception as e:
            log.error(
                "[LearningManager] Training failed: %s", e, exc_info=True
            )
        finally:
            with self._lock:
                self.is_training   = False
                self.last_training = time.time()
            log.info("[LearningManager] Training thread finished.")
