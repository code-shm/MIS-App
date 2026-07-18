# Data dictionary — `amex_scored` (fact_complaints)

Grain: **one row per complaint**. Produced by `src/pipeline.py`.

| Column | Type | Source | Description |
|--------|------|--------|-------------|
| `complaint_id` | int64 | CFPB | Unique complaint identifier |
| `date_received` | datetime | CFPB | Date CFPB received the complaint |
| `year` / `month` / `year_month` / `quarter` | derived | clean | Calendar keys for MIS time-series |
| `product` / `sub_product` | string | CFPB | Amex product line |
| `issue` / `sub_issue` | string | CFPB | Complaint issue taxonomy |
| `state` | string | CFPB | Consumer state |
| `submitted_via` | string | CFPB | Channel (Web, Phone, Referral, …) |
| `company_response` | string | CFPB | Resolution (Closed with explanation / relief / …) |
| `timely` | string | CFPB | Whether the company responded in time |
| `handling_days` | float | derived | Days from receipt → forwarded to company |
| `narrative` | string | CFPB | Complaint text, CFPB `XXXX` redactions stripped |
| `narrative_length` | int | derived | Character length of the cleaned narrative |
| `has_narrative` | 0/1 | derived | Whether a non-empty narrative exists |
| `sent_neg` / `sent_neu` / `sent_pos` | float | VADER | Sentiment component scores |
| `sent_compound` | float | VADER | Normalised −1…+1 sentiment |
| `sentiment_label` | string | derived | Positive / Neutral / Negative |
| `sentiment_band` | string | derived | Very Negative … Very Positive |
| `is_negative` | 0/1 | derived | `sent_compound` ≤ −0.20 |
| `is_escalated` | 0/1 | **label** | Relief given OR timely-response SLA breached |
| `escalation_score` | float | model | Predicted P(escalation) |
| `escalation_flag` | 0/1 | model | `escalation_score` ≥ 0.5 |
| `churn_risk_label` | 0/1 | **proxy label** | Negative sentiment + service failure |
| `churn_risk_score` | float | model | Predicted P(churn risk), intake-only features |
| `churn_high_risk` | 0/1 | model | `churn_risk_score` ≥ 0.50 |
| `timely_flag` / `relief_flag` | 0/1 | derived | Convenience flags for BI measures |

## `mis_industry_monthly`
One row per (`year_month`, `segment` ∈ {Industry, Amex}): `complaints`,
`timely`, `relief`, `narrative`, and the derived `timely_rate`, `relief_rate`,
`narrative_rate`. Computed over the full 17M+ national dataset.

## `mis_company_benchmark`
One row per company across the whole dataset: `complaints`, `timely_rate`,
`relief_rate`, `narrative_rate`, `rank` (by volume), `is_amex`.
