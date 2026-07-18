"""Compile the self-contained dashboard data extract.

Rolls the row-level scored table (and the industry MIS tables, when present)
up into a compact ``dashboards/html/data.json`` that the static dashboard reads
with a single fetch. Keeping the aggregation in Python — not in the browser —
means the dashboard stays fast and the numbers match the Parquet/BigQuery
tables exactly.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from . import config


def _vc(series: pd.Series, top: int | None = None) -> list[dict]:
    vc = series.value_counts(dropna=False)
    if top:
        vc = vc.head(top)
    return [{"label": str(k), "value": int(v)} for k, v in vc.items()]


def _rate_by(df: pd.DataFrame, by: str, col: str, top: int = 10) -> list[dict]:
    g = df.groupby(by).agg(n=(col, "size"), rate=(col, "mean"))
    g = g[g["n"] >= 50].sort_values("rate", ascending=False).head(top)
    return [{"label": str(i), "n": int(r["n"]), "rate": round(float(r["rate"]), 4)}
            for i, r in g.iterrows()]


def build(scored: pd.DataFrame, top_terms: list[tuple[str, float]] | None = None) -> dict:
    df = scored.copy()
    df = df[df["year"].notna()]

    # -- Headline KPIs ----------------------------------------------------
    kpis = {
        "total_complaints": int(len(df)),
        "with_narrative": int(df["has_narrative"].sum()),
        "escalation_rate": round(float(df["is_escalated"].mean()), 4),
        "negative_sentiment_rate": round(float(df["is_negative"].mean()), 4),
        "high_churn_risk_rate": round(float(df["churn_high_risk"].mean()), 4),
        "avg_handling_days": round(float(df["handling_days"].mean(skipna=True)), 2),
        "date_min": str(df["date_received"].min().date()),
        "date_max": str(df["date_received"].max().date()),
    }

    # -- Monthly trend (Amex) --------------------------------------------
    m = (df.groupby("year_month")
           .agg(complaints=("complaint_id", "size"),
                escalation_rate=("is_escalated", "mean"),
                negative_rate=("is_negative", "mean"),
                churn_risk=("churn_high_risk", "mean"),
                avg_sentiment=("sent_compound", "mean"))
           .reset_index())
    m = m[m["year_month"].astype(str).str.match(r"\d{4}-\d{2}")].sort_values("year_month")
    monthly = [{
        "ym": r["year_month"],
        "complaints": int(r["complaints"]),
        "escalation_rate": round(float(r["escalation_rate"]), 4),
        "negative_rate": round(float(r["negative_rate"]), 4),
        "churn_risk": round(float(r["churn_risk"]), 4),
        "avg_sentiment": round(float(r["avg_sentiment"]), 4),
    } for _, r in m.iterrows()]

    # -- Breakdowns -------------------------------------------------------
    breakdowns = {
        "product": _vc(df["product"], top=8),
        "issue": _vc(df["issue"], top=10),
        "state": _vc(df["state"], top=12),
        "channel": _vc(df["submitted_via"]),
        "company_response": _vc(df["company_response"]),
        "sentiment_band": _vc(df["sentiment_band"]),
    }

    # -- Risk lenses ------------------------------------------------------
    risk = {
        "escalation_by_issue": _rate_by(df, "issue", "is_escalated", top=10),
        "escalation_by_product": _rate_by(df, "product", "is_escalated", top=8),
        "churn_by_issue": _rate_by(df, "issue", "churn_high_risk", top=10),
        "sentiment_by_product": [
            {"label": str(i), "avg_sentiment": round(float(v), 4)}
            for i, v in df.groupby("product")["sent_compound"].mean()
                          .sort_values().head(8).items()
        ],
    }

    # -- Model report cards ----------------------------------------------
    models = {}
    for name in ("escalation", "churn"):
        p = config.MODELS_DIR / f"{name}_metrics.json"
        if p.exists():
            mm = json.loads(p.read_text())
            models[name] = {
                "roc_auc": mm["roc_auc"], "pr_auc": mm["pr_auc"],
                "n_train": mm["n_train"], "n_test": mm["n_test"],
            }
    if top_terms:
        models["top_escalation_terms"] = [
            {"term": t, "weight": round(w, 3)} for t, w in top_terms[:15]]

    # -- Industry MIS layer (6M+) ----------------------------------------
    industry = {}
    if config.MIS_COMPANY.exists():
        comp = pd.read_parquet(config.MIS_COMPANY)
        industry["total_rows_processed"] = int(comp["complaints"].sum())
        industry["distinct_companies"] = int(len(comp))
        amex_row = comp[comp["is_amex"]]
        if len(amex_row):
            r = amex_row.iloc[0]
            industry["amex_rank"] = int(r["rank"])
            industry["amex_timely_rate"] = round(float(r["timely_rate"]), 4)
            industry["amex_relief_rate"] = round(float(r["relief_rate"]), 4)
        top = comp.head(15)
        industry["top_companies"] = [{
            "company": str(r["company"])[:40],
            "complaints": int(r["complaints"]),
            "timely_rate": round(float(r["timely_rate"]), 4),
            "relief_rate": round(float(r["relief_rate"]), 4),
            "is_amex": bool(r["is_amex"]),
        } for _, r in top.iterrows()]
    if config.MIS_INDUSTRY.exists():
        mi = pd.read_parquet(config.MIS_INDUSTRY)
        mi = mi[mi["year_month"] >= "2019-01"]
        industry["monthly_benchmark"] = [{
            "ym": str(r["year_month"]), "segment": str(r["segment"]),
            "complaints": int(r["complaints"]),
            "timely_rate": round(float(r["timely_rate"]), 4),
            "relief_rate": round(float(r["relief_rate"]), 4),
        } for _, r in mi.iterrows()]

    # -- Complaint explorer slice (row-level, curated) --------------------
    # Ship a bounded set of real complaints with narratives so the explorer can
    # drill from aggregates to cases. Prioritise the highest-risk ones (that's
    # what an ops team triages) while keeping the payload small.
    exp = df[df["has_narrative"] == 1].copy()
    exp["_risk"] = exp[["escalation_score", "churn_risk_score"]].max(axis=1)
    exp = exp.sort_values("_risk", ascending=False).head(700)
    complaints = [{
        "id": int(r["complaint_id"]) if pd.notna(r["complaint_id"]) else None,
        "date": str(r["date_received"].date()) if pd.notna(r["date_received"]) else "",
        "product": str(r["product"]),
        "issue": str(r["issue"]),
        "state": str(r["state"]),
        "sentiment": str(r["sentiment_label"]),
        "compound": round(float(r["sent_compound"]), 3),
        "escalation": round(float(r["escalation_score"]), 3),
        "churn": round(float(r["churn_risk_score"]), 3),
        "escalated": int(r["is_escalated"]),
        "snippet": (str(r["narrative"])[:240] + ("…" if len(str(r["narrative"])) > 240 else "")),
    } for _, r in exp.iterrows()]

    payload = {
        "generated_from": "CFPB Consumer Complaint Database",
        "company": config.TARGET_COMPANY,
        "kpis": kpis,
        "monthly": monthly,
        "breakdowns": breakdowns,
        "risk": risk,
        "models": models,
        "industry": industry,
        "complaints": complaints,
    }

    blob = json.dumps(payload, indent=2, default=str)
    out = config.ROOT / "dashboards" / "html" / "data.json"
    out.write_text(blob)
    # Also emit a JS shim so the dashboard opens straight from disk (file://)
    # without needing a web server — browsers block fetch() over file://.
    js = config.ROOT / "dashboards" / "html" / "data.js"
    js.write_text("window.DASHBOARD_DATA = " + blob + ";\n")
    print(f"[dashboard] Wrote extract -> {out.relative_to(config.ROOT)} "
          f"({out.stat().st_size/1024:,.0f} KB) + data.js")
    return payload


if __name__ == "__main__":
    scored = pd.read_parquet(config.AMEX_SCORED)
    build(scored)
