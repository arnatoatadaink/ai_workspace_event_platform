/**
 * React-specific static checks that tsc cannot perform:
 *   1. Rules of Hooks: hook called conditionally or inside a loop
 *   2. Empty dependency array on useEffect/useCallback/useMemo (potential stale closure)
 *
 * Mirrors the role of src/analysis/type_mismatch.py for the frontend.
 */
import type { HookCallInfo } from "./ast-extractor.ts";

export type ViolationKind =
  | "conditional-hook"   // hook inside if/loop/switch
  | "empty-deps-array";  // [] dep array — may hide stale closures

export interface HookViolation {
  kind: ViolationKind;
  hookName: string;
  callerName: string;
  file: string;
  line: number;
  message: string;
}

const DEPS_HOOKS = new Set(["useEffect", "useCallback", "useMemo", "useLayoutEffect"]);

export function detectHookViolations(hookCalls: HookCallInfo[]): HookViolation[] {
  const violations: HookViolation[] = [];

  for (const call of hookCalls) {
    if (call.isConditional) {
      violations.push({
        kind: "conditional-hook",
        hookName: call.hookName,
        callerName: call.callerName,
        file: call.file,
        line: call.line,
        message: `${call.hookName} is called inside a conditional/loop in "${call.callerName}". ` +
          "Hooks must be called at the top level (Rules of Hooks).",
      });
    }

    if (
      DEPS_HOOKS.has(call.hookName) &&
      call.depsArrayText !== null &&
      call.depsArrayText.trim() === "[]"
    ) {
      violations.push({
        kind: "empty-deps-array",
        hookName: call.hookName,
        callerName: call.callerName,
        file: call.file,
        line: call.line,
        message: `${call.hookName} in "${call.callerName}" has an empty dependency array []. ` +
          "Verify that the callback truly has no dependencies to avoid stale closures.",
      });
    }
  }

  return violations;
}
