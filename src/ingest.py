"""Ingestion layer.

Two entry points:

  * ``fetch_amex()``  — pulls every American Express complaint from the CFPB
    search API in a single scrolled request and writes a typed Parquet file.
    This is the working set for the NLP + predictive-modelling layers.

  * ``load_bulk_iter()`` — streams the full 6M+ CFPB bulk export in chunks so
    the MIS layer can aggregate the whole industry without ever holding the
    ~6 GB file in memory.

Run directly:  python -m src.ingest --amex          (fetch Amex subset)
               python -m src.ingest --check-bulk    (verify bulk download)
"""
from __future__ import annotations

import argparse
import json
import sys
import zipfile

import pandas as pd
import requests

from . import config


# ---------------------------------------------------------------------------
# American Express subset — CFPB search API
# ---------------------------------------------------------------------------
def fetch_amex(company: str = config.TARGET_COMPANY) -> pd.DataFrame:
    """Fetch all complaints for ``company`` and persist them to Parquet."""
    print(f"[ingest] Requesting CFPB complaints for '{company}' ...")
    params = {
        "company": company,
        "format": "json",
        "no_aggs": "true",
        "sort": "created_date_desc",
        "size": 1_000_000,  # API returns the full matching set in one payload
    }
    resp = requests.get(config.CFPB_API, params=params, timeout=600)
    resp.raise_for_status()
    hits = resp.json()
    print(f"[ingest] Received {len(hits):,} raw records.")

    rows = [h["_source"] for h in hits]
    df = pd.DataFrame(rows)

    # Keep and order the schema we care about; guarantee every column exists.
    for col in config.API_FIELDS:
        if col not in df.columns:
            df[col] = pd.NA
    df = df[config.API_FIELDS].copy()

    df = _coerce_types(df)
    df.to_parquet(config.AMEX_RAW, index=False)
    print(f"[ingest] Wrote {len(df):,} rows -> {config.AMEX_RAW.relative_to(config.ROOT)}")
    return df


def _coerce_types(df: pd.DataFrame) -> pd.DataFrame:
    df["date_received"] = pd.to_datetime(df["date_received"], errors="coerce", utc=True).dt.tz_localize(None)
    df["date_sent_to_company"] = pd.to_datetime(df["date_sent_to_company"], errors="coerce", utc=True).dt.tz_localize(None)
    df["complaint_id"] = pd.to_numeric(df["complaint_id"], errors="coerce").astype("Int64")
    df["complaint_what_happened"] = df["complaint_what_happened"].fillna("").astype("string")
    for c in ("product", "sub_product", "issue", "sub_issue", "company", "state",
              "zip_code", "tags", "submitted_via", "company_response",
              "company_public_response", "timely"):
        df[c] = df[c].astype("string")
    return df


# ---------------------------------------------------------------------------
# Full industry bulk export — streamed in chunks
# ---------------------------------------------------------------------------
# Column names in the bulk CSV differ from the API (spaces/hyphens/capitalised).
BULK_COLUMN_MAP = {
    "Date received": "date_received",
    "Product": "product",
    "Sub-product": "sub_product",
    "Issue": "issue",
    "Sub-issue": "sub_issue",
    "Consumer complaint narrative": "complaint_what_happened",
    "Company public response": "company_public_response",
    "Company": "company",
    "State": "state",
    "ZIP code": "zip_code",
    "Tags": "tags",
    "Submitted via": "submitted_via",
    "Date sent to company": "date_sent_to_company",
    "Company response to consumer": "company_response",
    "Timely response?": "timely",
    "Consumer disputed?": "consumer_disputed",
    "Complaint ID": "complaint_id",
}


def bulk_available() -> bool:
    """True when the bulk zip has finished downloading and is a valid archive."""
    if not config.BULK_ZIP.exists():
        return False
    try:
        with zipfile.ZipFile(config.BULK_ZIP) as zf:
            return any(n.lower().endswith(".csv") for n in zf.namelist())
    except zipfile.BadZipFile:
        return False


def load_bulk_iter(chunksize: int = 250_000):
    """Yield chunks of the full CFPB export with normalised column names.

    Reads straight out of the .zip so the ~6 GB CSV is never fully expanded.
    """
    if not bulk_available():
        raise FileNotFoundError(
            f"Bulk file not ready at {config.BULK_ZIP}. "
            "Download it from " + config.CFPB_BULK_ZIP
        )
    usecols = list(BULK_COLUMN_MAP.keys())
    reader = pd.read_csv(
        config.BULK_ZIP,
        compression="zip",
        chunksize=chunksize,
        usecols=lambda c: c in usecols,
        dtype=str,
        on_bad_lines="skip",
        low_memory=True,
    )
    for chunk in reader:
        chunk = chunk.rename(columns=BULK_COLUMN_MAP)
        chunk["date_received"] = pd.to_datetime(chunk["date_received"], errors="coerce")
        yield chunk


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="CFPB ingestion")
    ap.add_argument("--amex", action="store_true", help="Fetch the Amex subset via API")
    ap.add_argument("--check-bulk", action="store_true", help="Report bulk-file status")
    args = ap.parse_args(argv)

    if args.amex:
        df = fetch_amex()
        print(json.dumps({
            "rows": int(len(df)),
            "date_min": str(df["date_received"].min()),
            "date_max": str(df["date_received"].max()),
            "with_narrative": int((df["complaint_what_happened"].str.len() > 0).sum()),
        }, indent=2))
    if args.check_bulk:
        print(f"bulk_available: {bulk_available()}")
        if config.BULK_ZIP.exists():
            mb = config.BULK_ZIP.stat().st_size / 1e6
            print(f"size: {mb:,.1f} MB")
    if not (args.amex or args.check_bulk):
        ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
