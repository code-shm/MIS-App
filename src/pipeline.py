"""End-to-end orchestration.

    raw Amex complaints
        -> clean / label
        -> VADER sentiment enrichment
        -> escalation classifier          (train + score)
        -> churn-risk model                (train + score)
        -> scored analytics table          (data/outputs/amex_scored.parquet)
        -> dashboard data extract          (dashboards/html/data.json)

The industry MIS layer (6M+ rows) runs separately via ``src.mis_aggregate`` and
feeds the same dashboard. Run:

    python -m src.pipeline                 # full run, refetch if raw missing
    python -m src.pipeline --no-refetch    # use cached raw parquet
"""
from __future__ import annotations

import argparse
import json

import pandas as pd

from . import (churn_model, clean, config, escalation_model, features,
               ingest, sentiment)

# Columns persisted to the scored analytics table (shared with src.refresh).
KEEP = [
    "complaint_id", "date_received", "year", "month", "year_month", "quarter",
    "product", "sub_product", "issue", "sub_issue", "state", "submitted_via",
    "company_response", "timely", "handling_days", "narrative", "narrative_length",
    "has_narrative", "sent_neg", "sent_neu", "sent_pos", "sent_compound",
    "sentiment_label", "sentiment_band", "is_negative", "is_escalated",
    "escalation_score", "escalation_flag", "churn_risk_label",
    "churn_risk_score", "churn_high_risk", "relief_flag", "timely_flag",
]


def run(refetch: bool = True, from_enriched: bool = False) -> pd.DataFrame:
    if from_enriched and config.AMEX_ENRICHED.exists():
        # Fast path: reuse the cached clean+sentiment frame, retrain models only.
        df = pd.read_parquet(config.AMEX_ENRICHED)
        print(f"[pipeline] Loaded cached enriched frame: {len(df):,} rows "
              "(skipping ingest/clean/VADER)")
    else:
        # 1. Ingest --------------------------------------------------------
        if refetch or not config.AMEX_RAW.exists():
            raw = ingest.fetch_amex()
        else:
            raw = pd.read_parquet(config.AMEX_RAW)
            print(f"[pipeline] Loaded cached raw: {len(raw):,} rows")

        # 2. Clean + label -------------------------------------------------
        df = clean.clean(raw)

        # 3. Sentiment enrichment (VADER) ----------------------------------
        df = sentiment.enrich(df)

    # 4. Escalation model --------------------------------------------------
    esc = escalation_model.train(df)
    df["escalation_score"] = escalation_model.score(df, esc)
    df["escalation_flag"] = (df["escalation_score"] >= 0.5).astype("int8")

    # 5. Churn-risk model --------------------------------------------------
    df["churn_risk_label"] = churn_model.build_proxy_label(df)
    chn = churn_model.train(df)
    df["churn_risk_score"] = churn_model.score(df, chn)
    df["churn_high_risk"] = (df["churn_risk_score"] >= config.CHURN_HIGH_RISK_CUTOFF).astype("int8")

    # 6. Persist enriched + scored tables ---------------------------------
    scored = df[KEEP].copy()
    scored.to_parquet(config.AMEX_ENRICHED, index=False)
    scored.to_parquet(config.AMEX_SCORED, index=False)
    print(f"[pipeline] Wrote scored table -> {config.AMEX_SCORED.relative_to(config.ROOT)}")

    # 7. Interpretability snapshot ----------------------------------------
    terms = escalation_model.top_terms(esc, k=15)
    print("[pipeline] Top escalation-driving terms: "
          + ", ".join(t for t, _ in terms[:10]))

    # 8. Dashboard extract -------------------------------------------------
    from . import dashboard_data  # local import to avoid cycle at import time
    dashboard_data.build(scored, terms)

    return scored


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Amex complaints pipeline")
    ap.add_argument("--no-refetch", action="store_true", help="Use cached raw parquet")
    ap.add_argument("--from-enriched", action="store_true",
                    help="Reuse cached clean+VADER frame; retrain models only")
    args = ap.parse_args(argv)
    scored = run(refetch=not args.no_refetch, from_enriched=args.from_enriched)
    print("\n[pipeline] Summary:")
    print(json.dumps({
        "rows": int(len(scored)),
        "escalation_rate": round(float(scored["is_escalated"].mean()), 4),
        "pred_escalation_flag_rate": round(float(scored["escalation_flag"].mean()), 4),
        "negative_sentiment_share": round(float(scored["is_negative"].mean()), 4),
        "high_churn_risk_share": round(float(scored["churn_high_risk"].mean()), 4),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
