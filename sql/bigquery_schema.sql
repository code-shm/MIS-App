-- Auto-generated BigQuery DDL for `amex-complaints-insights.amex_complaints`
CREATE SCHEMA IF NOT EXISTS `amex-complaints-insights.amex_complaints` OPTIONS(location='US');

CREATE OR REPLACE TABLE `amex-complaints-insights.amex_complaints.amex_scored` (
  `complaint_id` INT64,
  `date_received` TIMESTAMP,
  `year` INT64,
  `month` INT64,
  `year_month` STRING,
  `quarter` STRING,
  `product` STRING,
  `sub_product` STRING,
  `issue` STRING,
  `sub_issue` STRING,
  `state` STRING,
  `submitted_via` STRING,
  `company_response` STRING,
  `timely` STRING,
  `handling_days` FLOAT64,
  `narrative` STRING,
  `narrative_length` INT64,
  `has_narrative` INT64,
  `sent_neg` FLOAT64,
  `sent_neu` FLOAT64,
  `sent_pos` FLOAT64,
  `sent_compound` FLOAT64,
  `sentiment_label` STRING,
  `sentiment_band` STRING,
  `is_negative` INT64,
  `is_escalated` INT64,
  `escalation_score` FLOAT64,
  `escalation_flag` INT64,
  `churn_risk_label` INT64,
  `churn_risk_score` FLOAT64,
  `churn_high_risk` INT64,
  `relief_flag` INT64,
  `timely_flag` INT64
);

CREATE OR REPLACE TABLE `amex-complaints-insights.amex_complaints.mis_industry_monthly` (
  `year_month` STRING,
  `segment` STRING,
  `complaints` INT64,
  `timely` INT64,
  `relief` INT64,
  `narrative` INT64,
  `timely_rate` FLOAT64,
  `relief_rate` FLOAT64,
  `narrative_rate` FLOAT64
);

CREATE OR REPLACE TABLE `amex-complaints-insights.amex_complaints.mis_company_benchmark` (
  `company` STRING,
  `complaints` INT64,
  `timely` INT64,
  `relief` INT64,
  `narrative` INT64,
  `timely_rate` FLOAT64,
  `relief_rate` FLOAT64,
  `narrative_rate` FLOAT64,
  `rank` INT64,
  `is_amex` BOOL
);
