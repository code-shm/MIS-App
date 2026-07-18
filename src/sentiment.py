"""VADER sentiment enrichment of complaint narratives.

VADER (Valence Aware Dictionary and sEntiment Reasoner) is a lexicon+rule model
tuned for short, informal text — a good fit for consumer complaint narratives.
For each narrative we keep the four VADER scores plus a discrete label and an
intensity band that the dashboards and models consume.

Complaints with no narrative (~57% of CFPB rows are redacted to empty) are
scored neutral and flagged, so downstream models can treat "no text" as its own
signal rather than silently imputing sentiment.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

from . import config

_ANALYZER = SentimentIntensityAnalyzer()


def score_text(text: str) -> dict:
    if not isinstance(text, str) or not text.strip():
        return {"neg": 0.0, "neu": 1.0, "pos": 0.0, "compound": 0.0}
    return _ANALYZER.polarity_scores(text)


def _label(compound: float) -> str:
    if compound >= 0.05:
        return "Positive"
    if compound <= -0.05:
        return "Negative"
    return "Neutral"


def _band(compound: float) -> str:
    if compound <= -0.6:
        return "Very Negative"
    if compound <= -0.05:
        return "Negative"
    if compound < 0.05:
        return "Neutral"
    if compound < 0.6:
        return "Positive"
    return "Very Positive"


def enrich(df: pd.DataFrame, text_col: str = "narrative") -> pd.DataFrame:
    """Add VADER columns to ``df`` in place-safe fashion."""
    df = df.copy()
    print(f"[sentiment] Scoring {len(df):,} narratives with VADER ...")

    scores = df[text_col].map(score_text)
    sframe = pd.DataFrame(list(scores), index=df.index)
    df["sent_neg"] = sframe["neg"].astype("float32")
    df["sent_neu"] = sframe["neu"].astype("float32")
    df["sent_pos"] = sframe["pos"].astype("float32")
    df["sent_compound"] = sframe["compound"].astype("float32")

    df["sentiment_label"] = df["sent_compound"].map(_label).astype("string")
    df["sentiment_band"] = df["sent_compound"].map(_band).astype("string")
    df["is_negative"] = (df["sent_compound"] <= config.CHURN_SENTIMENT_THRESHOLD).astype("int8")

    scored = df[df["has_narrative"] == 1]
    if len(scored):
        dist = scored["sentiment_label"].value_counts(normalize=True)
        print("[sentiment] Narrative sentiment mix: "
              + ", ".join(f"{k} {v:.0%}" for k, v in dist.items()))
    return df
