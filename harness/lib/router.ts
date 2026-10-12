import { classifyPaths, RISK_FLAGS, type RiskFlag } from "./risk.ts";

export type RoutePath = "per_pr" | "batch_plan" | "graduated" | "reject";
export interface RouteDecision {
  path: RoutePath;
  reasons: string[];
}

export interface CheckResult {
  cmd: string;
  exit: number;
  runs: number;
  flaky: boolean;
}

/** `intake-results/<taskId>/intake.json`, as written by the trusted runner. */
export interface IntakeFacts {
  taskId: string;
  changedPaths: string[];
  touchesCi: boolean;
  touchesInstructions: boolean;
  touchesManifests: boolean;
  touchesSecurityPaths: boolean;
  /** Added or modified symlink (120000) or gitlink (160000). Written by trusted-run.sh. */
  touchesLinks?: boolean;
  linesChanged: number;
  checks: CheckResult[];
  allChecksPass: boolean;
  /** The commit intake analyzed (the base commit when there was no result bundle). */
  resultSha: string;
  /** S3 version and ETag of the result bundle intake analyzed; null when there was none. */
  resultBundleVersionId: string | null;
  resultBundleETag: string | null;
  /** The commit intake diffed from (v3). */
  baseSha?: string;
  /** Grading of a case or a fail-first spec (v3); null or absent when there was none. */
  grading?: Grading | null;
}

/** `intake.json` `grading` (CONTRACTS.md "Intake grading"). */
export interface Grading {
  mode: "case" | "fail-first";
  caseId: string | null;
  patchApplied: boolean;
  baseChecks: Array<{ cmd: string; exit: number }>;
  checks: CheckResult[];
  ok: boolean;
  reasons: string[];
}

