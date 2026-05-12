/**
 * CLI entry point for the React/TS static analysis pipeline.
 * Mirrors the role of src/analysis/checker.py.
 *
 * Usage:
 *   pnpm analyze           # scans web/src (default)
 *   pnpm analyze web/src   # explicit path
 */
import path from "node:path";
import { fileURLToPath } from "node:url";
import { extractFromProject } from "./ast-extractor.ts";
import { detectHookViolations } from "./hook-checker.ts";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

function main(): void {
  const rawTarget = process.argv[2];
  const srcDir = rawTarget
    ? path.resolve(rawTarget)
    : path.resolve(__dirname, "../../src");

  console.log(`Scanning: ${srcDir}\n`);

  const { components, hookCalls } = extractFromProject(srcDir);
  const violations = detectHookViolations(hookCalls);

  console.log(
    `Found ${components.length} component(s), ${hookCalls.length} hook call(s).`
  );

  if (violations.length === 0) {
    console.log("No hook violations detected.");
    process.exit(0);
  }

  console.error(`\n${violations.length} violation(s) detected:\n`);
  for (const v of violations) {
    const rel = path.relative(process.cwd(), v.file);
    console.error(`  [${v.kind}] ${rel}:${v.line}`);
    console.error(`    ${v.message}\n`);
  }
  process.exit(1);
}

main();
