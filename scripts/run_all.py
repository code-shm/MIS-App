"""One-command reproduction of the whole platform.

    python scripts/run_all.py            # full run (fetches Amex, builds MIS)
    python scripts/run_all.py --fast     # skip the 17M-row MIS pass

Steps:
    1. ingest Amex subset (CFPB API)      -> data/raw/amex_complaints_raw.parquet
    2. clean + VADER + train + score      -> data/outputs/amex_scored.parquet
    3. industry MIS over the 17M+ bulk     -> data/outputs/mis_*.parquet
    4. dashboard extract + standalone html -> dashboards/html/
    5. Power BI CSVs + BigQuery DDL        -> dashboards/powerbi/, sql/
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable


def run(cmd: list[str]) -> None:
    print(f"\n$ {' '.join(cmd)}")
    subprocess.run(cmd, cwd=ROOT, check=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fast", action="store_true", help="Skip the 17M-row MIS aggregation")
    args = ap.parse_args()

    run([PY, "-m", "src.pipeline"])                       # ingest + models + dashboard extract
    if not args.fast:
        run([PY, "-m", "src.mis_aggregate"])              # industry MIS (needs the bulk zip)
        run([PY, "-m", "src.pipeline", "--from-enriched"])  # refresh extract with MIS layer
    run([PY, "scripts/build_standalone.py"])
    run([PY, "scripts/export_powerbi.py"])
    run([PY, "-m", "src.bigquery_upload", "--emit-ddl-only"])
    print("\nAll done. Open dashboards/html/amex_dashboard_standalone.html")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
