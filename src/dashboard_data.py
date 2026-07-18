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


def _robust_z(values: list[float]):
    """Median/MAD robust z-scores (falls back to std when MAD collapses)."""
    a = np.asarray(values, dtype=float)
    med = float(np.median(a))
    mad = float(np.median(np.abs(a - med)))
    if mad > 1e-9:
        z = 0.6745 * (a - med) / mad
    else:
        sd = float(a.std()) or 1.0
        z = (a - med) / sd
    return med, z


def _trailing_z(values: list[float], window: int = 12, min_hist: int = 6):
    """Z-score of each point vs its trailing window (for trending series like
    volume, where an all-time baseline would flag the whole recent era)."""
    a = np.asarray(values, dtype=float)
    z = np.zeros(len(a))
    med_at = a.copy()
    for i in range(len(a)):
        hist = a[max(0, i - window):i]
        if len(hist) >= min_hist:
            med = float(np.median(hist))
            mad = float(np.median(np.abs(hist - med)))
            s = 1.4826 * mad if mad > 1e-9 else (float(hist.std()) or 1.0)
            z[i] = (a[i] - med) / s
            med_at[i] = med
    return z, med_at


def _sev(absz: float) -> str:
    return "critical" if absz >= 4.5 else "serious" if absz >= 3.5 else "warning"


