// High-risk path patterns. scripts/intake/trusted-run.sh carries the same four expressions
// (POSIX ERE, matched case-insensitively) so the trusted runner and the router agree; the
// router also recomputes them here from changedPaths and takes the union, so a drift between
// the two copies can only add risk, never remove it.

export const RISK_PATTERNS = {
  /**
   * CI definitions, code owners and git hooks: anything that runs with repo secrets or gates
   * merges. Directories match as entries as well as by contents (`(/|$)`), so a change that
   * replaces `.github` itself, with a symlink say, is caught. All of `.github/` counts.
   */
  touchesCi:
    "(^|/)(\\.github|\\.github/(workflows|actions)|\\.gitlab|\\.circleci|\\.buildkite|\\.azure-pipelines|\\.husky|\\.devcontainer)(/|$)" +
    "|(^|/)(\\.gitlab-ci\\.yml|jenkinsfile[^/]*|azure-pipelines[^/]*\\.ya?ml|buildspec[^/]*\\.ya?ml|\\.travis\\.yml" +
    "|bitbucket-pipelines\\.yml|\\.drone\\.yml|cloudbuild\\.ya?ml|codeowners|dependabot\\.yml|\\.pre-commit-config\\.yaml|\\.gitattributes)$",
  /** Files that steer every later agent session; directories match as entries as well. */
  touchesInstructions:
    "(^|/)(claude(\\.local)?\\.md|agents\\.md|gemini\\.md|\\.mcp\\.json|\\.cursorrules|\\.windsurfrules|copilot-instructions\\.md)$" +
    "|(^|/)(\\.claude|\\.cursor|\\.github/instructions|\\.github/prompts)(/|$)",
  /** Package manifests, lockfiles, toolchain pins and container bases: the supply chain. */
  touchesManifests:
    "(^|/)(package\\.json|package-lock\\.json|npm-shrinkwrap\\.json|yarn\\.lock|pnpm-lock\\.yaml|pnpm-workspace\\.yaml" +
    "|\\.npmrc|\\.yarnrc(\\.yml)?|requirements[^/]*\\.(txt|in)|constraints[^/]*\\.txt|pipfile(\\.lock)?|pyproject\\.toml" +
    "|poetry\\.lock|uv\\.lock|setup\\.(py|cfg)|pip\\.conf|go\\.(mod|sum|work)|cargo\\.(toml|lock)|gemfile(\\.lock)?" +
    "|[^/]*\\.gemspec|pom\\.xml|build\\.gradle(\\.kts)?|settings\\.gradle(\\.kts)?|gradle\\.lockfile" +
    "|gradle-wrapper\\.properties|libs\\.versions\\.toml|composer\\.(json|lock)|[^/]*\\.csproj|packages\\.config" +
    "|packages\\.lock\\.json|directory\\.(packages|build)\\.props|nuget\\.config|mix\\.(exs|lock)|package\\.(swift|resolved)" +
    "|podfile(\\.lock)?|pubspec\\.(yaml|lock)|dockerfile[^/]*|[^/]*\\.dockerfile|\\.gitmodules|\\.tool-versions|\\.nvmrc" +
    "|\\.python-version|rust-toolchain(\\.toml)?)$",
  /** Authentication, authorization, cryptography, secrets and their configuration. */
  touchesSecurityPaths:
    "(^|[/._-])(auth[a-z]*|security|crypto[a-z]*|oauth[a-z0-9]*|saml|sso|iam|rbac|acl|permissions?|passwords?|secrets?" +
    "|credentials?|jwt|sessions?|login|signin|csrf|cors|tls|ssl|certs?|certificates?|keystore|sanitiz[a-z]*)([/._-]|$)" +
    "|(^|/)\\.env(\\.[^/]*)?$|\\.(pem|key|p12|pfx|jks)$",
} as const;

export type RiskFlag = keyof typeof RISK_PATTERNS;
export const RISK_FLAGS = Object.keys(RISK_PATTERNS) as RiskFlag[];

const COMPILED: Record<RiskFlag, RegExp> = Object.fromEntries(
  RISK_FLAGS.map((flag) => [flag, new RegExp(RISK_PATTERNS[flag], "i")]),
) as Record<RiskFlag, RegExp>;

export type RiskFlags = Record<RiskFlag, boolean>;

/** Which high-risk categories a set of changed paths touches, and the paths behind each. */
export function classifyPaths(paths: readonly string[]): { flags: RiskFlags; hits: Record<RiskFlag, string[]> } {
  const hits = Object.fromEntries(RISK_FLAGS.map((f) => [f, [] as string[]])) as Record<RiskFlag, string[]>;
  for (const raw of paths) {
    const p = raw.replace(/\\/g, "/");
    for (const flag of RISK_FLAGS) if (COMPILED[flag].test(p)) hits[flag].push(raw);
  }
  const flags = Object.fromEntries(RISK_FLAGS.map((f) => [f, hits[f].length > 0])) as RiskFlags;
  return { flags, hits };
}
