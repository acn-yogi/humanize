// Risk flags for the facts file, from the router's own patterns (risk.ts), so facts.json says
// what the router will conclude. A reviewer flagged the first runs, whose facts left every flag
// false for the router to recompute.
//
//   echo '["pyproject.toml"]' | node harness/lib/flags.ts
import * as fs from "node:fs";
import { classifyPaths } from "./risk.ts";

const paths = JSON.parse(fs.readFileSync(0, "utf8"));
console.log(JSON.stringify(classifyPaths(Array.isArray(paths) ? paths : []).flags));
