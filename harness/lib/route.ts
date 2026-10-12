// The router step of a workbench run. It calls decide() from router.ts, which is the
// workbench-sandbox router copied unchanged apart from its import path, on facts computed
// outside the session: the diff, the trusted checks, the fail-first grading, the reviewer's
// verdict and the class, batch and proof rows. It never reads Claude's own account of the work.
//
//   node harness/lib/route.ts <task run dir> <harness dir> <pack id>
//
// Writes <run dir>/decision.json and prints it.
import * as fs from "node:fs";
import * as path from "node:path";
import { decide, type RouteDecision } from "./router.ts";

function readJson(file: string): any {
  try {
    return JSON.parse(fs.readFileSync(file, "utf8"));
  } catch {
    return undefined;
  }
}

const [runDir, harnessDir, packId] = process.argv.slice(2);
if (!runDir || !harnessDir || !packId) {
  console.error("usage: route.ts <task run dir> <harness dir> <pack id>");
  process.exit(2);
}

const plan = readJson(path.join(runDir, "plan.json"));
const facts = readJson(path.join(runDir, "facts.json"));
const verdict = readJson(path.join(runDir, "verdict.json"));
const scope = readJson(path.join(runDir, "scope.json")) ?? { harness: [], outside: [] };
const packetPresent = fs.existsSync(path.join(runDir, "packet.json"));
const classRow = plan?.classRow ?? undefined;
// The prover's record for this class: pass^k of its cases on a given pack.
const evalRow = plan ? readJson(path.join(harnessDir, "proofs", `${plan.class}.json`)) : undefined;

let decision: RouteDecision & { approval?: string; className?: string };
if (scope.harness.length > 0) {
  decision = { path: "reject", reasons: [`changes the harness that judges it: ${scope.harness.slice(0, 5).join(", ")}`] };
} else if (scope.outside.length > 0) {
  decision = { path: "reject", reasons: [`outside the spec's scope: ${scope.outside.slice(0, 5).join(", ")}`] };
} else {
  decision = decide({
    taskId: facts?.taskId,
    facts,
    verdict,
    packetPresent,
    kind: "implement",
    classRow,
    batchPlanId: plan?.batchPlanId ?? undefined,
    batchPlanRow: plan?.batchPlanRow ?? undefined,
    evalRow,
    imageId: packId,
    driver: "guest",
  });
  // A class marked high risk goes to a person whatever its paths, on top of the path rules.
  if (decision.path !== "reject" && classRow?.risk === "high" && !decision.reasons.some((r) => r.startsWith("high risk"))) {
    decision = { path: "per_pr", reasons: [`high risk: class ${plan.class} is high risk by policy`, ...decision.reasons] };
  }
  if (decision.path === "per_pr" && decision.reasons[0] === "class not graduated") {
    decision.reasons[0] = `class ${plan.class} is approved per PR (harness/classes.toml)`;
  }
}

const out = {
  taskId: facts?.taskId ?? null,
  spec: plan?.id ?? null,
  className: plan?.class ?? null,
  ...decision,
  packId,
  // What happens next, in words a reviewer reads on the PR.
  next: {
    per_pr: "A person reviews this PR.",
    batch_plan: `Joins approved batch ${plan?.batchPlanId}: one person approves the batch with harness/bin/approve-batch.sh.`,
    graduated: "Merges by policy: the class is graduated and its cases hold pass^k on this pack.",
    reject: "Halted with the reasons above. No PR.",
  }[decision.path],
  at: new Date().toISOString(),
};
fs.writeFileSync(path.join(runDir, "decision.json"), JSON.stringify(out, null, 2) + "\n");
console.log(JSON.stringify(out));
