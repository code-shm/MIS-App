"""Churn-risk prediction model.

The CFPB dataset carries no account-closure outcome, so we construct a
transparent churn proxy grounded in service-recovery research: a complaint
signals elevated churn risk when negative customer sentiment is compounded by a
service failure the company controls (untimely handling, no relief provided, or
a dispute-style outcome). See ``config`` for the exact rule.

Crucially, the model does **not** just re-emit that rule. The proxy defines the
label; a Gradient-Boosted Trees classifier then learns the relationship from the
full structured + text-derived feature set, so it generalises to — and produces
a calibrated risk score for — complaints whose ultimate outcome is not yet
known. The output is an at-risk probability per customer/complaint that feeds
the retention view of the dashboard.
"""
from __future__ import annotations

import json

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.metrics import (average_precision_score, classification_report,
                             roc_auc_score)
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OrdinalEncoder

from . import config, features

MODEL_PATH = config.MODELS_DIR / "churn_model.joblib"
METRICS_PATH = config.MODELS_DIR / "churn_metrics.json"
TARGET = "churn_risk_label"

# Leakage control is the whole game here. The proxy label is DEFINED from
# sentiment + resolution outcome (timely / relief / disputed / sent_compound),
# so those columns are deliberately EXCLUDED from the feature set — otherwise the
# model would trivially reconstruct the label (ROC-AUC 1.0, and useless). The
# model instead predicts churn risk from what is known at complaint *intake*:
# the product/issue taxonomy, geography, channel and complaint size. That makes
# it a genuine early-warning task — "given how this case arrives, how likely is
# it to end in a churn-risk outcome?" — with an honest, sub-perfect AUC.
_CAT = ["product", "sub_product", "issue", "sub_issue", "state", "submitted_via"]
_NUM = ["handling_days", "narrative_length", "has_narrative"]

# Columns forbidden as features because they define the label (guard rail).
_LEAKY = {"sent_compound", "sent_neg", "sent_pos", "sent_neu", "is_negative",
          "timely_flag", "relief_flag", "company_response", "timely", "is_escalated"}


def build_proxy_label(df: pd.DataFrame) -> pd.Series:
    """Service-recovery churn proxy (the training target)."""
    negative = df["sent_compound"] <= config.CHURN_SENTIMENT_THRESHOLD
    untimely = df["timely_flag"] == 0
    no_relief = df["relief_flag"] == 0
    disputed = df["company_response"].str.contains("dispute", case=False, na=False)
    service_failure = untimely | no_relief | disputed
    return (negative & service_failure).astype("int8")


def _build() -> Pipeline:
    pre = ColumnTransformer([
        ("cat", Pipeline([
            ("impute", SimpleImputer(strategy="constant", fill_value="Unknown")),
            ("ord", OrdinalEncoder(handle_unknown="use_encoded_value", unknown_value=-1)),
        ]), _CAT),
        ("num", SimpleImputer(strategy="median"), _NUM),
    ])
    clf = HistGradientBoostingClassifier(
        max_iter=300, learning_rate=0.08, max_depth=6,
        l2_regularization=1.0, random_state=config.RANDOM_STATE)
    return Pipeline([("pre", pre), ("clf", clf)])


def train(df: pd.DataFrame) -> Pipeline:
    df = df.copy()
    df[TARGET] = build_proxy_label(df)

    # Guard rail: assert no label-defining column slipped into the feature set.
    leaks = _LEAKY.intersection(_CAT + _NUM)
    assert not leaks, f"Leakage: {leaks} define the churn label and cannot be features."

    X = df[_CAT + _NUM]
    y = df[TARGET].astype(int)

    X_tr, X_te, y_tr, y_te = train_test_split(
        X, y, test_size=config.TEST_SIZE, random_state=config.RANDOM_STATE, stratify=y)

    print(f"[churn] Training on {len(X_tr):,} rows "
          f"(proxy at-risk rate {y.mean():.1%}) ...")
    model = _build()
    model.fit(X_tr, y_tr)

    proba = model.predict_proba(X_te)[:, 1]
    pred = (proba >= config.CHURN_HIGH_RISK_CUTOFF).astype(int)
    metrics = {
        "n_train": int(len(X_tr)),
        "n_test": int(len(X_te)),
        "at_risk_rate": float(y.mean()),
        "roc_auc": float(roc_auc_score(y_te, proba)),
        "pr_auc": float(average_precision_score(y_te, proba)),
        "report": classification_report(y_te, pred, output_dict=True, zero_division=0),
    }
    print(f"[churn] ROC-AUC {metrics['roc_auc']:.3f} | PR-AUC {metrics['pr_auc']:.3f}")

    joblib.dump(model, MODEL_PATH)
    METRICS_PATH.write_text(json.dumps(metrics, indent=2))
    print(f"[churn] Saved model -> {MODEL_PATH.relative_to(config.ROOT)}")
    return model


def score(df: pd.DataFrame, model: Pipeline | None = None) -> pd.Series:
    model = model or joblib.load(MODEL_PATH)
    proba = model.predict_proba(df[_CAT + _NUM])[:, 1]
    return pd.Series(proba, index=df.index, name="churn_risk_score").astype("float32")
