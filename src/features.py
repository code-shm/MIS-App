"""Feature specification shared by the escalation and churn models.

Builds a scikit-learn ColumnTransformer that fuses three signal families:

  * unstructured text  — TF-IDF over the (redaction-cleaned) narrative,
  * structured category — product / issue / state / channel one-hots,
  * derived numeric     — handling time, narrative length, VADER scores.

This is the "structured + unstructured integration" the platform is built
around: one model input matrix carrying both the MIS facts and the NLP-derived
sentiment features.
"""
from __future__ import annotations

from sklearn.compose import ColumnTransformer
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from . import config

CATEGORICAL = ["product", "sub_product", "issue", "state", "submitted_via"]
NUMERIC = ["handling_days", "narrative_length", "has_narrative",
           "sent_neg", "sent_neu", "sent_pos", "sent_compound"]
TEXT = "narrative"

# Columns a fitted model needs present at inference time.
REQUIRED = CATEGORICAL + NUMERIC + [TEXT]


def build_preprocessor() -> ColumnTransformer:
    text_pipe = TfidfVectorizer(
        max_features=config.TFIDF_MAX_FEATURES,
        ngram_range=config.TFIDF_NGRAM,
        stop_words="english",
        min_df=5,
        sublinear_tf=True,
    )
    cat_pipe = Pipeline([
        ("impute", SimpleImputer(strategy="constant", fill_value="Unknown")),
        ("onehot", OneHotEncoder(handle_unknown="ignore", min_frequency=25)),
    ])
    num_pipe = Pipeline([
        ("impute", SimpleImputer(strategy="median")),
        ("scale", StandardScaler()),
    ])
    return ColumnTransformer(
        transformers=[
            ("text", text_pipe, TEXT),
            ("cat", cat_pipe, CATEGORICAL),
            ("num", num_pipe, NUMERIC),
        ],
        remainder="drop",
        sparse_threshold=0.3,
    )
