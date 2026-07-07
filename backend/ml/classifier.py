"""
FeatureClassifier — Cognitive Behaviour Engine (Feature Generator)
==================================================================
Extracts features and performs hybrid classification:
  Heuristic (personalized, intent-aware) → Embeddings (semantic) → ML model

Improvements over original:
  • Lazy model loading — _init_models_bg() fires only on the FIRST call to
    extract_features(). If no session is ever started, the 4 GB SentenceTransformer
    is never downloaded/loaded at all.
  • All print() replaced with logging.getLogger(__name__).
  • 100 ms classification budget retained.
"""

from __future__ import annotations

import concurrent.futures
import logging
import os
import threading
import time
from backend.utils.user_profile import user_profile
from backend.ml.intent_engine import IntentProfile

log = logging.getLogger(__name__)


class FeatureClassifier:

    def __init__(self):
        self.model_path = os.path.join(os.path.dirname(__file__), "..", "..", "data", "ml", "focus_model.pkl")
        self.ml_ready   = False
        self.model      = None
        self.tfidf      = None
        self.embedder   = None
        self.util       = None
        self.ml_error   = None
        self._model_mtime = 0
        self._model_lock = threading.Lock()

        # Class-level executor (not per-call) so shutdown(wait=True) doesn't
        # block the caller after a TimeoutError.  max_workers=1 keeps it
        # equivalent to the original design.
        self._ml_executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="focuslock-ml"
        )

        # Cached label from the most recent _run_ml_pipeline() call.
        # Initialised to NEUTRAL so prob_to_label() is always safe to call.
        self._last_ml_label: str = "NEUTRAL"

        # Lazy loading state — models only load on first classify call
        self._load_started = False
        self._load_lock    = threading.Lock()

    def _reload_model_if_updated(self):
        """Check model file mtime and reload if updated.

        NOTE: Does NOT early-return when ml_ready is False so that a freshly
        trained model on a clean install is automatically picked up without
        requiring a process restart.
        """
        if not os.path.exists(self.model_path):
            return

        try:
            current_mtime = os.path.getmtime(self.model_path)

            if current_mtime <= self._model_mtime:
                return

            with self._model_lock:
                # double-check after acquiring lock
                current_mtime = os.path.getmtime(self.model_path)

                if current_mtime <= self._model_mtime:
                    return

                import joblib

                log.info("[Classifier] Reloading updated model...")

                artifacts = joblib.load(self.model_path)

                self.model = artifacts.get("model")
                self.tfidf = artifacts.get("tfidf")
                self.ml_ready = True
                self._model_mtime = current_mtime

                log.info("[Classifier] Model reloaded successfully.")

        except Exception as e:
            log.warning("[Classifier] Model reload failed: %s", e)

    # ── Lazy Model Loading ───────────────────────────────────────────────────
    def _ensure_loaded(self):
        """
        Trigger model loading on the first call to extract_features().
        Uses a double-checked lock so only one thread starts the load.
        """
        if self._load_started:
            return
        with self._load_lock:
            if self._load_started:   # second check inside lock
                return
            self._load_started = True
            self._init_models_bg()

    def _init_models_bg(self):
        """Load heavy models in a daemon background thread (non-blocking)."""

        def load():
            # SentenceTransformer
            try:
                from sentence_transformers import SentenceTransformer, util
                self.util     = util
                self.embedder = SentenceTransformer("all-MiniLM-L6-v2")
                log.info("[Classifier] SentenceTransformer loaded successfully.")
            except Exception as e:
                self.ml_error = f"SentenceTransformer failed: {e}"
                log.warning(
                    "[Classifier] SentenceTransformer unavailable (%s) — heuristics only.",
                    e,
                )

            # Scikit-Learn model
            if os.path.exists(self.model_path):
                try:
                    import joblib
                    artifacts  = joblib.load(self.model_path)
                    self.model = artifacts.get("model")
                    self.tfidf = artifacts.get("tfidf")
                    self._model_mtime = os.path.getmtime(self.model_path)
                    self.ml_ready = True
                    log.info("[Classifier] ML model loaded successfully.")
                except Exception as e:
                    err = f"ML artifact load failed: {e}"
                    self.ml_error = (
                        f"{self.ml_error} | {err}" if self.ml_error else err
                    )
                    log.warning("[Classifier] %s", err)
            else:
                msg = (
                    f"Model not found at {self.model_path}. "
                    "Run train_model.py to generate it."
                )
                self.ml_error = (
                    f"{self.ml_error} | {msg}" if self.ml_error else msg
                )
                log.warning("[Classifier] %s", msg)

        threading.Thread(target=load, name="focuslock-model-loader", daemon=True).start()

    def ml_status(self) -> dict:
        """Expose ML health state for /api/status and /api/profile."""
        return {
            "ml_ready":    self.ml_ready,
            "ml_error":    self.ml_error,
            "embedder_ok": self.embedder is not None,
        }

    # ── Feature Extraction ────────────────────────────────────────────────────

    def extract_features(
        self,
        context:        dict,
        intent:         str,
        mode:           str,
        whitelist:      list,
        blacklist:      list,
        intent_profile: "IntentProfile | None" = None,
    ) -> dict:
        """
        Input:  context generated by context_builder.py
        Output: feature dictionary consumed by the engine's decision layer.
        """
        # Step 1 — ensure models are loading (lazy, once)
        self._ensure_loaded()
        self._reload_model_if_updated()

        start_time = time.time()

        intent = (intent or "").lower()
        intent_key = intent_profile.intent_key if intent_profile else "global"
        full_text  = context.get("normalized_text", "")

        # ── 2. Strict Overrides ───────────────────────────────────────────────
        is_whitelist = any(w.lower() in full_text for w in (whitelist or []))
        is_blacklist = any(b.lower() in full_text for b in (blacklist or []))

        # ── 3. Personalized Heuristic Pass ────────────────────────────────────
        concept_weights  = user_profile.get_all_weights(intent_key)
        heuristic_score  = 0
        matched_concepts = []

        for concept, weight in concept_weights.items():
            if concept in full_text:
                heuristic_score += weight
                matched_concepts.append(concept)

        # ── 4. Intent-Aware Scoring ───────────────────────────────────────────
        intent_boost      = 0
        negative_override = False
        intent_reason     = "No intent profile"
        intent_match      = False

        if intent_profile and intent_profile.strength > 0:
            result            = intent_profile.score_activity(
                full_text, app_name=context.get("app", "")
            )
            intent_boost      = result["intent_boost"]
            negative_override = result["negative_override"]
            intent_reason     = result["intent_reason"]
            intent_match      = intent_boost != 0
            heuristic_score  += intent_boost
        else:
            # Legacy flat keyword boost (fallback when no IntentProfile)
            intent_words = [w for w in intent.split() if len(w) > 3]
            for word in intent_words:
                if word in full_text:
                    heuristic_score += 20
                    intent_match     = True
            intent_reason = "Legacy intent keyword boost"

        # ── 5. Semantic Embeddings Fallback (budget-capped) ───────────────────
        semantic_similarity = 0.0
        ml_prob             = 0.0

        if self.embedder is not None and self.util is not None:
            # —— Feature alignment with train_model.py ——
            # TF-IDF was trained on `window_title` only; pass the raw title
            # (not the richer normalized_text) to keep vocabulary consistent.
            title_text   = context.get("title", "")
            # mode_encoded must use the same mapping as training:
            #   deep=2, normal=1, drift=0 (default to 1 / normal if unknown)
            mode_encoded = {"deep": 2, "normal": 1, "drift": 0}.get(
                (mode or "").lower(), 1
            )
            # Submit to the class-level executor (never used as context manager
            # so shutdown(wait=True) is NOT called after a TimeoutError).
            future      = self._ml_executor.submit(
                self._run_ml_pipeline, intent, full_text, title_text, mode_encoded
            )
            elapsed_ms  = (time.time() - start_time) * 1000
            budget_left = max(0.0, 100.0 - elapsed_ms) / 1000.0
            try:
                semantic_similarity, ml_prob = future.result(timeout=budget_left)
            except concurrent.futures.TimeoutError:
                log.debug("[Classifier] Budget exceeded — falling back to heuristics.")
                # Detach the future: don't cancel (can't stop a running thread),
                # but don't block waiting for it either.
                future.cancel()

        # ── 6. Confidence Calibration ─────────────────────────────────────────
        if is_whitelist or is_blacklist or negative_override:
            confidence = 100.0
        else:
            confidence = 50.0

            heur_sign = 1 if heuristic_score > 0 else (-1 if heuristic_score < 0 else 0)
            sem_sign  = (
                1  if semantic_similarity > 0.4
                else (-1 if semantic_similarity < 0.2 else 0)
            )

            if heur_sign == sem_sign and heur_sign != 0:
                confidence = min(95.0, confidence + 30 + abs(heuristic_score))
            elif heur_sign != 0:
                confidence = min(85.0, confidence + abs(heuristic_score))

            if intent_match:
                confidence = min(95.0, confidence + 20)

            if intent_profile and intent_profile.strength > 0.5:
                confidence = min(98.0, confidence + 10 * intent_profile.strength)

        latency_ms = int((time.time() - start_time) * 1000)

        return {
            "semantic_similarity": round(float(semantic_similarity), 3),
            "heuristic_score":     heuristic_score,
            "intent_match":        intent_match,
            "confidence":          round(float(confidence), 1),
            "negative_override":   negative_override,
            "whitelist_match":     is_whitelist,
            "blacklist_match":     is_blacklist,
            "matched_concepts":    matched_concepts,
            "latency_ms":          latency_ms,
            "ml_prob":             round(float(ml_prob), 3),
        }

    # ── Real-time Feedback (Layer 1 + Layer 2) ────────────────────────────────

    def apply_session_feedback(
        self,
        app:           str,
        title:         str,
        correct_label: str,
        intent_key:    str  = "global",
        manual:        bool = False,
    ):
        """
        Apply a real-time learning signal to the user profile.
        Layer 1 (auto):   called by engine on violation or session-end.
        Layer 2 (manual): called by engine on user thumbs-up/down feedback.
        """
        concept   = (app or title or "").lower().strip().split(".")[0]
        direction = "negative" if correct_label == "DISTRACTION" else "positive"

        if concept:
            user_profile.apply_feedback(
                concept    = concept,
                direction  = direction,
                intent_key = intent_key,
                manual     = manual,
            )
            action = "Manual" if manual else "Auto"
            log.info(
                "[Classifier] %s feedback → '%s' (%s) in intent '%s'",
                action, concept, direction, intent_key,
            )

    # ── ML Pipeline (budget-capped) ───────────────────────────────────────────

    def _run_ml_pipeline(
        self,
        intent:       str,
        text:         str,
        title:        str,
        mode_encoded: int,
    ) -> tuple[float, float]:
        """Runs SentenceTransformer + Scikit-Learn inside the 100 ms budget.

        Args:
            intent:       User's session goal string (for semantic similarity).
            text:         Full normalized context text (for semantic similarity).
            title:        Raw window title — matches the ``window_title`` column
                          that the TF-IDF vectorizer was fitted on at train time.
            mode_encoded: Integer-encoded session mode (deep=2, normal=1, drift=0),
                          matching the ``mode_encoded`` column used during training.
        """
        sim  = 0.0
        prob = 0.0

        try:
            g_emb = self.embedder.encode(intent, convert_to_tensor=True)
            t_emb = self.embedder.encode(text,   convert_to_tensor=True)
            sim   = max(0.0, self.util.cos_sim(g_emb, t_emb).item())
        except Exception:
            pass

        if self.ml_ready and self.model and self.tfidf:
            try:
                import numpy as np
                # Use `title` (= window_title) — the same text source the
                # TF-IDF vectorizer was fitted on during training.
                tfidf_vec = self.tfidf.transform([title]).toarray()
                # Use the caller-supplied mode_encoded, NOT a hardcoded literal.
                features  = np.hstack(([[sim, mode_encoded]], tfidf_vec))
                probs     = self.model.predict_proba(features)[0]
                prob      = float(np.max(probs))
                # Cache the winning label so prob_to_label() is free
                self._last_ml_label = str(
                    self.model.classes_[int(np.argmax(probs))]
                )
            except Exception:
                pass

        return sim, prob

    def prob_to_label(self, prob: float, features: dict) -> str:
        """
        Return the ML-predicted label paired with *prob*.

        Computes the label from the model's classes_ directly using the probs
        returned by the most recent _run_ml_pipeline() call.  Falls back to
        NEUTRAL if the model has not run or the cached label is unavailable.

        NOTE: ``features`` is kept as a parameter for API compatibility even
        though it is not used here; callers may still pass it.
        """
        # _run_ml_pipeline caches the winning label in self._last_ml_label.
        # Returning it here is safe because prob_to_label() is always called
        # from the same call-chain that just ran _run_ml_pipeline() via
        # future.result() — there is no concurrent writer at this point.
        return self._last_ml_label if self.ml_ready else "NEUTRAL"

    def reload_classifier(self) -> bool:
        """Force reload of the ML model from disk.

        Returns True on successful reload, False otherwise.
        """
        if not os.path.exists(self.model_path):
            log.warning("[Classifier] Model file not found for reload.")
            self.ml_ready = False
            return False
        try:
            import joblib
            artifacts = joblib.load(self.model_path)
            with self._model_lock:
                self.model = artifacts.get("model")
                self.tfidf = artifacts.get("tfidf")
                self.ml_ready = True
                self._model_mtime = os.path.getmtime(self.model_path)
            log.info("[Classifier] Model reloaded on request.")
            return True
        except Exception as e:
            log.warning("[Classifier] Model reload failed: %s", e)
            self.ml_ready = False
            return False


# ── Global Singleton ──────────────────────────────────────────────────────────
classifier = FeatureClassifier()