def build_alerts(df: pd.DataFrame, monthly: list[dict], min_n: int = 30) -> dict:
    """Auto-detect anomalies an ops lead would want surfaced first.

    Three lenses: (1) the latest month vs its trailing baseline, (2) the biggest
    historical spikes across the series, (3) product/issue risk hotspots.
    """
    metrics = [
        ("complaints", "Complaint volume", "count", True),
        ("escalation_rate", "Escalation rate", "rate", True),
        ("negative_rate", "Negative sentiment", "rate", True),
        ("churn_risk", "Churn-risk share", "rate", True),
    ]
    qual = [m for m in monthly if m["complaints"] >= min_n]
    attention, anomalies = [], []
    rate_series = {}
    timeline = {"metric": None, "points": []}
    counts = {"critical": 0, "serious": 0, "warning": 0}
    as_of_ym = None

    if len(qual) >= 8:
        yms = [m["ym"] for m in qual]
        # The final month is often the current, incomplete one — compare it to
        # the median of the trailing 6 months (recent volumes dwarf the early
        # years) and step back to the last COMPLETE month if it's partial.
        prior = [m["complaints"] for m in qual[-7:-1]]
        med_vol = float(np.median(prior)) if prior else 0.0
        cur_idx = len(qual) - 1
        if med_vol and qual[cur_idx]["complaints"] < 0.5 * med_vol:
            cur_idx -= 1
        cur_ym = qual[cur_idx]["ym"]
        as_of_ym = cur_ym
        for key, label, kind, higher_is_bad in metrics:
            vals = [m[key] for m in qual]
            # Volume trends secularly -> trailing baseline; rates are ~stationary
            # -> global robust baseline.
            if key == "complaints":
                z, med_arr = _trailing_z(vals)
                med = float(med_arr[cur_idx])
            else:
                med, z = _robust_z(vals)
            # (1) last-complete-month status
            zl = float(z[cur_idx]); v = vals[cur_idx]
            direction = "above" if v >= med else "below"
            bad = (direction == "above") == higher_is_bad
            fmt = (lambda x: f"{x:,.0f}") if kind == "count" else (lambda x: f"{x*100:.1f}%")
            # Negative-sentiment depends on CFPB narrative publication, which lags
            # for recent months — omit it from the current-month lens (it stays in
            # the historical-anomaly scan where coverage is complete).
            if abs(zl) >= 2.0 and key != "negative_rate":
                sev = _sev(abs(zl)) if bad else "good"
                if sev in counts:
                    counts[sev] += 1
                attention.append({
                    "severity": sev, "metric": label, "ym": cur_ym,
                    "value": round(v, 4), "baseline": round(med, 4), "z": round(zl, 2),
                    "direction": direction,
                    "detail": (f"{label} was {fmt(v)} in {cur_ym}, {abs(zl):.1f}σ "
                               f"{direction} the {fmt(med)} baseline."),
                })
            # (2) historical anomalies — upward spikes (z already uses the right
            # baseline per metric: trailing for volume, global for rates).
            for m, zz in zip(qual, z):
                spike_bad = (zz >= 0) == higher_is_bad
                if abs(zz) >= 3.5 and spike_bad and m["ym"] != cur_ym:
                    anomalies.append({
                        "severity": _sev(abs(zz)), "metric": label, "ym": m["ym"],
                        "value": round(m[key], 4), "z": round(float(zz), 2),
                        "detail": f"{label} hit {fmt(m[key])} in {m['ym']} ({abs(zz):.1f}σ).",
                    })
            # (3) collect rate-metric series for the headline timeline
            if kind == "rate":
                rate_series[key] = (label, [
                    {"ym": m["ym"], "value": round(m[key], 4),
                     "z": round(float(zz), 2), "flag": bool(abs(zz) >= 3.5)}
                    for m, zz in zip(qual, z)])

        # Skip the 2011-2014 ramp-up era (thin trailing baselines) and cap each
        # metric to keep the list diverse rather than all-volume.
        anomalies = [a for a in anomalies if a["ym"] >= "2015-01"]
        per_metric, capped = {}, []
        for a in sorted(anomalies, key=lambda a: -abs(a["z"])):
            per_metric.setdefault(a["metric"], 0)
            if per_metric[a["metric"]] < 3:
                capped.append(a); per_metric[a["metric"]] += 1
        anomalies = sorted(capped, key=lambda a: -abs(a["z"]))[:8]

        # Headline timeline = the rate metric with the most anomalies (so the
        # marked spikes are visible); default to escalation rate.
        from collections import Counter
        acnt = Counter(a["metric"] for a in anomalies)
        pref = {"Escalation rate": 2, "Churn-risk share": 1, "Negative sentiment": 0}
        if rate_series:
            best = max(rate_series, key=lambda k: (acnt.get(rate_series[k][0], 0),
                                                   pref.get(rate_series[k][0], -1)))
            timeline = {"metric": rate_series[best][0], "points": rate_series[best][1]}

    # (3) segment hotspots — products/issues with risk far above the Amex mean.
    hotspots = []
    esc_base = float(df["is_escalated"].mean())
    chn_base = float(df["churn_high_risk"].mean())
    for kind, col in (("product", "product"), ("issue", "issue")):
        g = df.groupby(col).agg(n=("complaint_id", "size"),
                                esc=("is_escalated", "mean"),
                                chn=("churn_high_risk", "mean"))
        g = g[g["n"] >= 150]
        for name, r in g.iterrows():
            for mname, rate, base in (("escalation", r["esc"], esc_base),
                                      ("churn-risk", r["chn"], chn_base)):
                lift = rate / base if base else 1
                if lift >= 1.4 and rate >= 0.15:
                    sev = "critical" if lift >= 2.0 else "serious" if lift >= 1.7 else "warning"
                    hotspots.append({
                        "severity": sev, "kind": kind, "name": str(name), "metric": mname,
                        "rate": round(float(rate), 4), "baseline": round(base, 4),
                        "lift": round(float(lift), 2), "n": int(r["n"]),
                        "detail": (f"{str(name)[:44]} — {mname} {rate*100:.0f}% "
                                   f"({lift:.1f}× the {base*100:.0f}% Amex average, n={int(r['n']):,})."),
                    })
    hotspots.sort(key=lambda h: -h["lift"])
    hotspots = hotspots[:8]
    for h in hotspots:
        if h["severity"] in counts:
            counts[h["severity"]] += 1

    return {
        "as_of": as_of_ym,
        "counts": counts,
        "attention": attention,
        "anomalies": anomalies,
        "hotspots": hotspots,
        "timeline": timeline,
    }


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
        "alerts": build_alerts(df, monthly),
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
