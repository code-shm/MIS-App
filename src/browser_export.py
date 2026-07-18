"""Export model artifacts the dashboard can run entirely in the browser.

Produces ``dashboards/html/scorer_assets.js`` (``window.SCORER_ASSETS``) holding:

  * **vader** — the exact VADER lexicon, booster/negation lists, special cases
    and constants, so the browser reproduces the same sentiment scores the
    pipeline used (emoji handling is omitted — complaint narratives are text).
  * **escalation** — a compact text-only TF-IDF + LogisticRegression model
    (vocabulary, idf, coefficients, intercept, stop-words) trained on the
    narratives, so the in-browser scorer gives a genuine escalation probability
    and can surface the words driving it (the model is linear = interpretable).

The heavy VADER lexicon (~7.5k terms) makes this ~200 KB, so the dashboard
lazy-loads it only when the Scorer tab is opened.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import (ENGLISH_STOP_WORDS,
                                             TfidfVectorizer)
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline

import vaderSentiment.vaderSentiment as vader

from . import config

OUT = config.ROOT / "dashboards" / "html" / "scorer_assets.js"
MAX_FEATURES = 3000


def _train_text_escalation() -> dict:
    df = pd.read_parquet(config.AMEX_SCORED, columns=["narrative", "has_narrative", "is_escalated"])
    df = df[df["has_narrative"] == 1]
    X, y = df["narrative"].fillna(""), df["is_escalated"].astype(int)
    print(f"[browser] Training text-only escalation model on {len(X):,} narratives ...")

    pipe = Pipeline([
        ("tfidf", TfidfVectorizer(max_features=MAX_FEATURES, ngram_range=(1, 2),
                                  stop_words="english", min_df=5, sublinear_tf=True,
                                  norm="l2", lowercase=True)),
        ("clf", LogisticRegression(max_iter=1000, class_weight="balanced",
                                   C=1.0, solver="liblinear", random_state=config.RANDOM_STATE)),
    ])
    Xtr, Xte, ytr, yte = train_test_split(X, y, test_size=0.2, random_state=config.RANDOM_STATE, stratify=y)
    pipe.fit(Xtr, ytr)
    auc = roc_auc_score(yte, pipe.predict_proba(Xte)[:, 1])
    print(f"[browser] Text-only escalation model ROC-AUC {auc:.3f}")

    import joblib
    joblib.dump(pipe, config.MODELS_DIR / "escalation_text_model.joblib")

    vec: TfidfVectorizer = pipe.named_steps["tfidf"]
    clf: LogisticRegression = pipe.named_steps["clf"]

    # vocabulary_ maps term -> column index; order arrays by index.
    vocab = vec.vocabulary_
    n = len(vocab)
    terms = [None] * n
    for term, idx in vocab.items():
        terms[idx] = term
    idf = vec.idf_.tolist()
    coef = clf.coef_[0].tolist()

    return {
        "terms": terms,
        "idf": [round(v, 5) for v in idf],
        "coef": [round(v, 5) for v in coef],
        "intercept": round(float(clf.intercept_[0]), 5),
        "sublinear": True,
        "norm": "l2",
        "ngram": [1, 2],
        "stopwords": sorted(ENGLISH_STOP_WORDS),
        "auc": round(float(auc), 3),
        "n_train": int(len(Xtr)),
    }


def _vader_assets() -> dict:
    analyzer = vader.SentimentIntensityAnalyzer()
    return {
        "lexicon": {k: round(v, 4) for k, v in analyzer.lexicon.items()},
        "boosters": {k: round(v, 4) for k, v in vader.BOOSTER_DICT.items()},
        "negate": list(vader.NEGATE),
        "special_cases": {k: float(v) for k, v in vader.SPECIAL_CASES.items()},
        "constants": {"B_INCR": vader.B_INCR, "B_DECR": vader.B_DECR,
                      "C_INCR": vader.C_INCR, "N_SCALAR": vader.N_SCALAR},
    }


def build() -> dict:
    assets = {"vader": _vader_assets(), "escalation": _train_text_escalation()}
    blob = json.dumps(assets, separators=(",", ":"))
    OUT.write_text("window.SCORER_ASSETS = " + blob + ";\n", encoding="utf-8")
    print(f"[browser] Wrote {OUT.relative_to(config.ROOT)} ({OUT.stat().st_size/1024:,.0f} KB) "
          f"| vader lexicon {len(assets['vader']['lexicon']):,} terms "
          f"| escalation vocab {len(assets['escalation']['terms']):,}")
    return assets


if __name__ == "__main__":
    build()
