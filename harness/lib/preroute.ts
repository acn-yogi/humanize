// The dispatcher's preview: for each spec in the queue, what will happen before any spend.
// It applies the router's own risk patterns (risk.ts) to the spec's declared scope, so a spec
// that can touch a manifest, CI or instruction file is known to stop for a person before it
// runs. The router still decides on the real diff afterwards; this is a forecast, not a verdict.
//
//   python3 harness/lib/plan.py queue harness specs | node harness/lib/preroute.ts <ledger.jsonl>
import * as fs from "node:fs";
import { classifyPaths, RISK_FLAGS } from "./risk.ts";

const LABEL: Record<string, string> = {
  touchesCi: "CI",
  touchesInstructions: "agent instructions",
  touchesManifests: "package manifest",
  touchesSecurityPaths: "security paths",
};

const plans = JSON.parse(fs.readFileSync(0, "utf8"));
const ledgerFile = process.argv[2];
const done = new Map<string, any>();
if (ledgerFile && fs.existsSync(ledgerFile)) {
  for (const line of fs.readFileSync(ledgerFile, "utf8").split("\n")) {
    if (!line.trim()) continue;
    try {
      const row = JSON.parse(line);
      if (row.spec && row.path !== "reject" && !row.trial) done.set(row.spec, row);
    } catch {}
  }
}

const rows = plans.map((p: any) => {
  // Globs name files; the risk patterns match file names, so strip the wildcard tail.
  const paths = p.scope.map((s: string) => s.replace(/\/\*\*$/, "/x").replace(/\*/g, "x"));
  const { flags } = classifyPaths(paths);
  const risky = RISK_FLAGS.filter((f) => flags[f]).map((f) => LABEL[f]);
  // The phase (harness/config.toml [harness] phase) comes with every plan.
  const phase: number = typeof p.phase === "number" ? p.phase : 2;
  let action: string;
  let forecast: string;
  if (phase === 0) {
    action = "wait";
    forecast = "phase 0 (assess): nothing runs until the readiness assessment is done (demo/assess.md)";
  } else if (p.status !== "approved") {
    action = "wait";
    forecast = `intent not approved (${p.status}): no spend until a person approves the spec`;
  } else if (done.has(p.id)) {
    action = "done";
    const row = done.get(p.id);
    forecast = `already ran: ${row.path}${row.pr ? `, ${row.pr}` : ""}`;
  } else if (phase === 1) {
    // Assisted: the class still names the work, but every PR goes to a person.
    action = "run";
    forecast = `phase 1 (assisted): a person reviews every PR (class ${p.class}${risky.length || p.classRow?.risk === "high" ? ", high risk" : ""})`;
  } else if (risky.length || p.classRow?.risk === "high") {
    action = "run";
    forecast = `HIGH RISK (${[...risky, ...(p.classRow?.risk === "high" ? [`class ${p.class}`] : [])].join(", ")}): runs, then stops for a person at the PR`;
  } else if (p.classRow?.approval === "batch" && p.batchPlanRow?.approved === true) {
    action = "run";
    forecast = `mechanical: joins approved batch ${p.batchPlanId}; one approval merges the batch`;
  } else if (p.classRow?.graduated === true) {
    action = "run";
    forecast = "graduated: merges by policy while its cases hold pass^k";
  } else {
    action = "run";
    forecast = `per PR: a person reviews the PR (class ${p.class})`;
  }
  return { id: p.id, file: p.file, class: p.class, issue: p.issue, action, forecast, caps: p.caps, phase, phaseName: p.phaseName, phaseSource: p.phaseSource };
});
console.log(JSON.stringify(rows));