const SHA_RE = /^([0-9a-f]{40}|[0-9a-f]{64})$/;
/** S3 version ids and ETags are opaque but printable; nothing that could break a copy source. */
const OPAQUE_RE = /^[A-Za-z0-9._"-]{1,1024}$/;

const RISK_LABEL: Record<RiskFlag, string> = {
  touchesCi: "CI configuration or code owners",
  touchesInstructions: "agent instruction files",
  touchesManifests: "package manifests or lockfiles",
  touchesSecurityPaths: "auth or security paths",
};

/** Strict parse of untrusted JSON into intake facts; anything off shape is undefined. */
export function parseIntakeFacts(value: unknown, expectedTaskId: string): IntakeFacts | undefined {
  if (!value || typeof value !== "object" || Array.isArray(value)) return undefined;
  const v = value as Record<string, unknown>;
  if (v.taskId !== expectedTaskId) return undefined;
  if (!Array.isArray(v.changedPaths) || !v.changedPaths.every((p) => typeof p === "string")) return undefined;
  for (const flag of RISK_FLAGS) if (typeof v[flag] !== "boolean") return undefined;
  if (v.touchesLinks !== undefined && typeof v.touchesLinks !== "boolean") return undefined;
  if (typeof v.linesChanged !== "number" || !Number.isFinite(v.linesChanged)) return undefined;
  if (typeof v.allChecksPass !== "boolean" || !Array.isArray(v.checks)) return undefined;
  for (const c of v.checks) {
    if (!c || typeof c !== "object") return undefined;
    const ck = c as Record<string, unknown>;
    if (typeof ck.cmd !== "string" || typeof ck.exit !== "number" || typeof ck.flaky !== "boolean") return undefined;
  }
  // The analyzed bundle is pinned: any change must name its commit, S3 version and ETag.
  if (typeof v.resultSha !== "string" || !SHA_RE.test(v.resultSha)) return undefined;
  const pinned = typeof v.resultBundleVersionId === "string" && typeof v.resultBundleETag === "string";
  const none = v.resultBundleVersionId === null && v.resultBundleETag === null;
  if (!pinned && !none) return undefined;
  if (pinned && (!OPAQUE_RE.test(v.resultBundleVersionId as string) || !OPAQUE_RE.test(v.resultBundleETag as string))) return undefined;
  if (none && v.changedPaths.length > 0) return undefined;
  if (v.baseSha !== undefined && (typeof v.baseSha !== "string" || !SHA_RE.test(v.baseSha))) return undefined;
  if (v.grading !== undefined && v.grading !== null) {
    const g = v.grading as Record<string, unknown>;
    if (typeof g !== "object" || Array.isArray(g)) return undefined;
    if (g.mode !== "case" && g.mode !== "fail-first") return undefined;
    if (typeof g.ok !== "boolean" || !Array.isArray(g.checks) || !Array.isArray(g.reasons)) return undefined;
  }
  return v as unknown as IntakeFacts;
}

/** Only the exact string "approve" counts as approval; anything else is not. */
export function parseVerdict(value: unknown): "approve" | "reject" | undefined {
  if (!value || typeof value !== "object") return undefined;
  const verdict = (value as Record<string, unknown>).verdict;
  return verdict === "approve" || verdict === "reject" ? verdict : undefined;
}

export interface RouteInput {
  taskId: string;
  facts: unknown;
  verdict: unknown;
  packetPresent: boolean;
  /** Row from the classes table, or undefined when the class has no row. */
  classRow?: Record<string, unknown>;
  batchPlanId?: string;
  /** Row for `batch:<batchPlanId>` in the classes table; a plan counts only when approved. */
  batchPlanRow?: Record<string, unknown>;
  /** "improve" for an improver workbench's pack change (v3); implement otherwise. */
  kind?: string;
  /** Row `eval:<class>` the prover wrote: the class's cases on one image, at pass^k. */
  evalRow?: Record<string, unknown>;
  /** The image the workbench ran, from done.json. */
  imageId?: string;
  /** Where Claude Code ran, from done.json: guest (also when absent) or host. */
  driver?: string;
}

/**
 * The risk router. Reads only what intake computed, the review verdict and the class row;
 * never the workbench's packet contents. High-risk paths are always per_pr.
 */
export function decide(input: RouteInput): RouteDecision {
  const facts = parseIntakeFacts(input.facts, input.taskId);
  if (!facts) return { path: "reject", reasons: ["intake facts missing or malformed"] };
  if (!input.packetPresent) return { path: "reject", reasons: ["packet missing"] };
  if (facts.changedPaths.length === 0) return { path: "reject", reasons: ["no changes"] };
  // Fail first (proposal section 12): the reproducing test must fail on the base and pass on
  // the result. A grading that is not ok is a rejection whatever else passed.
  if (facts.grading && facts.grading.ok !== true) {
    const why = facts.grading.reasons.map((r) => String(r).slice(0, 300)).slice(0, 10);
    return { path: "reject", reasons: [`reproducing test (${facts.grading.mode}) did not hold`, ...why] };
  }

  const failing = facts.checks.filter((c) => !c.flaky && c.exit !== 0).map((c) => c.cmd);
  if (!facts.allChecksPass || failing.length > 0) {
    return { path: "reject", reasons: [`checks failed: ${failing.join(", ") || "allChecksPass is false"}`] };
  }

  const verdict = parseVerdict(input.verdict);
  if (!verdict) return { path: "reject", reasons: ["review verdict missing or malformed"] };
  // A finding from the adversarial reviewer is for a person to judge (proposal section 11):
  // it sends the change to per_pr with the reviewer's reasons, never to an automatic path.
  if (verdict === "reject") {
    const reviewReasons = Array.isArray((input.verdict as { reasons?: unknown }).reasons)
      ? ((input.verdict as { reasons: unknown[] }).reasons.filter((r) => typeof r === "string") as string[]).slice(0, 20)
      : [];
    return { path: "per_pr", reasons: ["adversarial review raised findings", ...reviewReasons] };
  }
  // A pack change reaches every workbench: the prover proves it and people release it.
  if (input.kind === "improve") {
    return { path: "per_pr", reasons: ["pack change from the improver: proven by the prover and released by people, never merged automatically"] };
  }

  const recomputed = classifyPaths(facts.changedPaths);
  const risky = RISK_FLAGS.filter((f) => facts[f] || recomputed.flags[f]);
  const riskReasons = risky.map((f) => {
    const paths = recomputed.hits[f].slice(0, 5);
    return `high risk: touches ${RISK_LABEL[f]}${paths.length ? ` (${paths.join(", ")})` : ""}`;
  });
  // Links cannot be seen from paths, so only intake can clear them; a missing fact counts as a link.
  if (facts.touchesLinks !== false) {
    riskReasons.push(
      facts.touchesLinks === true ? "high risk: adds or modifies a symlink or submodule" : "high risk: link facts missing",
    );
  }
  if (riskReasons.length > 0) return { path: "per_pr", reasons: riskReasons };

  const flaky = facts.checks.filter((c) => c.flaky).map((c) => c.cmd);
  const notes = flaky.length ? [`flaky checks quarantined: ${flaky.join(", ")}`] : [];
  if (facts.checks.length - flaky.length === 0) {
    return { path: "per_pr", reasons: ["no stable checks ran", ...notes] };
  }

  if (input.batchPlanId) {
    // The yes for a batch sits on the plan: it must be registered and approved by a person.
    if (input.batchPlanRow?.approved !== true || input.batchPlanRow?.class !== `batch:${input.batchPlanId}`) {
      return { path: "per_pr", reasons: [`batch plan ${input.batchPlanId} is not registered as approved`, ...notes] };
    }
    return { path: "batch_plan", reasons: [`instance of approved batch plan ${input.batchPlanId}`, ...notes] };
  }
  if (input.classRow && input.classRow.graduated === true) {
    // Graduation reads pass^k on the image this task ran: a new pack sends the class back to
    // per_pr until the prover re-certifies its cases (CONTRACTS.md v3).
    // It also reads the placement: cases proven with Claude Code in the microVM say nothing yet
    // about the host driver, and the other way round (CONTRACTS.md "Host driver").
    const ev = input.evalRow;
    const taskDriver = input.driver ?? "guest";
    const rowDriver = ev?.driver ?? "guest";
    const proven =
      ev !== undefined &&
      ev.passK === 1 &&
      typeof ev.imageId === "string" &&
      typeof input.imageId === "string" &&
      ev.imageId === input.imageId &&
      rowDriver === taskDriver;
    if (!proven) {
      const why = !ev
        ? "class graduated, but its cases have no pass^k record"
        : ev.imageId !== input.imageId
          ? "class graduated, but its cases are not yet proven on this pack (pass^k)"
          : rowDriver !== taskDriver
            ? `class graduated, but its cases are proven with the ${String(rowDriver)} driver, not the ${taskDriver} driver`
            : `class graduated, but its cases are at pass^k ${String(ev.passK)} on this pack`;
      return { path: "per_pr", reasons: [why, ...notes] };
    }
    return { path: "graduated", reasons: ["class graduated, cases at pass^k 1 on this pack, checks pass, review approved", ...notes] };
  }
  return {
    path: "per_pr",
    reasons: [input.classRow ? "class not graduated" : "class unknown", ...notes],
  };
}

/** What the workbench gate decides after TrustedRun: review the result, or go straight to Reject. */
export interface WorkbenchOutcome {
  path: "review" | "reject";
  reasons: string[];
}

/**
 * Whether a workbench produced something worth reviewing. A review workbench is dispatched only when
 * the host reported `status: "ok"` in done.json, the result bundle is in intake/, and the
 * trusted runner's facts parse and pin that bundle. Anything else is rejected here, without
 * spending a review workbench on a result that does not exist.
 */
export function workbenchOutcome(input: { taskId: string; done: unknown; resultBundlePresent: boolean; facts: unknown }): WorkbenchOutcome {
  const reasons: string[] = [];
  const done = input.done && typeof input.done === "object" && !Array.isArray(input.done) ? (input.done as Record<string, unknown>) : undefined;
  if (!done) reasons.push("done.json missing or malformed");
  else if (done.taskId !== input.taskId) reasons.push("done.json names another task");
  else if (done.status !== "ok") reasons.push(`workbench status ${typeof done.status === "string" ? done.status.slice(0, 40) : "unknown"}`);
  if (!input.resultBundlePresent) reasons.push("no result bundle: the workbench made no commits");
  const facts = parseIntakeFacts(input.facts, input.taskId);
  if (!facts) reasons.push("intake facts missing or malformed");
  else if (facts.resultBundleVersionId === null) reasons.push("intake facts pin no result bundle");
  return reasons.length ? { path: "reject", reasons } : { path: "review", reasons: [] };
}
