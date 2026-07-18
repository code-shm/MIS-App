"""Agentic refresh — pull the latest complaints and update the dashboard.

Designed to run on a loop (see ``src.serve``) or on demand. It re-pulls the Amex
feed from the CFPB API (one request), and to stay fast it only runs VADER on
complaints it has never seen before — sentiment for known ids is read from the
cached enriched table. Existing trained models score every row; models are only
retrained when asked (``retrain=True``) or when they don't exist yet.

Writes a ``dashboards/html/version.json`` stamp (updated-at, row count, new rows)
that the live dashboard polls to know when to reload.

    python -m src.refresh              # one incremental refresh
    python -m src.refresh --retrain    # refresh and retrain the models
"""
from __future__ import annotations

import argparse
import datetime as dt
import json

import pandas as pd

from . import (churn_model, clean, config, dashboard_data, escalation_model,
               ingest, sentiment)
from .pipeline import KEEP

VERSION_FILE = config.ROOT / "dashboards" / "html" / "version.json"
_SENT_COLS = ["sent_neg", "sent_neu", "sent_pos", "sent_compound",
              "sentiment_label", "sentiment_band", "is_negative"]


def _write_version(rows: int, new_rows: int, retrained: bool) -> dict:
    payload = {
        "updated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "rows": int(rows),
        "new_rows": int(new_rows),
        "retrained": bool(retrained),
    }
    VERSION_FILE.write_text(json.dumps(payload))
    return payload


def refresh(retrain: bool = False) -> dict:
    print(f"[refresh] {dt.datetime.now():%Y-%m-%d %H:%M:%S} — pulling latest complaints ...")
    raw = ingest.fetch_amex()
    df = clean.clean(raw)

    # Reuse cached VADER scores for complaints we've already processed.
    n_new = len(df)
    if config.AMEX_ENRICHED.exists() and not retrain:
        prev = pd.read_parquet(config.AMEX_ENRICHED)
        cached = prev[["complaint_id", *[c for c in _SENT_COLS if c in prev.columns]]] \
            .drop_duplicates("complaint_id")
        df = df.merge(cached, on="complaint_id", how="left")
        new_mask = df["sent_compound"].isna()
        n_new = int(new_mask.sum())
        print(f"[refresh] {n_new:,} new complaints since last run "
              f"({len(df) - n_new:,} reused from cache).")
        if n_new:
            scored_new = sentiment.enrich(df.loc[new_mask].copy())
            for c in _SENT_COLS:
                df.loc[new_mask, c] = scored_new[c].values
    else:
        df = sentiment.enrich(df)

    # Guarantee sentiment dtypes are numeric where models expect it.
    for c in ("sent_neg", "sent_neu", "sent_pos", "sent_compound"):
        df[c] = pd.to_numeric(df[c], errors="coerce").astype("float32")
    df["is_negative"] = pd.to_numeric(df["is_negative"], errors="coerce").fillna(0).astype("int8")

    # Train models if missing or requested; otherwise score with the saved ones.
    if retrain or not escalation_model.MODEL_PATH.exists() or not churn_model.MODEL_PATH.exists():
        print("[refresh] Training models ...")
        esc = escalation_model.train(df)
        df["churn_risk_label"] = churn_model.build_proxy_label(df)
        churn_model.train(df)
    else:
        esc = None
        df["churn_risk_label"] = churn_model.build_proxy_label(df)

    df["escalation_score"] = escalation_model.score(df, esc)
    df["escalation_flag"] = (df["escalation_score"] >= 0.5).astype("int8")
    df["churn_risk_score"] = churn_model.score(df)
    df["churn_high_risk"] = (df["churn_risk_score"] >= config.CHURN_HIGH_RISK_CUTOFF).astype("int8")

    scored = df[KEEP].copy()
    scored.to_parquet(config.AMEX_ENRICHED, index=False)
    scored.to_parquet(config.AMEX_SCORED, index=False)

    terms = escalation_model.top_terms(esc or escalation_model.joblib.load(escalation_model.MODEL_PATH))
    dashboard_data.build(scored, terms)

    payload = _write_version(len(scored), n_new, retrain)
    print(f"[refresh] Done. {len(scored):,} complaints ({n_new:,} new). "
          f"Stamp: {payload['updated_at']}")
    return payload


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Agentic dashboard refresh")
    ap.add_argument("--retrain", action="store_true", help="Retrain models this run")
    args = ap.parse_args(argv)
    print(json.dumps(refresh(retrain=args.retrain), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
