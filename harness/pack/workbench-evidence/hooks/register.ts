import type { EngineInterface, Register } from "claude-code";

// Workbench evidence mod. Each conversation row (session.append) and each tool call result
// (tool.call) becomes one JSON line under /var/workbench/evidence (in a local run, the evidence
// folder beside the task's worktree; CONTRACTS.md "Local mode"); workbench-init folds the lines
// into packet.json after Claude Code exits. The packet is untrusted input downstream: the
// router computes its facts from the diff and the gateway log, never from this record.
// Best effort: a failed write is dropped and the call goes on unchanged.

/**
 * Where the lines go, from where the session started (a shell cd does not move it):
 * /var/workbench/evidence for /work (a workbench, or the host driver), else the evidence folder
 * beside the worktree.
 */
let dir: Promise<string> | undefined;
function evidenceDir($: EngineInterface): Promise<string> {
  dir ??= $.session.root().then((root) => {
    const work = root.replace(/\/+$/, "");
    if (work === "/work") return "/var/workbench/evidence";
    if (!work.startsWith("/")) throw new Error("the session root is not an absolute folder");
    return `${work.slice(0, work.lastIndexOf("/"))}/evidence`;
  });
  dir.catch(() => (dir = undefined));
  return dir;
}
/** Lines per file. $.fs.write replaces a whole file, so files are kept short. */
const LINES_PER_FILE = 200;
/** Longest text kept from any one field. */
const MAX_TEXT = 2000;

let file = 0;
let lines: string[] = [];
let seq = 0;
// Writes run one at a time, in the order the events came.
let queue: Promise<unknown> = Promise.resolve();

function clip(text: string): string {
  return text.length > MAX_TEXT ? `${text.slice(0, MAX_TEXT)}[cut ${text.length - MAX_TEXT}]` : text;
}

/** Appends one line to the current file and rewrites that file; never rejects. */
function record($: EngineInterface, entry: Record<string, unknown>): Promise<unknown> {
  lines.push(JSON.stringify({ seq: seq++, at: new Date().toISOString(), ...entry }));
  const name = `${String(file).padStart(6, "0")}.jsonl`;
  const text = lines.join("\n") + "\n";
  if (lines.length >= LINES_PER_FILE) {
    file += 1;
    lines = [];
  }
  queue = queue.then(async () => $.fs.write(`${await evidenceDir($)}/${name}`, text)).catch(() => undefined);
  return queue;
}

type Block = { type: string; text?: unknown; name?: unknown; is_error?: unknown };

export const register: Register = (on) => {
  on("session.append", async ($, e, next) => {
    const stored = await next(e);
    const blocks: Block[] = Array.isArray(e.message.content) ? (e.message.content as Block[]) : [];
    await record($, {
      event: "session.append",
      uuid: stored.uuid ?? e.uuid,
      agentId: e.agentId,
      door: e.door,
      origin: e.origin.kind,
      tool: e.origin.kind === "tool" ? e.origin.tool : undefined,
      type: e.message.type,
      role: e.message.role,
      blocks: blocks.map((b) => ({
        type: b.type,
        text: typeof b.text === "string" ? clip(b.text) : undefined,
        name: typeof b.name === "string" ? b.name : undefined,
        isError: b.is_error === true ? true : undefined,
      })),
    });
    return stored;
  });

  on("tool.call", async ($, e, next) => {
    const result = await next(e);
    const input = e as unknown as Record<string, unknown>;
    await record($, {
      event: "tool.call",
      tool: String(e.tool),
      toolUseId: e.tool_use_id,
      agentId: e.agentId,
      command: typeof input.command === "string" ? clip(input.command) : undefined,
      path:
        typeof input.file_path === "string" ? input.file_path : typeof input.path === "string" ? input.path : undefined,
      denied: result.deny !== undefined ? clip(result.deny) : undefined,
      isError: result.isError === true ? true : undefined,
      text: typeof result.text === "string" ? clip(result.text) : undefined,
    });
    return result;
  });
};
