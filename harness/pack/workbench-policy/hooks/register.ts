import type { EngineInterface, Register } from "claude-code";

// Workbench policy mod. Best effort by design: a hook that fails is skipped, so the controls
// that must hold live in managed settings, the sandbox and the microVM. This mod adds a
// reasoned refusal on top, which the evidence mod records for the packet.

/** The worktree in a workbench, and in the microVM behind the host driver. */
const WORK = "/work";

/**
 * Where file tools may reach. In a workbench (and with the host driver) the session starts in
 * /work; in a local run (CONTRACTS.md "Local mode") it starts in the task's worktree, beside
 * the task's claude-config folder. Taken from where the session started, which a shell cd does
 * not move, never from an environment variable a repository's settings could set.
 */
interface Layout {
  /** File tools may read and write only below it. */
  work: string;
  /** Claude Code's own per-session files (large tool output it reads back). Read only. */
  ownRead: string[];
}

let known: Promise<Layout> | undefined;
function layout($: EngineInterface): Promise<Layout> {
  known ??= $.session.root().then((root) => {
    const work = root.replace(/\/+$/, "");
    if (!work.startsWith("/") || work === "") throw new Error("the session root is not an absolute folder");
    if (work === WORK) return { work, ownRead: ["/home/workbench/.claude/projects"] };
    const parent = work.slice(0, work.lastIndexOf("/")) || "/";
    return { work, ownRead: [`${parent === "/" ? "" : parent}/claude-config/projects`] };
  });
  // A failed lookup is asked again next time; meanwhile the call is refused (the catch below).
  known.catch(() => (known = undefined));
  return known;
}

/** Tools a workbench never uses: no web access, no MCP, no Windows shell. */
const DENIED_TOOLS = new Set(["WebFetch", "WebSearch", "PowerShell", "RemoteTrigger"]);
const DENIED_PREFIXES = ["mcp__"];

/**
 * Host driver (CONTRACTS.md, "Host driver"): the bridge's tools, which run in the microVM.
 * Each maps to its path field; bash has none. Every other mcp__ tool stays denied.
 */
const BRIDGE_PREFIX = "mcp__workbench__";
const BRIDGE_PATH_FIELD: Record<string, string | null> = {
  bash: null,
  read: "file_path",
  write: "file_path",
  edit: "file_path",
  glob: "path",
  grep: "path",
};
const BRIDGE_READ_ONLY = new Set(["read", "glob", "grep"]);
/** read, glob and grep may also reach the home folder: the judge's subject, the improver's export. */
const BRIDGE_READ_ROOT = "/home/workbench";

/** Tools whose input names a path, and the field that holds it. */
const PATH_FIELD: Record<string, string> = {
  Read: "file_path",
  Write: "file_path",
  Edit: "file_path",
  MultiEdit: "file_path",
  NotebookEdit: "notebook_path",
  Glob: "path",
  Grep: "path",
};
const READ_ONLY = new Set(["Read", "Glob", "Grep"]);

const isUnder = (path: string, root: string) => path === root || path.startsWith(root + "/");

/** True when any segment of the path is ".git" (any case): the folder or a gitfile. */
function hasGitSegment(path: string): boolean {
  return path.split(/[\\/]+/).some((segment) => segment.toLowerCase() === ".git");
}

