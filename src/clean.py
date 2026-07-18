"""Cleaning + normalisation of the raw Amex complaints.

Turns the raw CFPB payload into an analysis-ready frame: de-duplicates,
derives calendar keys, computes the company handling-time in days, redacts the
CFPB ``XXXX`` placeholders out of narratives, and attaches the escalation label
that the classifier will learn.
"""
from __future__ import annotations

import re

import numpy as np
import pandas as pd

from . import config

_XXXX = re.compile(r"\bX{2,}\b")
_WS = re.compile(r"\s+")


def clean_narrative(text: str) -> str:
    """Strip CFPB PII redaction tokens and collapse whitespace."""
    if not isinstance(text, str) or not text:
        return ""
    text = _XXXX.sub(" ", text)
    text = _WS.sub(" ", text)
    return text.strip()


def add_escalation_label(df: pd.DataFrame) -> pd.DataFrame:
    relief = df["company_response"].isin(config.ESCALATION_RESPONSES)
    untimely = df["timely"].str.strip().str.lower().eq("no")
    df["is_escalated"] = (relief | untimely).astype("int8")
    return df


def clean(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    # De-duplicate on the complaint id.
    before = len(df)
    df = df.drop_duplicates(subset="complaint_id").reset_index(drop=True)
    print(f"[clean] Dropped {before - len(df):,} duplicate ids.")

    # Calendar keys for MIS time-series.
    dr = df["date_received"]
    df["year"] = dr.dt.year.astype("Int64")
    df["month"] = dr.dt.month.astype("Int64")
    df["year_month"] = dr.dt.to_period("M").astype("string")
    df["quarter"] = dr.dt.to_period("Q").astype("string")

    # Handling time: receipt -> forwarded to company (days).
    delta = (df["date_sent_to_company"] - df["date_received"]).dt.total_seconds() / 86400.0
    df["handling_days"] = delta.clip(lower=0).round(2)

    # Narrative hygiene + presence flag.
    df["narrative"] = df["complaint_what_happened"].map(clean_narrative).astype("string")
    df["has_narrative"] = (df["narrative"].str.len() > 0).astype("int8")
    df["narrative_length"] = df["narrative"].str.len().fillna(0).astype("int32")

    # Tidy categoricals.
    for c in ("product", "sub_product", "issue", "sub_issue", "state",
              "submitted_via", "company_response"):
        df[c] = df[c].fillna("Unknown").str.strip()

    df["timely_flag"] = df["timely"].str.strip().str.lower().eq("yes").astype("int8")
    df["relief_flag"] = df["company_response"].isin(config.ESCALATION_RESPONSES).astype("int8")

    df = add_escalation_label(df)

    print(f"[clean] {len(df):,} rows | {df['has_narrative'].sum():,} with narrative "
          f"| escalation rate {df['is_escalated'].mean():.1%}")
    return df
