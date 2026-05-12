/**
 * React hook that logs component lifecycle events in dev mode.
 * The entire module is excluded from prod bundles via the conditional import
 * pattern shown below — do NOT import this file at the top level.
 *
 * Usage (inside a component):
 *   useEffect(() => {
 *     if (import.meta.env.DEV) {
 *       import("./debug/useRuntimeLogger").then(({ useRuntimeLogger }) => {
 *         // hook rules require calling at top level; use the standalone `log`
 *         // helper from logger.ts for deferred scenarios.
 *       });
 *     }
 *   }, []);
 *
 * Preferred pattern — call at the top of a component in DEV-only wrapper:
 *   // DevWrapper.tsx (only imported in dev entry)
 *   import { useRuntimeLogger } from "./debug/useRuntimeLogger";
 *   export function DevWrapper({ name, children }: { name: string; children: ReactNode }) {
 *     useRuntimeLogger(name);
 *     return <>{children}</>;
 *   }
 */
import { useEffect, useRef } from "react";
import { log, flush, type Lifecycle } from "./logger";

interface Options {
  /** Arbitrary key/value to attach to every event from this component. */
  data?: Record<string, unknown>;
  sessionId?: string;
}

function emit(component: string, lifecycle: Lifecycle, opts: Options): void {
  log({ component, lifecycle, data: opts.data, sessionId: opts.sessionId });
}

/**
 * Logs mount, unmount, and re-render counts for `componentName`.
 * Call unconditionally at the top of your component (obeys Rules of Hooks).
 * Tree-shaken in production when the parent module is not imported.
 */
export function useRuntimeLogger(componentName: string, opts: Options = {}): void {
  const renderCount = useRef(0);
  renderCount.current += 1;

  useEffect(() => {
    emit(componentName, "mount", opts);
    return () => {
      emit(componentName, "unmount", opts);
      flush();
    };
    // intentionally omitting opts from deps: stable reference assumed
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [componentName]);

  useEffect(() => {
    if (renderCount.current > 1) {
      emit(componentName, "render", {
        ...opts,
        data: { ...opts.data, renderCount: renderCount.current },
      });
    }
  });
}