export const register: Register = (on) => {
  on("tool.call", async ($, e, next) => {
    const tool = String(e.tool);

    if (tool.startsWith(BRIDGE_PREFIX)) {
      const refusal = bridgeRefusal(tool, e as unknown as Record<string, unknown>);
      return refusal === undefined ? next(e) : { deny: refusal };
    }

    if (DENIED_TOOLS.has(tool) || DENIED_PREFIXES.some((p) => tool.startsWith(p))) {
      return { deny: `workbench-policy: ${tool} is not available in a workbench.` };
    }

    const field = PATH_FIELD[tool];
    if (field === undefined) return next(e);

    const raw = (e as unknown as Record<string, unknown>)[field];
    // Glob and Grep without a path search the working directory, which is the worktree.
    if (raw === undefined || raw === "") return next(e);
    if (typeof raw !== "string") return { deny: `workbench-policy: ${tool} named no usable path.` };

    const { work, ownRead } = await layout($);
    // Resolve links and "..": an allow-list on the real path is the robust form. A path
    // that does not exist yet (Write) is placed by its nearest existing folder.
    const real = await placed($, raw, work);
    // Git metadata belongs to workbench-init, which does every commit: no file tool touches it,
    // by the name written or by where it lands.
    if (hasGitSegment(raw) || (real !== undefined && hasGitSegment(real))) {
      return { deny: `workbench-policy: ${tool} may not touch .git; the workbench commits the worktree itself.` };
    }
    const roots = READ_ONLY.has(tool) ? [work, ...ownRead] : [work];
    if (real !== undefined && roots.some((root) => isUnder(real, root))) return next(e);
    return { deny: `workbench-policy: ${tool} may only touch files under ${work}; ${raw} is outside it.` };
  }).catch(($, e) => ({ deny: `workbench-policy: the policy check for ${String(e.tool)} failed, so the call is refused.` }));
};

/**
 * Why a bridge tool call is refused, or undefined when it may run. Its paths are microVM
 * paths, not paths on the machine this hook runs on, so they are checked by name only and
 * $.fs is never asked; the exec agent repeats the rules on real paths inside the microVM.
 */
function bridgeRefusal(tool: string, input: Record<string, unknown>): string | undefined {
  const name = tool.slice(BRIDGE_PREFIX.length);
  if (!Object.hasOwn(BRIDGE_PATH_FIELD, name)) return `workbench-policy: ${tool} is not available in a workbench.`;
  const field = BRIDGE_PATH_FIELD[name];
  if (field === null) return undefined;
  const raw = input[field];
  // glob and grep without a path search /work.
  if ((raw === undefined || raw === "") && field === "path") return undefined;
  if (typeof raw !== "string" || raw === "") return `workbench-policy: ${tool} named no usable path.`;
  if (hasGitSegment(raw)) return `workbench-policy: ${tool} may not touch .git; the workbench commits the worktree itself.`;
  if (raw.split(/[\\/]+/).includes("..")) return `workbench-policy: ${tool} may not use .. in a path; name the file from /work.`;
  // Relative paths are under /work, where the exec agent places them too.
  const absolute = raw.startsWith("/") ? raw : `${WORK}/${raw}`;
  const normal = "/" + absolute.split("/").filter((s) => s !== "" && s !== ".").join("/");
  const roots = BRIDGE_READ_ONLY.has(name) ? [WORK, BRIDGE_READ_ROOT] : [WORK];
  if (roots.some((root) => isUnder(normal, root))) return undefined;
  return `workbench-policy: ${tool} may only touch files under ${roots.join(" or ")}; ${raw} is outside.`;
}

/**
 * Where a path lands once links and ".." are resolved, or undefined when it cannot be
 * placed. A file not there yet (a Write into new folders) is placed by its nearest
 * existing ancestor plus the remaining names, none of which may be "." or "..".
 */
async function placed($: EngineInterface, path: string, work: string): Promise<string | undefined> {
  if (!path.startsWith("/")) path = `${work}/${path}`;
  const rest: string[] = [];
  let current = path.replace(/\/+$/, "") || "/";
  for (;;) {
    const stat = await $.fs.stat(current, { resolve: true }).catch(() => undefined);
    if (stat?.realPath !== undefined) {
      return [stat.realPath.replace(/\/$/, ""), ...rest].join("/") || "/";
    }
    if (current === "/") return undefined;
    const cut = current.lastIndexOf("/");
    const name = current.slice(cut + 1);
    if (name === "" || name === "." || name === "..") return undefined;
    rest.unshift(name);
    current = current.slice(0, cut) || "/";
  }
}
