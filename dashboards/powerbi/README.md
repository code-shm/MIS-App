# Power BI dashboard — build guide

The interactive HTML dashboard (`dashboards/html/`) is the ready-to-view
deliverable. This folder reproduces the **same model in Power BI Desktop**, which
is the tool named on the résumé and the one an Amex MIS team would publish to
the Power BI Service.

## 1. Data model (star schema)

```
                 ┌─────────────────────┐
                 │      dim_date       │
                 │  date (key)         │
                 │  year, quarter,     │
                 │  month, month_name, │
                 │  year_month         │
                 └──────────┬──────────┘
                            │ 1
                            │
                            │ *
        ┌───────────────────┴────────────────────┐
        │            fact_complaints              │  grain: one complaint
        │  complaint_id, date_received (→dim_date)│
        │  product, sub_product, issue, sub_issue │
        │  state, submitted_via, company_response │
        │  handling_days, narrative_length        │
        │  sent_compound, sentiment_label,        │  ← VADER enrichment
        │  is_negative                            │
        │  is_escalated, escalation_score,        │  ← escalation model
        │  escalation_flag                        │
        │  churn_risk_score, churn_high_risk      │  ← churn model
        │  timely_flag, relief_flag               │
        └─────────────────────────────────────────┘

   mis_industry_monthly   ── standalone (industry vs. Amex monthly benchmark)
   mis_company_benchmark  ── standalone (company league table, Amex highlighted)
```

Relationship: `fact_complaints[date_received]` → `dim_date[date]`
(single direction, one-to-many). Mark `dim_date` as the date table.

## 2. Load the data

**Option A — local CSV (no cloud needed).** In Power BI Desktop:
`Get Data → Text/CSV` and load each file from `dashboards/powerbi/data/`:
`fact_complaints.csv`, `dim_date.csv`, `mis_industry_monthly.csv`,
`mis_company_benchmark_top200.csv`. These are produced by
`python scripts/export_powerbi.py`.

**Option B — BigQuery (production).** `Get Data → Google BigQuery`, sign in, and
select the `amex_complaints` dataset (tables loaded by `python -m
src.bigquery_upload`). Use **DirectQuery** for live refresh or **Import** for
speed. The table schema is versioned in [`sql/bigquery_schema.sql`](../../sql/bigquery_schema.sql).

## 3. Measures

Create the measures from [`measures.dax`](measures.dax) (Modeling → New measure,
one per block). They cover volume, escalation, VADER sentiment, churn risk,
service quality (timely/relief), and MoM/YoY/rolling time intelligence.

## 4. Suggested report pages

1. **Executive MIS** — KPI cards (Total Complaints, Escalation Rate, Negative
   Sentiment Rate, Churn-Risk Rate, Timely Response Rate), a monthly volume line
   with YoY, and the product/issue mix.
2. **Escalation intelligence** — escalation rate by issue & product (bar),
   `Avg Escalation Score` distribution, and a table of the top predicted-to-
   escalate open cases.
3. **Voice of customer (NLP)** — sentiment band breakdown, average sentiment by
   product, and sentiment trend over time.
4. **Churn & retention** — churn-risk rate by issue/state, `Avg Churn-Risk
   Score` gauge, and a decile table of highest-risk customers to prioritise.
5. **Industry benchmark** — `Amex Industry Rank` card, Amex-vs-industry timely/
   relief lines, and the company league table with Amex highlighted.

## 5. Theme

A JSON theme matching the dashboard palette (Amex blue `#006FCF`, status
good/warning/critical) is in [`amex_theme.json`](amex_theme.json) —
`View → Themes → Browse for themes`.
