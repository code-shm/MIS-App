"""Generate a branded executive PDF report from the dashboard extract.

Reads ``dashboards/html/data.json`` (so the PDF always matches the dashboard)
and renders a multi-page PDF with the KPI summary, trends, breakdowns, model
report cards and the industry benchmark. Uses only matplotlib — no extra deps.

    python -m src.report                     # -> reports/amex_executive_report.pdf
    python -m src.report --out somewhere.pdf
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages

from . import config

DATA = config.ROOT / "dashboards" / "html" / "data.json"
DEFAULT_OUT = config.FIGURES_DIR.parent / "amex_executive_report.pdf"

# Palette (matches the dashboard / dataviz reference)
BRAND = "#006FCF"
INK = "#0b0b0b"
INK2 = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
SERIES = ["#2a78d6", "#008300", "#e87ba4", "#eda100", "#1baf7a", "#eb6834", "#4a3aa7", "#e34948"]
SERIOUS = "#ec835a"
CRIT = "#d03b3b"

plt.rcParams.update({
    "font.family": "DejaVu Sans",
    "font.size": 9,
    "axes.edgecolor": GRID,
    "axes.linewidth": 0.8,
    "axes.grid": True,
    "grid.color": GRID,
    "grid.linewidth": 0.6,
    "text.color": INK,
    "axes.labelcolor": INK2,
    "xtick.color": MUTED,
    "ytick.color": MUTED,
    "figure.dpi": 150,
})


def _pct(x):
    return f"{x*100:.1f}%"


def _int(x):
    return f"{int(x):,}"


def _header(fig, title, sub):
    fig.text(0.06, 0.955, "AX", fontsize=15, fontweight="bold", color="white",
             bbox=dict(boxstyle="round,pad=0.35", fc=BRAND, ec="none"))
    fig.text(0.115, 0.965, title, fontsize=15, fontweight="bold", color=INK, va="center")
    fig.text(0.115, 0.945, sub, fontsize=8.5, color=INK2, va="center")
    fig.add_artist(plt.Line2D([0.06, 0.94], [0.925, 0.925], color=GRID, lw=1,
                              transform=fig.transFigure))


def _footer(fig, page, total):
    fig.text(0.06, 0.03, "Source: CFPB Consumer Complaint Database (public). "
             "Independent analytics — not affiliated with American Express.",
             fontsize=6.5, color=MUTED)
    fig.text(0.94, 0.03, f"{page} / {total}", fontsize=7, color=MUTED, ha="right")


def _hbar(ax, labels, values, color, valfmt, title):
    y = range(len(labels))
    ax.barh(list(y), values, color=color, height=0.62, zorder=3)
    ax.set_yticks(list(y))
    ax.set_yticklabels([l[:26] for l in labels], fontsize=7.5)
    ax.invert_yaxis()
    ax.grid(axis="y", visible=False)
    vmax = max(values) if values else 1
    for i, v in enumerate(values):
        ax.text(v + vmax * 0.01, i, valfmt(v), va="center", fontsize=7, color=INK)
    ax.set_xlim(0, vmax * 1.16)
    ax.set_title(title, fontsize=9.5, fontweight="bold", color=INK, loc="left", pad=6)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)


def build(out: Path = DEFAULT_OUT) -> Path:
    if not DATA.exists():
        raise FileNotFoundError(f"{DATA} missing — run the pipeline first.")
    d = json.loads(DATA.read_text())
    k, ind, models = d["kpis"], d.get("industry", {}), d.get("models", {})
    stamp = dt.datetime.now().strftime("%d %b %Y %H:%M")
    TOTAL = 3

    with PdfPages(out) as pdf:
        # ---- Page 1: executive summary + trends --------------------------
        fig = plt.figure(figsize=(8.27, 11.69))  # A4 portrait
        _header(fig, "American Express — Complaints Analytics & MIS",
                f"Executive report · generated {stamp}")

        kpi_items = [
            ("Total complaints", _int(k["total_complaints"])),
            ("Escalation rate", _pct(k["escalation_rate"])),
            ("Negative sentiment", _pct(k["negative_sentiment_rate"])),
            ("High churn-risk", _pct(k["high_churn_risk_rate"])),
            ("Avg handling", f"{k['avg_handling_days']:.1f} d"),
            ("Coverage", f"{k['date_min']} → {k['date_max']}"),
        ]
        for i, (lab, val) in enumerate(kpi_items):
            x = 0.06 + (i % 3) * 0.30
            yb = 0.845 - (i // 3) * 0.075
            fig.text(x, yb + 0.028, val, fontsize=15, fontweight="bold", color=BRAND)
            fig.text(x, yb + 0.006, lab.upper(), fontsize=7, color=MUTED)

        m = [x for x in d["monthly"] if x["ym"] >= "2015-01"]
        xs = [x["ym"] for x in m]
        idx = range(len(xs))

        ax1 = fig.add_axes([0.09, 0.50, 0.85, 0.16])
        ax1.plot(list(idx), [x["complaints"] for x in m], color=SERIES[0], lw=1.6)
        ax1.fill_between(list(idx), [x["complaints"] for x in m], color=SERIES[0], alpha=0.08)
        ax1.set_title("Monthly complaint volume", fontsize=9.5, fontweight="bold",
                      color=INK, loc="left", pad=6)
        _sparse_x(ax1, xs)
        for s in ("top", "right"):
            ax1.spines[s].set_visible(False)

        ax2 = fig.add_axes([0.09, 0.28, 0.85, 0.16])
        ax2.plot(list(idx), [x["escalation_rate"] for x in m], color=SERIES[5], lw=1.4, label="Escalation")
        ax2.plot(list(idx), [x["negative_rate"] for x in m], color=SERIES[7], lw=1.4, label="Negative sentiment")
        ax2.plot(list(idx), [x["churn_risk"] for x in m], color=SERIES[6], lw=1.4, label="Churn-risk")
        ax2.set_title("Risk & sentiment rates over time", fontsize=9.5, fontweight="bold",
                      color=INK, loc="left", pad=6)
        ax2.legend(loc="upper right", fontsize=7, frameon=False, ncol=3)
        ax2.yaxis.set_major_formatter(lambda v, _: f"{v*100:.0f}%")
        _sparse_x(ax2, xs)
        for s in ("top", "right"):
            ax2.spines[s].set_visible(False)

        fig.text(0.06, 0.235, "Industry context", fontsize=9.5, fontweight="bold", color=INK)
        ctx = (f"Amex ranks #{ind.get('amex_rank','—')} of {_int(ind.get('distinct_companies',0))} "
               f"companies across {_int(ind.get('total_rows_processed',0))} complaints in the national "
               f"CFPB dataset. Amex timely-response rate {_pct(ind.get('amex_timely_rate',0))}, "
               f"relief rate {_pct(ind.get('amex_relief_rate',0))}.")
        fig.text(0.06, 0.17, ctx, fontsize=8.5, color=INK2, wrap=True,
                 bbox=dict(boxstyle="round,pad=0.6", fc="#f4f8fd", ec=GRID))
        _footer(fig, 1, TOTAL)
        pdf.savefig(fig); plt.close(fig)

        # ---- Page 2: breakdowns ------------------------------------------
        fig = plt.figure(figsize=(8.27, 11.69))
        _header(fig, "Complaint breakdowns", "Where complaints concentrate")
        b = d["breakdowns"]
        specs = [
            ([0.09, 0.66, 0.38, 0.20], b["product"][:7], SERIES[0], _int, "By product"),
            ([0.57, 0.66, 0.38, 0.20], b["issue"][:8], SERIES[4], _int, "By issue"),
            ([0.09, 0.38, 0.38, 0.20], b["state"][:8], SERIES[1], _int, "By state"),
            ([0.57, 0.38, 0.38, 0.20], b["sentiment_band"], SERIES[6], _int, "By sentiment band"),
            ([0.09, 0.10, 0.38, 0.20], d["risk"]["escalation_by_issue"][:8], SERIOUS, _pct, "Escalation rate by issue"),
            ([0.57, 0.10, 0.38, 0.20], d["risk"]["churn_by_issue"][:8], CRIT, _pct, "Churn-risk share by issue"),
        ]
        for rect, rows, color, fmt, title in specs:
            ax = fig.add_axes(rect)
            if rows and "rate" in rows[0]:
                _hbar(ax, [r["label"] for r in rows], [r["rate"] for r in rows], color, fmt, title)
            else:
                _hbar(ax, [r["label"] for r in rows], [r["value"] for r in rows], color, fmt, title)
        _footer(fig, 2, TOTAL)
        pdf.savefig(fig); plt.close(fig)

        # ---- Page 3: models + benchmark ----------------------------------
        fig = plt.figure(figsize=(8.27, 11.69))
        _header(fig, "Predictive models & industry benchmark",
                "Held-out performance and peer comparison")

        y = 0.86
        for name, label in (("escalation", "Escalation classifier (Logistic Regression + TF-IDF)"),
                            ("churn", "Churn-risk model (Gradient-Boosted Trees)")):
            mm = models.get(name)
            fig.text(0.06, y, label, fontsize=10, fontweight="bold", color=INK)
            if mm:
                fig.text(0.06, y - 0.028,
                         f"ROC-AUC  {mm['roc_auc']:.3f}      PR-AUC  {mm['pr_auc']:.3f}      "
                         f"train {_int(mm['n_train'])} / test {_int(mm['n_test'])}",
                         fontsize=9, color=INK2)
            y -= 0.075

        terms = models.get("top_escalation_terms", [])
        if terms:
            fig.text(0.06, y, "Top escalation-driving terms", fontsize=10, fontweight="bold", color=INK)
            fig.text(0.06, y - 0.03, "  ·  ".join(t["term"] for t in terms[:12]),
                     fontsize=8.5, color=INK2, wrap=True)
            y -= 0.07

        # Benchmark table (top companies, Amex highlighted)
        comp = ind.get("top_companies", [])[:12]
        ax = fig.add_axes([0.06, 0.10, 0.88, max(0.05, 0.03 * (len(comp) + 1))])
        ax.axis("off")
        if comp:
            cells = [[c["company"][:34], _int(c["complaints"]), _pct(c["timely_rate"]), _pct(c["relief_rate"])]
                     for c in comp]
            tbl = ax.table(cellText=cells,
                           colLabels=["Company", "Complaints", "Timely %", "Relief %"],
                           colWidths=[0.5, 0.2, 0.15, 0.15], loc="upper center", cellLoc="left")
            tbl.auto_set_font_size(False); tbl.set_fontsize(7.8); tbl.scale(1, 1.35)
            for (r, cc), cell in tbl.get_celld().items():
                cell.set_edgecolor(GRID)
                if r == 0:
                    cell.set_facecolor(BRAND); cell.set_text_props(color="white", fontweight="bold")
                elif comp[r - 1].get("is_amex"):
                    cell.set_facecolor("#e3f0fb"); cell.set_text_props(fontweight="bold")
        fig.text(0.06, 0.115 + 0.03 * (len(comp) + 1),
                 "Company league table — national CFPB dataset", fontsize=10,
                 fontweight="bold", color=INK)
        _footer(fig, 3, TOTAL)
        pdf.savefig(fig); plt.close(fig)

        info = pdf.infodict()
        info["Title"] = "Amex Complaints Analytics & MIS — Executive Report"
        info["Author"] = "Amex Complaints Insights Platform"

    print(f"[report] Wrote {out} ({out.stat().st_size/1024:,.0f} KB)")
    return out


def _sparse_x(ax, xs):
    n = len(xs)
    step = max(1, n // 8)
    ticks = list(range(0, n, step))
    ax.set_xticks(ticks)
    ax.set_xticklabels([xs[i] for i in ticks], fontsize=6.8, rotation=0)
    ax.set_xlim(-0.5, n - 0.5)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Generate the executive PDF report")
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    args = ap.parse_args(argv)
    build(Path(args.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
