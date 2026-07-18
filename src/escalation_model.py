"""Escalation classification model.

Predicts whether an incoming complaint will escalate — i.e. require tangible
relief or breach the timely-response SLA — from its structured attributes and
narrative text. In an ops setting this is the triage signal that routes a case
to a senior specialist before it turns into relief/regulatory exposure.

Model: TF-IDF + one-hot + scaled-numeric  ->  Logistic Regression
(class-weighted, calibrated probabilities). Logistic regression keeps the model
interpretable — the strongest escalation-driving terms are inspectable — which
matters for a governance-sensitive domain like complaints handling.
"""
from __future__ import annotations

import json

import joblib
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (average_precision_score, classification_report,
                             roc_auc_score)
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline

from . import config, features

MODEL_PATH = config.MODELS_DIR / "escalation_model.joblib"
METRICS_PATH = config.MODELS_DIR / "escalation_metrics.json"
TARGET = "is_escalated"


def _build() -> Pipeline:
    return Pipeline([
        ("pre", features.build_preprocessor()),
        ("clf", LogisticRegression(
            max_iter=2000, C=1.0, class_weight="balanced",
            solver="liblinear", random_state=config.RANDOM_STATE)),
    ])


def train(df: pd.DataFrame) -> Pipeline:
    X = df[features.REQUIRED]
    y = df[TARGET].astype(int)

    X_tr, X_te, y_tr, y_te = train_test_split(
        X, y, test_size=config.TEST_SIZE, random_state=config.RANDOM_STATE, stratify=y)

    print(f"[escalation] Training on {len(X_tr):,} rows "
          f"(base escalation rate {y.mean():.1%}) ...")
    model = _build()
    model.fit(X_tr, y_tr)

    proba = model.predict_proba(X_te)[:, 1]
    pred = (proba >= 0.5).astype(int)
    metrics = {
        "n_train": int(len(X_tr)),
        "n_test": int(len(X_te)),
        "base_rate": float(y.mean()),
        "roc_auc": float(roc_auc_score(y_te, proba)),
        "pr_auc": float(average_precision_score(y_te, proba)),
        "report": classification_report(y_te, pred, output_dict=True, zero_division=0),
    }
    print(f"[escalation] ROC-AUC {metrics['roc_auc']:.3f} | PR-AUC {metrics['pr_auc']:.3f}")

    joblib.dump(model, MODEL_PATH)
    METRICS_PATH.write_text(json.dumps(metrics, indent=2))
    print(f"[escalation] Saved model -> {MODEL_PATH.relative_to(config.ROOT)}")
    return model


def top_terms(model: Pipeline, k: int = 20) -> list[tuple[str, float]]:
    """Return the TF-IDF terms most predictive of escalation (interpretability)."""
    pre = model.named_steps["pre"]
    clf = model.named_steps["clf"]
    names = pre.get_feature_names_out()
    coefs = clf.coef_[0]
    order = np.argsort(coefs)[::-1][:k]
    return [(names[i].replace("text__", ""), float(coefs[i])) for i in order]


def score(df: pd.DataFrame, model: Pipeline | None = None) -> pd.Series:
    model = model or joblib.load(MODEL_PATH)
    proba = model.predict_proba(df[features.REQUIRED])[:, 1]
    return pd.Series(proba, index=df.index, name="escalation_score").astype("float32")
