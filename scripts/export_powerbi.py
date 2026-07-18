"""Export analytics tables as Power BI-friendly CSVs.

Power BI Desktop imports CSV natively (Parquet needs a connector), so this
writes the star-schema fact + the MIS tables to dashboards/powerbi/data/ ready
for Get Data > Text/CSV. Dates are ISO-formatted for clean type inference.
"""
from __future__ import annotations

import sys

import pandas as pd

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))
from src import config  # noqa: E402

OUT = config.ROOT / "dashboards" / "powerbi" / "data"
OUT.mkdir(parents=True, exist_ok=True)


def _write(df: pd.DataFrame, name: str) -> None:
    path = OUT / f"{name}.csv"
    df.to_csv(path, index=False, date_format="%Y-%m-%d")
    print(f"  {name}.csv  ({len(df):,} rows, {path.stat().st_size/1024:,.0f} KB)")


def main() -> int:
    print("[powerbi] Exporting CSVs ->", OUT.relative_to(config.ROOT))

    if config.AMEX_SCORED.exists():
        fact = pd.read_parquet(config.AMEX_SCORED)
        # Drop the long narrative from the BI fact (keep it lean; text lives in
        # the analytical parquet). Keep a length + sentiment summary instead.
        fact = fact.drop(columns=[c for c in ("narrative",) if c in fact.columns])
        _write(fact, "fact_complaints")

        # A tiny date dimension for a proper star schema in Power BI.
        dates = pd.DataFrame({"date": pd.to_datetime(fact["date_received"]).dt.normalize().unique()})
        dates = dates.dropna().sort_values("date")
        dates["year"] = dates["date"].dt.year
        dates["quarter"] = dates["date"].dt.quarter
        dates["month"] = dates["date"].dt.month
        dates["month_name"] = dates["date"].dt.strftime("%b")
        dates["year_month"] = dates["date"].dt.strftime("%Y-%m")
        _write(dates, "dim_date")

    if config.MIS_INDUSTRY.exists():
        _write(pd.read_parquet(config.MIS_INDUSTRY), "mis_industry_monthly")
    if config.MIS_COMPANY.exists():
        comp = pd.read_parquet(config.MIS_COMPANY)
        _write(comp.head(200), "mis_company_benchmark_top200")

    print("[powerbi] Done. In Power BI Desktop: Get Data > Text/CSV > select these files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
