const BASE = "http://localhost:8001";

export interface SessionInfo {
  session_id: string;
  event_count: number;
  started_at: string;
  last_event_at: string;
}

export interface EventItem {
  event_id: string;
  session_id: string;
  event_type: string;
  source: string;
  timestamp: string;
  schema_version: string;
  [key: string]: unknown;
}

export interface EventPage {
  items: EventItem[];
  total: number;
  offset: number;
  limit: number;
}

export interface ConversationItem {
  conversation_id: string;
  session_id: string;
  created_at: string;
  message_count: number;
  event_index_start: number;
  event_index_end: number;
  summary_short: string | null;
  topics: string[] | null;
  is_pending: boolean;
}

export interface ConversationPage {
  items: ConversationItem[];
  next_cursor: string | null;
}

export interface ActiveTopicItem {
  topic: string;
  weight: number;
  trend: string;
}

export interface ActiveTopicsResponse {
  active_topics: ActiveTopicItem[];
  window: {
    conversations: number;
    from_: string | null;
    to: string | null;
  };
}

export type PluginStatus = "active" | "available" | "coming_soon" | "update_available";

export interface PluginEntry {
  name: string;
  source_name: string;
  description: string;
  status: PluginStatus;
  installed_version: string | null;
  latest_version: string;
  install_command: string | null;
}

export interface CheckUpdateResponse {
  name: string;
  installed_version: string | null;
  latest_version: string;
  update_available: boolean;
}

export async function fetchSessions(): Promise<SessionInfo[]> {
  const res = await fetch(`${BASE}/sessions`);
  if (!res.ok) throw new Error(`GET /sessions: ${res.status}`);
  return res.json();
}

export async function fetchEvents(
  sessionId: string,
  limit = 50,
  offset = 0,
): Promise<EventPage> {
  const params = new URLSearchParams({
    session_id: sessionId,
    limit: String(limit),
    offset: String(offset),
  });
  const res = await fetch(`${BASE}/events?${params}`);
  if (!res.ok) throw new Error(`GET /events: ${res.status}`);
  return res.json();
}

export async function fetchConversations(
  sessionId: string,
  cursor?: string,
  limit = 20,
): Promise<ConversationPage> {
  const params = new URLSearchParams({ limit: String(limit) });
  if (cursor) params.set("before_conversation_id", cursor);
  const res = await fetch(`${BASE}/sessions/${sessionId}/conversations?${params}`);
  if (!res.ok) throw new Error(`GET /sessions/${sessionId}/conversations: ${res.status}`);
  const items: ConversationItem[] = await res.json();
  const next_cursor =
    items.length === limit ? items[items.length - 1].conversation_id : null;
  return { items, next_cursor };
}

export async function fetchActiveTopics(
  sessionId: string,
): Promise<ActiveTopicsResponse> {
  const res = await fetch(`${BASE}/sessions/${sessionId}/topics/active`);
  if (!res.ok) throw new Error(`GET /sessions/${sessionId}/topics/active: ${res.status}`);
  return res.json();
}

export async function fetchPlugins(): Promise<PluginEntry[]> {
  const res = await fetch(`${BASE}/plugins`);
  if (!res.ok) throw new Error(`GET /plugins: ${res.status}`);
  return res.json();
}

export async function checkPluginUpdate(name: string): Promise<CheckUpdateResponse> {
  const res = await fetch(`${BASE}/plugins/${name}/check-update`, { method: "POST" });
  if (!res.ok) throw new Error(`POST /plugins/${name}/check-update: ${res.status}`);
  return res.json();
}

export async function fetchHealth(): Promise<boolean> {
  try {
    const res = await fetch(`${BASE}/health`, { signal: AbortSignal.timeout(3000) });
    return res.ok;
  } catch {
    return false;
  }
}

export interface ScannedSession {
  session_id: string;
  message_count: number;
  first_message_at: string | null;
  last_message_at: string | null;
  file_size_bytes: number;
}

export interface SessionStats {
  session_id: string;
  conversation_count: number;
  summarized_count: number;
  has_pending_transcript: boolean;
  has_unanalyzed_events: boolean;
}

export interface AnalyzeResponse {
  session_id: string;
  conversations_created: number;
}

export interface SessionSummarizeResponse {
  session_id: string;
  processed: number;
  skipped: number;
  failed: string[];
}

export interface IngestResponse {
  session_id: string;
  ingested_count: number;
  conversations_indexed: number;
}

export interface PlotlyTrace {
  type: string;
  mode: string;
  name: string;
  x: number[];
  y: number[];
  text: string[];
  [key: string]: unknown;
}

