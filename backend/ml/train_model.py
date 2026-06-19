"""
train_model.py — Improved Offline ML Retrainer
=============================================
Upgrades:
  • Controlled RandomForest (prevents overfitting)
  • Better evaluation (precision/recall/F1)
  • Safer feature handling
  • Cleaner logging + structure
"""

from __future__ import annotations

import logging
import os

log = logging.getLogger(__name__)

_HERE = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH = os.path.join(_HERE, "..", "..", "data", "ml", "focus_model.pkl")
PRIMARY_DATA_PATH = os.path.join(_HERE, "..", "..", "data", "ml", "training_data.csv")
PARSED_DATA_PATH = os.path.join(_HERE, "..", "..", "data", "ml", "parsed_dataset.csv")


# ─────────────────────────────────────────────────────────────
# Data Normalization
# ─────────────────────────────────────────────────────────────
def _normalize_training_frame(df, source_name: str):
    import pandas as pd

    if "title" in df.columns and "window_title" not in df.columns:
        df = df.rename(columns={"title": "window_title"})

    for col, default in {
        "window_title": "",
        "label": "",
        "goal": "",
        "mode": "normal",
    }.items():
        if col not in df.columns:
            df[col] = default

    if "similarity" not in df.columns:
        df["similarity"] = df.get("cosine_similarity", 0.0)

    # Clean
    df["window_title"] = df["window_title"].fillna("").astype(str).str.strip()
    df["goal"] = df["goal"].fillna("").astype(str).str.strip()
    df["mode"] = df["mode"].fillna("normal").astype(str).str.lower()
    df["label"] = df["label"].fillna("").astype(str).str.upper()

    df["similarity"] = pd.to_numeric(df["similarity"], errors="coerce").fillna(0.0)
    df["similarity"] = df["similarity"].clip(0.0, 1.0)

    allowed = {"PRODUCTIVE", "DISTRACTION", "NEUTRAL"}

    before = len(df)
    df = df[(df["window_title"].str.len() > 0) & (df["label"].isin(allowed))]
    dropped = before - len(df)

    if dropped:
        log.info("[Normalize] %s: dropped %d invalid rows", source_name, dropped)

    return df[["window_title", "goal", "mode", "label", "similarity"]].copy()


# ─────────────────────────────────────────────────────────────
# Training
# ─────────────────────────────────────────────────────────────
def train_model(data: list | None = None) -> dict:
    """
    Train the focus classifier.

    Args:
        data: Optional list of dicts collected from live classification
              sessions.  Each dict must contain keys matching the CSV schema:
              window_title (or title), goal, mode, label, similarity.
              When provided these rows are merged with the on-disk CSV before
              training, so the model continuously improves from real usage.
              Pass None (or omit) to train on static CSV data only.
    """
    log.info("[TrainModel] Starting training")

    try:
        import pandas as pd
        import numpy as np
        import joblib
        from sklearn.model_selection import train_test_split
        from sklearn.ensemble import RandomForestClassifier
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.metrics import (
            accuracy_score,
            classification_report,
            confusion_matrix,
        )
        from sklearn.metrics.pairwise import cosine_similarity
    except ImportError as e:
        log.error("[TrainModel] Missing dependency: %s", e)
        return {}

    # ── Load data ─────────────────────────────────────────────
    frames = []
    for name, path in [
        ("training_data.csv", PRIMARY_DATA_PATH),
        ("parsed_dataset.csv", PARSED_DATA_PATH),
    ]:
        if not os.path.exists(path):
            continue

        try:
            raw = pd.read_csv(path)
            norm = _normalize_training_frame(raw, name)
            if not norm.empty:
                frames.append(norm)
        except Exception as e:
            log.error("[TrainModel] Failed loading %s: %s", name, e)

    # ── Merge live session data ────────────────────────────────
    if data:
        try:
            supplementary = pd.DataFrame(data)
            supplementary = _normalize_training_frame(supplementary, "live_session_data")
            if not supplementary.empty:
                frames.append(supplementary)
                log.info(
                    "[TrainModel] Merged %d live rows from session data.",
                    len(supplementary),
                )
        except Exception as exc:
            log.warning("[TrainModel] Failed to merge live data: %s", exc)

    if not frames:
        log.warning("[TrainModel] No usable data")
        return {}

    df = pd.concat(frames, ignore_index=True)

    if len(df) < 20:
        log.warning("[TrainModel] Too few samples (%d)", len(df))
        return {}

    log.info("[TrainModel] Total samples: %d", len(df))

    # ── Feature Engineering ───────────────────────────────────
    df["cosine_similarity"] = df["similarity"].clip(0, 1)

    # Mode encoding (fixed)
    df["mode_encoded"] = df["mode"].map({"deep": 2, "normal": 1, "drift": 0}).fillna(1)

    # TF-IDF (stable size)
    tfidf = TfidfVectorizer(max_features=800, ngram_range=(1, 2), min_df=2)

    X_text = tfidf.fit_transform(df["window_title"]).toarray()
    X_numeric = df[["cosine_similarity", "mode_encoded"]].values

    import numpy as np

    X = np.hstack((X_numeric, X_text))
    y = df["label"]

    # ── Train/Test Split ──────────────────────────────────────
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )

    # ── Model (FIXED) ─────────────────────────────────────────
    clf = RandomForestClassifier(
        n_estimators=300,
        max_depth=20,
        min_samples_leaf=2,
        random_state=42,
        class_weight="balanced",
        n_jobs=-1,
    )

    log.info("[TrainModel] Training model...")
    clf.fit(X_train, y_train)

    # ── Evaluation ────────────────────────────────────────────
    y_pred = clf.predict(X_test)

    accuracy = accuracy_score(y_test, y_pred)
    report = classification_report(y_test, y_pred)
    matrix = confusion_matrix(y_test, y_pred)

    log.info("[TrainModel] Accuracy: %.2f%%", accuracy * 100)
    log.info("[TrainModel] Classification Report:\n%s", report)
    log.info("[TrainModel] Confusion Matrix:\n%s", matrix)

    # ── Save ─────────────────────────────────────────────────
    try:
        joblib.dump(
            {
                "model": clf,
                "tfidf": tfidf,
            },
            MODEL_PATH,
        )
        log.info("[TrainModel] Saved → %s", MODEL_PATH)
    except Exception as e:
        log.error("[TrainModel] Save failed: %s", e)
        return {}

    return {
        "samples": len(df),
        "accuracy": round(float(accuracy), 4),
        "model_path": MODEL_PATH,
    }


# ── Entry Point ──────────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    result = train_model()

    if result:
        print(f"\n✅ Training complete: {result}")
    else:
        print("\n❌ Training failed")
