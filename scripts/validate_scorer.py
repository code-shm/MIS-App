"""Validate the browser scorer matches the Python pipeline (VADER + text model).

Runs the same test strings through Python VADER and the persisted text
escalation model, invokes the JS scorer via node, and reports max deviation.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import joblib
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src import config  # noqa: E402

TESTS = [
    "This is a scam, they never refunded my money!",
    "AMEX was absolutely wonderful and resolved my issue quickly.",
    "I am not happy with the service at all.",
    "The card was fine but the customer support was terrible.",
    "They charged me twice and refused to help. Worst experience ever!!!",
    "kind of disappointed but it worked out okay in the end",
    "no problems whatsoever, great job",
    "I disputed a fraudulent charge and they closed my account without notice.",
    "Membership rewards points were never credited despite multiple calls.",
    "Excellent service, very satisfied with the quick resolution.",
    "least helpful representative I have ever dealt with",
    "They SERIOUSLY messed up my billing and would not fix it.",
]


def main() -> int:
    analyzer = SentimentIntensityAnalyzer()
    pipe = joblib.load(config.MODELS_DIR / "escalation_text_model.joblib")
    probs = pipe.predict_proba(TESTS)[:, 1]

    py = [{"text": t,
           "compound": round(analyzer.polarity_scores(t)["compound"], 4),
           "prob": round(float(p), 6)}
          for t, p in zip(TESTS, probs)]

    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as fh:
        json.dump(TESTS, fh)
        tests_path = fh.name

    res = subprocess.run(["node", str(ROOT / "scripts" / "validate_scorer.js"), tests_path],
                         capture_output=True, text=True, cwd=ROOT)
    if res.returncode != 0:
        print("node failed:", res.stderr); return 1
    js = json.loads(res.stdout)

    max_sent, max_prob = 0.0, 0.0
    print(f"{'compound (py/js)':>26} | {'esc prob (py/js)':>24} | text")
    for p, j in zip(py, js):
        ds = abs(p["compound"] - j["compound"]); dp = abs(p["prob"] - j["prob"])
        max_sent = max(max_sent, ds); max_prob = max(max_prob, dp)
        flag = "" if (ds < 0.02 and dp < 0.02) else "  <-- MISMATCH"
        print(f"{p['compound']:+.4f}/{j['compound']:+.4f}   | "
              f"{p['prob']:.4f}/{j['prob']:.4f}   | {p['text'][:42]}{flag}")

    print(f"\nMax sentiment deviation: {max_sent:.5f}  |  Max escalation-prob deviation: {max_prob:.5f}")
    ok = max_sent < 0.02 and max_prob < 0.02
    print("RESULT:", "PASS - browser scorer matches Python" if ok else "FAIL - divergence too large")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