export interface PlotlyFigure {
  data: PlotlyTrace[];
  layout: Record<string, unknown>;
}

export interface UmapResponse {
  figure: PlotlyFigure;
  point_count: number;
  color_by: string;
}

export type UmapColorBy = "session" | "time";

export async function fetchUmap(opts?: {
  sessionId?: string;
  since?: string;
  until?: string;
  colorBy?: UmapColorBy;
}): Promise<UmapResponse> {
  const params = new URLSearchParams();
  if (opts?.sessionId) params.set("session_id", opts.sessionId);
  if (opts?.since) params.set("since", opts.since);
  if (opts?.until) params.set("until", opts.until);
  if (opts?.colorBy) params.set("color_by", opts.colorBy);
  const query = params.size > 0 ? `?${params}` : "";
  const res = await fetch(`${BASE}/umap${query}`);
  if (!res.ok) throw new Error(`GET /umap: ${res.status}`);
  return res.json();
}

export async function fetchScannedSessions(scanDir?: string): Promise<ScannedSession[]> {
  const params = new URLSearchParams();
  if (scanDir) params.set("scan_dir", scanDir);
  const query = params.size > 0 ? `?${params}` : "";
  const res = await fetch(`${BASE}/claude/scan-sessions${query}`);
  if (!res.ok) throw new Error(`GET /claude/scan-sessions: ${res.status}`);
  return res.json();
}

export async function fetchSessionStats(sessionId: string): Promise<SessionStats> {
  const res = await fetch(`${BASE}/sessions/${sessionId}/stats`);
  if (!res.ok) throw new Error(`GET /sessions/${sessionId}/stats: ${res.status}`);
  return res.json();
}

export async function ingestSession(sessionId: string): Promise<IngestResponse> {
  const res = await fetch(`${BASE}/sessions/${sessionId}/ingest`, { method: "POST" });
  if (!res.ok) throw new Error(`POST /sessions/${sessionId}/ingest: ${res.status}`);
  return res.json();
}

export async function summarizeSession(sessionId: string): Promise<SessionSummarizeResponse> {
  const res = await fetch(`${BASE}/sessions/${sessionId}/summarize`, { method: "POST" });
  if (!res.ok) throw new Error(`POST /sessions/${sessionId}/summarize: ${res.status}`);
  return res.json();
}

export async function analyzeSession(sessionId: string): Promise<AnalyzeResponse> {
  const res = await fetch(`${BASE}/sessions/${sessionId}/analyze`, { method: "POST" });
  if (!res.ok) throw new Error(`POST /sessions/${sessionId}/analyze: ${res.status}`);
  return res.json();
}

export type BackendKind = "openai_compat" | "claude";

export interface SummarizerSettingsResponse {
  backend: BackendKind;
  base_url: string;
  api_key_masked: string;
  model: string;
}

export interface SummarizerSettingsPut {
  backend?: BackendKind;
  base_url?: string;
  api_key?: string;
  model?: string;
}

export interface TestConnectionRequest {
  backend: BackendKind;
  base_url: string;
  api_key: string;
  model: string;
}

export interface TestConnectionResponse {
  ok: boolean;
  model_used: string;
  latency_ms: number;
  error?: string;
}

export async function fetchSummarizerSettings(): Promise<SummarizerSettingsResponse> {
  const res = await fetch(`${BASE}/settings/summarizer`);
  if (!res.ok) throw new Error(`GET /settings/summarizer: ${res.status}`);
  return res.json();
}

export async function putSummarizerSettings(
  body: SummarizerSettingsPut,
): Promise<SummarizerSettingsResponse> {
  const res = await fetch(`${BASE}/settings/summarizer`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(detail.detail ?? `PUT /settings/summarizer: ${res.status}`);
  }
  return res.json();
}

export async function testSummarizerConnection(
  body: TestConnectionRequest,
): Promise<TestConnectionResponse> {
  const res = await fetch(`${BASE}/settings/summarizer/test`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`POST /settings/summarizer/test: ${res.status}`);
  return res.json();
}

export interface SummarizeOneResponse {
  conversation_id: string;
  summary_short: string;
  summary_long: string;
  topics: string[];
  model_used: string;
  was_cached: boolean;
}

export async function summarizeConversation(
  conversationId: string,
): Promise<SummarizeOneResponse> {
  const res = await fetch(`${BASE}/conversations/${conversationId}/summarize`, {
    method: "POST",
  });
  if (!res.ok) throw new Error(`POST /conversations/${conversationId}/summarize: ${res.status}`);
  return res.json();
}
