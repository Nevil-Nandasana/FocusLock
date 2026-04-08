"""
train_model.py — Offline ML Retrainer
======================================
Converts the raw training CSV into a persisted sklearn RandomForest model.

Usage:
  • As a module (called by LearningManager in background):
        from backend.train_model import train_model
        metrics = train_model()

  • As a standalone script (manual retrain):
        python -m backend.train_model
        python backend/train_model.py

Returns:
  dict with keys: samples, accuracy, model_path — useful for logging.
"""

from __future__ import annotations

import logging
import os

log = logging.getLogger(__name__)

# Resolve paths relative to THIS file — works regardless of CWD or .exe bundle
_HERE      = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH = os.path.join(_HERE, "focus_model.pkl")
DATA_PATH  = os.path.join(_HERE, "training_data.csv")


def train_model(data=None) -> dict:
    """
    Train (or retrain) the FocusLock RandomForest classifier and persist it.

    Args:
        data: Reserved for future use — pass a DataFrame or None to use the CSV.

    Returns:
        dict: { "samples": int, "accuracy": float, "model_path": str }
              Returns {} on failure (caller should log but not crash).
    """
    log.info("[TrainModel] Starting training run.")

    try:
        import pandas as pd
        import numpy as np
        import joblib
        from sklearn.model_selection import train_test_split
        from sklearn.ensemble import RandomForestClassifier
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.metrics import accuracy_score
        from sklearn.metrics.pairwise import cosine_similarity
    except ImportError as e:
        log.error("[TrainModel] Missing dependency: %s — training aborted.", e)
        return {}

    # ── 1. Load Data ──────────────────────────────────────────────────────────
    if not os.path.exists(DATA_PATH):
        log.warning("[TrainModel] Training data not found at %s — aborted.", DATA_PATH)
        return {}

    try:
        df = pd.read_csv(DATA_PATH)
    except Exception as e:
        log.error("[TrainModel] Failed to read training CSV: %s", e)
        return {}

    log.info("[TrainModel] Loaded %d rows from %s", len(df), DATA_PATH)

    if len(df) < 10:
        log.warning("[TrainModel] Too few samples (%d) — skipping retrain.", len(df))
        return {}

    # Drop rows with missing critical fields
    df = df.dropna(subset=["window_title", "goal", "label"])
    if df.empty:
        log.warning("[TrainModel] All rows dropped after NA filter — aborted.")
        return {}

    # ── 2. Feature Engineering ────────────────────────────────────────────────
    log.info("[TrainModel] Loading SentenceTransformer (all-MiniLM-L6-v2)…")
    try:
        from sentence_transformers import SentenceTransformer
        embedder = SentenceTransformer("all-MiniLM-L6-v2")
    except Exception as e:
        log.error("[TrainModel] SentenceTransformer load failed: %s — aborted.", e)
        return {}

    log.info("[TrainModel] Computing embeddings for %d rows…", len(df))
    try:
        goal_np  = embedder.encode(df["goal"].tolist(),         convert_to_numpy=True)
        title_np = embedder.encode(df["window_title"].tolist(), convert_to_numpy=True)
    except Exception as e:
        log.error("[TrainModel] Embedding computation failed: %s", e)
        return {}

    similarities = [
        float(cosine_similarity([g], [t])[0][0])
        for g, t in zip(goal_np, title_np)
    ]
    df["cosine_similarity"] = similarities
    df["mode_encoded"]      = df["mode"].map({"deep": 2, "normal": 1}).fillna(1)

    # TF-IDF over window titles
    tfidf  = TfidfVectorizer(max_features=1000, ngram_range=(1, 2))
    X_text = tfidf.fit_transform(df["window_title"]).toarray()

    X_numeric = df[["cosine_similarity", "mode_encoded"]].values
    X         = __import__("numpy").hstack((X_numeric, X_text))
    y         = df["label"]

    # ── 3. Train ──────────────────────────────────────────────────────────────
    log.info("[TrainModel] Training RandomForestClassifier (n_estimators=200)…")
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42
    )
    clf = RandomForestClassifier(
        n_estimators=200, random_state=42, class_weight="balanced"
    )
    clf.fit(X_train, y_train)

    # ── 4. Evaluate ───────────────────────────────────────────────────────────
    y_pred   = clf.predict(X_test)
    accuracy = float(accuracy_score(y_test, y_pred))
    log.info("[TrainModel] Accuracy: %.2f%%  (test set size=%d)", accuracy * 100, len(y_test))

    # ── 5. Persist ────────────────────────────────────────────────────────────
    try:
        import joblib as jl
        jl.dump({"model": clf, "tfidf": tfidf}, MODEL_PATH)
        log.info("[TrainModel] Model saved to %s", MODEL_PATH)
    except Exception as e:
        log.error("[TrainModel] Failed to save model: %s", e)
        return {}

    return {
        "samples":    len(df),
        "accuracy":   round(accuracy, 4),
        "model_path": MODEL_PATH,
    }


# ── Standalone entry point ────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    # Bootstrap minimal logging when run directly
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    result = train_model()
    if result:
        print(f"\n✅ Training complete: {result}")
    else:
        print("\n❌ Training failed — check logs above.")
        sys.exit(1)
