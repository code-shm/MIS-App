"""Central configuration for the Amex Complaints Analytics & MIS platform.

All paths are resolved relative to the repository root so the pipeline runs
identically from any working directory. Tunables (target company, model
hyper-parameters, churn heuristic thresholds) live here so the rest of the
codebase stays declarative.
"""
from __future__ import annotations

from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parents[1]

DATA_RAW = ROOT / "data" / "raw"
DATA_PROCESSED = ROOT / "data" / "processed"
DATA_OUTPUTS = ROOT / "data" / "outputs"
MODELS_DIR = ROOT / "models"
FIGURES_DIR = ROOT / "reports" / "figures"

for _d in (DATA_RAW, DATA_PROCESSED, DATA_OUTPUTS, MODELS_DIR, FIGURES_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Data sources (CFPB Consumer Complaint Database — public domain)
# ---------------------------------------------------------------------------
# The full database is 6M+ complaints across all financial companies and powers
# the industry-wide MIS layer. American Express complaints consolidate under a
# single CFPB entity name and power the deep NLP + predictive-modelling layer.
CFPB_API = "https://www.consumerfinance.gov/data-research/consumer-complaints/search/api/v1/"
CFPB_BULK_ZIP = "https://files.consumerfinance.gov/ccdb/complaints.csv.zip"

TARGET_COMPANY = "AMERICAN EXPRESS COMPANY"

# Raw file names
BULK_ZIP = DATA_RAW / "complaints_full.csv.zip"
AMEX_RAW = DATA_RAW / "amex_complaints_raw.parquet"

# Processed / output tables
AMEX_ENRICHED = DATA_PROCESSED / "amex_enriched.parquet"          # + sentiment + features
AMEX_SCORED = DATA_OUTPUTS / "amex_scored.parquet"                # + model predictions
MIS_INDUSTRY = DATA_OUTPUTS / "mis_industry_monthly.parquet"      # 6M+ aggregate MIS
MIS_COMPANY = DATA_OUTPUTS / "mis_company_benchmark.parquet"      # company league table

# ---------------------------------------------------------------------------
# Schema — the CFPB _source fields we keep
# ---------------------------------------------------------------------------
API_FIELDS = [
    "complaint_id", "date_received", "date_sent_to_company", "product",
    "sub_product", "issue", "sub_issue", "company", "state", "zip_code",
    "tags", "submitted_via", "company_response", "company_public_response",
    "timely", "complaint_what_happened",
]

# ---------------------------------------------------------------------------
# Escalation label
# ---------------------------------------------------------------------------
# A complaint is treated as "escalated" when it could not be resolved with a
# plain explanation — i.e. it forced tangible remediation (monetary or
# non-monetary relief) or the company failed to respond in time. This mirrors
# how an Amex service-ops team would triage: relief/late cases are the ones that
# consumed cost, regulatory attention, and relationship capital.
ESCALATION_RESPONSES = {
    "Closed with monetary relief",
    "Closed with non-monetary relief",
}

# ---------------------------------------------------------------------------
# Churn-risk proxy
# ---------------------------------------------------------------------------
# The public dataset has no account-closure signal, so churn is modelled as a
# transparent service-recovery proxy grounded in CX research: a customer is
# flagged at-risk when a negative-sentiment complaint is compounded by a service
# failure (untimely handling, no relief, or a dispute-style narrative). The
# model then LEARNS this relationship from structured + text features so it can
# score new complaints where the outcome is not yet known.
CHURN_SENTIMENT_THRESHOLD = -0.20   # VADER compound below this = negative
CHURN_HIGH_RISK_CUTOFF = 0.50       # predicted-probability threshold for the at-risk flag

# ---------------------------------------------------------------------------
# Model settings
# ---------------------------------------------------------------------------
RANDOM_STATE = 42
TEST_SIZE = 0.20
TFIDF_MAX_FEATURES = 5000
TFIDF_NGRAM = (1, 2)

# ---------------------------------------------------------------------------
# BigQuery (override via environment / CLI as needed)
# ---------------------------------------------------------------------------
BQ_PROJECT = "amex-complaints-insights"
BQ_DATASET = "amex_complaints"
BQ_LOCATION = "US"
BQ_TABLES = {
    "amex_scored": AMEX_SCORED,
    "mis_industry_monthly": MIS_INDUSTRY,
    "mis_company_benchmark": MIS_COMPANY,
}
