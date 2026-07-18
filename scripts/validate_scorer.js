/* Parity harness: run the JS scorer on the shared test strings and emit JSON.
 * Compared against the Python pipeline by scripts/validate_scorer.py. */
"use strict";
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const HTML = path.resolve(__dirname, "..", "dashboards", "html");
const ctx = { window: {}, console, Math, Set, Map, JSON };
ctx.globalThis = ctx;
vm.createContext(ctx);
for (const f of ["scorer_assets.js", "scorer.js"]) {
  vm.runInContext(fs.readFileSync(path.join(HTML, f), "utf8"), ctx, { filename: f });
}
const Scorer = ctx.window.Scorer;

const tests = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const out = tests.map((t) => {
  const s = Scorer.sentiment(t);
  const e = Scorer.escalation(t);
  return { text: t, compound: s.compound, prob: Math.round(e.prob * 1e6) / 1e6 };
});
process.stdout.write(JSON.stringify(out));
