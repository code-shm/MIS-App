"""Load the curated output tables into Google BigQuery.

The pipeline writes analytics-ready Parquet locally; this module pushes those
tables to BigQuery so the Power BI dashboard (or any BI tool) can query them at
scale. It is intentionally optional — it only runs when Google credentials are
available (``GOOGLE_APPLICATION_CREDENTIALS`` or ``gcloud auth``). When creds are
absent it degrades gracefully and instead emits the ``CREATE TABLE`` DDL under
``sql/`` so the schema is still versioned and reproducible.

Usage:
    python -m src.bigquery_upload --project my-proj --dataset amex_complaints
    python -m src.bigquery_upload --emit-ddl-only      # no cloud needed
"""
from __future__ import annotations

import argparse
import sys

import pandas as pd

from . import config


def _bq_type(dtype) -> str:
    dt = str(dtype).lower()  # handles nullable dtypes like "Int64"/"Float32"
    if "datetime" in dt:
        return "TIMESTAMP"
    if "bool" in dt:
        return "BOOL"
    if "int" in dt:
        return "INT64"
    if "float" in dt:
        return "FLOAT64"
    return "STRING"


def emit_ddl() -> str:
    """Generate CREATE TABLE DDL for every output table from its Parquet schema."""
    lines = [f"-- Auto-generated BigQuery DDL for `{config.BQ_PROJECT}.{config.BQ_DATASET}`",
             f"CREATE SCHEMA IF NOT EXISTS `{config.BQ_PROJECT}.{config.BQ_DATASET}`"
             f" OPTIONS(location='{config.BQ_LOCATION}');", ""]
    for name, path in config.BQ_TABLES.items():
        if not path.exists():
            lines.append(f"-- ({name}: {path.name} not built yet — run the pipeline first)\n")
            continue
        df = pd.read_parquet(path)
        cols = ",\n".join(f"  `{c}` {_bq_type(t)}" for c, t in df.dtypes.items())
        lines.append(f"CREATE OR REPLACE TABLE `{config.BQ_PROJECT}.{config.BQ_DATASET}.{name}` (")
        lines.append(cols)
        lines.append(");\n")
    ddl = "\n".join(lines)
    out = config.ROOT / "sql" / "bigquery_schema.sql"
    out.write_text(ddl)
    print(f"[bq] Wrote DDL -> {out.relative_to(config.ROOT)}")
    return ddl


def upload(project: str, dataset: str, location: str = config.BQ_LOCATION) -> None:
    try:
        from google.cloud import bigquery
    except ImportError:
        print("[bq] google-cloud-bigquery not installed — run `pip install google-cloud-bigquery`.")
        return

    client = bigquery.Client(project=project)
    ds_ref = bigquery.Dataset(f"{project}.{dataset}")
    ds_ref.location = location
    client.create_dataset(ds_ref, exists_ok=True)
    print(f"[bq] Dataset ready: {project}.{dataset} ({location})")

    for name, path in config.BQ_TABLES.items():
        if not path.exists():
            print(f"[bq] skip {name}: {path.name} not built.")
            continue
        df = pd.read_parquet(path)
        table_id = f"{project}.{dataset}.{name}"
        job = client.load_table_from_dataframe(
            df, table_id,
            job_config=bigquery.LoadJobConfig(write_disposition="WRITE_TRUNCATE"),
        )
        job.result()
        print(f"[bq] Loaded {len(df):,} rows -> {table_id}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="BigQuery loader")
    ap.add_argument("--project", default=config.BQ_PROJECT)
    ap.add_argument("--dataset", default=config.BQ_DATASET)
    ap.add_argument("--location", default=config.BQ_LOCATION)
    ap.add_argument("--emit-ddl-only", action="store_true",
                    help="Only write sql/bigquery_schema.sql, do not touch the cloud")
    args = ap.parse_args(argv)

    emit_ddl()
    if args.emit_ddl_only:
        return 0
    try:
        upload(args.project, args.dataset, args.location)
    except Exception as exc:  # noqa: BLE001 — creds/network failures are expected offline
        print(f"[bq] Cloud upload skipped ({type(exc).__name__}: {exc}).")
        print("[bq] DDL still written under sql/ — set GOOGLE_APPLICATION_CREDENTIALS to enable upload.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
