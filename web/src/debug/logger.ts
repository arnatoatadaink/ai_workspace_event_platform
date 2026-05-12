/**
 * Dev-only runtime logger for React components.
 * Emits FrontendDebugEvent payloads to the backend /ingest endpoint.
 *
 * Import pattern — always guard the *import* so the module is tree-shaken in prod:
 *   if (import.meta.env.DEV) {
 *     const { log } = await import("./debug/logger");
 *     log(...);
 *   }
 */

export type Lifecycle =
  | "mount"
  | "unmount"
  | "render"
  | "state-change"
  | "effect"
  | "error";

export interface DebugPayload {
  component: string;
  lifecycle: Lifecycle;
  data?: Record<string, unknown>;
  sessionId?: string;
}

interface IngestBody {
  event_type: "frontend_debug";
  source: "frontend";
  session_id: string;
  component: string;
  lifecycle: string;
  data: Record<string, unknown>;
}

const INGEST_URL = "/api/ingest";
const DEFAULT_SESSION = "frontend-debug";

// Micro-batch: flush every 2 s or when buffer hits 20 events
const FLUSH_INTERVAL_MS = 2000;
const FLUSH_BATCH_SIZE = 20;

let _buffer: IngestBody[] = [];
let _timer: ReturnType<typeof setTimeout> | null = null;

function _schedule(): void {
  if (_timer !== null) return;
  _timer = setTimeout(() => {
    _timer = null;
    _flush();
  }, FLUSH_INTERVAL_MS);
}

function _flush(): void {
  if (_buffer.length === 0) return;
  const batch = _buffer.splice(0, _buffer.length);
  // fire-and-forget; errors are surfaced to console only in dev
  void Promise.all(
    batch.map((body) =>
      fetch(INGEST_URL, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
        // keepalive lets the request survive page unload (unmount events)
        keepalive: true,
      }).catch((err: unknown) => {
        console.warn("[RuntimeLogger] ingest failed", err);
      })
    )
  );
}

/** Enqueue a debug event. No-op when bundled in production (dead code). */
export function log(payload: DebugPayload): void {
  const body: IngestBody = {
    event_type: "frontend_debug",
    source: "frontend",
    session_id: payload.sessionId ?? DEFAULT_SESSION,
    component: payload.component,
    lifecycle: payload.lifecycle,
    data: payload.data ?? {},
  };
  _buffer.push(body);
  if (_buffer.length >= FLUSH_BATCH_SIZE) {
    _flush();
  } else {
    _schedule();
  }
}

/** Flush remaining buffered events immediately (call on app teardown). */
export function flush(): void {
  if (_timer !== null) {
    clearTimeout(_timer);
    _timer = null;
  }
  _flush();
}
