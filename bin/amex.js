#!/usr/bin/env node
/**
 * amex — Node CLI wrapper for the Amex Complaints Analytics & MIS platform.
 *
 * The analytics/ML core is Python (pandas, scikit-learn, VADER, matplotlib);
 * this thin launcher lets the whole thing run through npm on any OS:
 *
 *   npm start                 # live self-updating dashboard  (alias: serve)
 *   npm run refresh           # pull latest complaints + rescore
 *   npm run pipeline          # full rebuild (ingest -> models -> dashboard)
 *   npm run report            # generate the executive PDF
 *   npm run mis               # industry MIS over the 17M+ bulk export
 *   npm run powerbi           # export Power BI CSVs
 *   npm run standalone        # rebuild the self-contained dashboard file
 *   npm run bigquery          # emit BigQuery DDL (add creds to also upload)
 *   npm run all               # pipeline + mis + report + exports
 *
 * Pass extra flags after `--`, e.g.  `npm run serve -- --interval 15`.
 */
"use strict";
const { spawn, spawnSync } = require("child_process");
const path = require("path");

const ROOT = path.resolve(__dirname, "..");

// Map friendly subcommands to the Python module + default args.
const COMMANDS = {
  serve:      { mod: "src.serve" },
  refresh:    { mod: "src.refresh" },
  pipeline:   { mod: "src.pipeline" },
  mis:        { mod: "src.mis_aggregate" },
  report:     { mod: "src.report" },
  bigquery:   { mod: "src.bigquery_upload", args: ["--emit-ddl-only"] },
  ingest:     { mod: "src.ingest", args: ["--amex"] },
  scorer:     { mod: "src.browser_export" },
  geo:        { mod: "src.geo_export" },
  // script-based helpers
  powerbi:    { script: "scripts/export_powerbi.py" },
  standalone: { script: "scripts/build_standalone.py" },
  all:        { script: "scripts/run_all.py" },
};

function findPython() {
  for (const cand of ["python", "python3", "py"]) {
    const r = spawnSync(cand, ["--version"], { stdio: "ignore" });
    if (!r.error && r.status === 0) return cand;
  }
  console.error("✗ Python 3.9+ not found on PATH. Install it, then `npm run setup`.");
  process.exit(1);
}

function main() {
  const [cmd, ...rest] = process.argv.slice(2);
  if (!cmd || cmd === "help" || cmd === "--help" || cmd === "-h") {
    console.log("Usage: amex <command> [-- extra args]\n\nCommands:");
    for (const c of Object.keys(COMMANDS)) console.log("  " + c);
    console.log("\nExample: amex serve -- --interval 15");
    process.exit(cmd ? 0 : 1);
  }
  const spec = COMMANDS[cmd];
  if (!spec) {
    console.error(`✗ Unknown command "${cmd}". Run \`amex help\`.`);
    process.exit(1);
  }
  const py = findPython();
  const argv = spec.mod
    ? ["-m", spec.mod, ...(spec.args || []), ...rest]
    : [spec.script, ...(spec.args || []), ...rest];

  const child = spawn(py, argv, { cwd: ROOT, stdio: "inherit" });
  child.on("exit", (code) => process.exit(code == null ? 1 : code));
  process.on("SIGINT", () => child.kill("SIGINT"));
}

main();
