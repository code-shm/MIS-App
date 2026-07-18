"""Industry-wide MIS layer — aggregates the full 6M+ CFPB export.

Streams the bulk file in chunks (constant memory) and accumulates two MIS
tables an Amex reporting analyst would live in:

  * ``mis_industry_monthly``   — monthly complaint volume, timely-response rate
    and relief rate across the whole industry, with the Amex slice broken out
    so the card can be benchmarked against the market.
  * ``mis_company_benchmark``  — a company league table (volume, timely %,
    relief %, narrative %) used to rank Amex against peer issuers.

This is the step that substantiates "processed 6M+ complaints": every row of the
national database passes through the accumulator, not just the Amex subset.
"""
from __future__ import annotations

import time

import numpy as np
import pandas as pd

from . import config, ingest

_RELIEF = {"Closed with monetary relief", "Closed with non-monetary relief"}


def _agg_chunk(chunk: pd.DataFrame, is_amex_target: str):
    chunk = chunk.copy()
    chunk["year_month"] = chunk["date_received"].dt.to_period("M").astype("string")
    chunk["timely_yes"] = chunk["timely"].str.strip().str.lower().eq("yes")
    chunk["relief"] = chunk["company_response"].isin(_RELIEF)
    chunk["has_narr"] = chunk["complaint_what_happened"].fillna("").str.len() > 0
    chunk["is_amex"] = chunk["company"].fillna("").str.upper().eq(is_amex_target)
    return chunk


def build_mis(chunksize: int = 250_000, progress_every: int = 1) -> dict:
    """Single streaming pass over the full export -> MIS parquet tables."""
    target = config.TARGET_COMPANY.upper()
    t0 = time.time()
    total = 0

    # Monthly accumulators keyed by (year_month, segment) where segment in
    # {"Industry", "Amex"}.
    monthly = {}          # key -> dict of running sums
    company = {}          # company -> running sums (league table)

    print("[mis] Streaming full CFPB export (6M+ rows) ...")
    for i, chunk in enumerate(ingest.load_bulk_iter(chunksize=chunksize), start=1):
        c = _agg_chunk(chunk, target)
        total += len(c)

        for seg, mask in (("Industry", slice(None)), ("Amex", c["is_amex"])):
            sub = c.loc[mask] if not isinstance(mask, slice) else c
            if not len(sub):
                continue
            g = sub.groupby("year_month", dropna=True).agg(
                complaints=("timely_yes", "size"),
                timely=("timely_yes", "sum"),
                relief=("relief", "sum"),
                narrative=("has_narr", "sum"),
            )
            for ym, row in g.iterrows():
                if ym is pd.NA or ym is None:
                    continue
                k = (str(ym), seg)
                acc = monthly.setdefault(k, dict(complaints=0, timely=0, relief=0, narrative=0))
                acc["complaints"] += int(row["complaints"])
                acc["timely"] += int(row["timely"])
                acc["relief"] += int(row["relief"])
                acc["narrative"] += int(row["narrative"])

        gc = c.groupby(c["company"].fillna("Unknown")).agg(
            complaints=("timely_yes", "size"),
            timely=("timely_yes", "sum"),
            relief=("relief", "sum"),
            narrative=("has_narr", "sum"),
        )
        for comp, row in gc.iterrows():
            acc = company.setdefault(comp, dict(complaints=0, timely=0, relief=0, narrative=0))
            acc["complaints"] += int(row["complaints"])
            acc["timely"] += int(row["timely"])
            acc["relief"] += int(row["relief"])
            acc["narrative"] += int(row["narrative"])

        if i % progress_every == 0:
            print(f"[mis]   chunk {i}: {total:,} rows @ {total/(time.time()-t0):,.0f} rows/s")

    # ---- Monthly table ----
    m = pd.DataFrame([
        dict(year_month=k[0], segment=k[1], **v) for k, v in monthly.items()
    ])
    m = m[m["year_month"].str.match(r"\d{4}-\d{2}")].copy()
    m["timely_rate"] = (m["timely"] / m["complaints"]).round(4)
    m["relief_rate"] = (m["relief"] / m["complaints"]).round(4)
    m["narrative_rate"] = (m["narrative"] / m["complaints"]).round(4)
    m = m.sort_values(["year_month", "segment"]).reset_index(drop=True)
    m.to_parquet(config.MIS_INDUSTRY, index=False)

    # ---- Company league table ----
    comp = pd.DataFrame([
        dict(company=k, **v) for k, v in company.items()
    ])
    comp["timely_rate"] = (comp["timely"] / comp["complaints"]).round(4)
    comp["relief_rate"] = (comp["relief"] / comp["complaints"]).round(4)
    comp["narrative_rate"] = (comp["narrative"] / comp["complaints"]).round(4)
    comp = comp.sort_values("complaints", ascending=False).reset_index(drop=True)
    comp["rank"] = np.arange(1, len(comp) + 1)
    comp["is_amex"] = comp["company"].str.upper().eq(target)
    # Persist the full table but the dashboard reads the top 60 + Amex.
    comp.to_parquet(config.MIS_COMPANY, index=False)

    elapsed = time.time() - t0
    summary = {
        "total_rows_processed": int(total),
        "distinct_companies": int(len(comp)),
        "months": int(m["year_month"].nunique()),
        "amex_rank": int(comp.loc[comp["is_amex"], "rank"].iloc[0]) if comp["is_amex"].any() else None,
        "elapsed_sec": round(elapsed, 1),
    }
    print(f"[mis] Done: {total:,} rows in {elapsed:,.0f}s | "
          f"{summary['distinct_companies']:,} companies | Amex rank {summary['amex_rank']}")
    return summary


if __name__ == "__main__":
    import json
    print(json.dumps(build_mis(), indent=2))
