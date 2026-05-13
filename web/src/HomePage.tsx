import { useEffect, useRef, useState } from "react";
import {
  analyzeSession,
  checkPluginUpdate,
  fetchHealth,
  fetchPlugins,
  fetchScannedSessions,
  fetchSessionStats,
  ingestSession,
  summarizeSession,
  type CheckUpdateResponse,
  type PluginEntry,
  type ScannedSession,
  type SessionInfo,
  type SessionStats,
} from "./api";

const STATUS_LABEL: Record<string, string> = {
  active: "稼働中",
  available: "未設定",
  coming_soon: "近日公開",
  update_available: "更新あり",
};

const STATUS_DOT: Record<string, string> = {
  active: "dot-green",
  available: "dot-yellow",
  coming_soon: "dot-gray",
  update_available: "dot-blue",
};

type SessionStatus =
  | "未取込"
  | "取込中"
  | "取込済"
  | "分析中"
  | "分析済"
  | "要約中"
  | "要約済";

const SESSION_STATUS_CLASS: Record<SessionStatus, string> = {
  未取込: "status-not-ingested",
  取込中: "status-ingesting",
  取込済: "status-ingested",
  分析中: "status-analyzing",
  分析済: "status-analyzed",
  要約中: "status-summarizing",
  要約済: "status-summarized",
};

function getSessionStatus(
  isIngested: boolean,
  stats: SessionStats | null | undefined,
): SessionStatus {
  if (!isIngested) return "未取込";
  if (!stats) return "取込中";
  const {
    conversation_count,
    summarized_count,
    has_pending_transcript,
    has_unanalyzed_events,
  } = stats;
  if (has_pending_transcript) return "取込中";
  if (conversation_count === 0) return "取込済";
  // Trailing unanalyzed events haven't formed a conversation record yet;
  // evaluate summary progress first so those events don't downgrade the status.
  if (summarized_count === conversation_count) return "要約済";
  if (summarized_count > 0) return "要約中";
  if (has_unanalyzed_events) return "分析中";
  return "分析済";
}

interface Props {
  onOpenSession: (sessionId: string) => void;
  sessions: SessionInfo[];
  onSessionsRefresh: () => void;
}

export function HomePage({ onOpenSession, sessions, onSessionsRefresh }: Props) {
  const [plugins, setPlugins] = useState<PluginEntry[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [checking, setChecking] = useState<string | null>(null);
  const [updateResults, setUpdateResults] = useState<
    Record<string, CheckUpdateResponse>
  >({});
  const [apiOnline, setApiOnline] = useState<boolean | null>(null);
  const [scannedSessions, setScannedSessions] = useState<ScannedSession[]>([]);
  const [sessionStats, setSessionStats] = useState<Record<string, SessionStats>>({});
  const [actionLoading, setActionLoading] = useState<Record<string, string>>({});
  const ingestedIds = new Set(sessions.map((s) => s.session_id));
  const statsLoadedRef = useRef<Set<string>>(new Set());

  const loadStats = async (sessionId: string) => {
    if (!ingestedIds.has(sessionId)) return;
    try {
      const stats = await fetchSessionStats(sessionId);
      setSessionStats((prev) => ({ ...prev, [sessionId]: stats }));
    } catch {
      // stats stay undefined; status shown as 取込中
    }
  };

  useEffect(() => {
    fetchPlugins()
      .then(setPlugins)
      .catch((e: unknown) => setError(String(e)));
    fetchHealth().then(setApiOnline);
    fetchScannedSessions()
      .then(setScannedSessions)
      .catch(() => setScannedSessions([]));
  }, []);

  // Load stats for ingested sessions after scannedSessions or sessions change
  useEffect(() => {
    for (const s of scannedSessions) {
      if (ingestedIds.has(s.session_id) && !statsLoadedRef.current.has(s.session_id)) {
        statsLoadedRef.current.add(s.session_id);
        void loadStats(s.session_id);
      }
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scannedSessions, sessions]);

  async function handleCheckUpdate(name: string) {
    setChecking(name);
    try {
      const result = await checkPluginUpdate(name);
      setUpdateResults((prev) => ({ ...prev, [name]: result }));
    } catch (e) {
      setError(String(e));
    } finally {
      setChecking(null);
    }
  }

  async function handleRefresh(sessionId: string) {
    setActionLoading((prev) => ({ ...prev, [sessionId]: "refreshing" }));
    try {
      const updated = await fetchScannedSessions();
      setScannedSessions(updated);
      const stats = await fetchSessionStats(sessionId);
      setSessionStats((prev) => ({ ...prev, [sessionId]: stats }));
    } catch {
      // ignore
    } finally {
      setActionLoading((prev) => { const n = { ...prev }; delete n[sessionId]; return n; });
    }
  }

  async function handleIngest(sessionId: string) {
    setActionLoading((prev) => ({ ...prev, [sessionId]: "ingesting" }));
    try {
      await ingestSession(sessionId);
      onSessionsRefresh();
      const stats = await fetchSessionStats(sessionId);
      setSessionStats((prev) => ({ ...prev, [sessionId]: stats }));
    } catch (e) {
      setError(String(e));
    } finally {
      setActionLoading((prev) => { const n = { ...prev }; delete n[sessionId]; return n; });
    }
  }

  async function handleAnalyze(sessionId: string) {
    setActionLoading((prev) => ({ ...prev, [sessionId]: "analyzing" }));
    try {
      await analyzeSession(sessionId);
      const stats = await fetchSessionStats(sessionId);
      setSessionStats((prev) => ({ ...prev, [sessionId]: stats }));
    } catch (e) {
      setError(String(e));
    } finally {
      setActionLoading((prev) => { const n = { ...prev }; delete n[sessionId]; return n; });
    }
  }

  async function handleSummarize(sessionId: string) {
    setActionLoading((prev) => ({ ...prev, [sessionId]: "summarizing" }));
    try {
      await summarizeSession(sessionId);
      const stats = await fetchSessionStats(sessionId);
      setSessionStats((prev) => ({ ...prev, [sessionId]: stats }));
    } catch (e) {
      setError(String(e));
    } finally {
      setActionLoading((prev) => { const n = { ...prev }; delete n[sessionId]; return n; });
    }
  }

  const sourceSessions = sessions.reduce<Record<string, SessionInfo[]>>(
    (acc, s) => {
      const src = (s as SessionInfo & { source?: string }).source ?? "claude_cli";
      if (!acc[src]) acc[src] = [];
      acc[src].push(s);
      return acc;
    },
    {},
  );

  return (
    <div className="home-page">
      {error && <div className="home-error">{error}</div>}

      {/* API接続ステータス */}
      <section className="home-section home-section-status">
        <h2 className="home-section-title">API接続ステータス</h2>
        <div className="connection-status">
          <span
            className={`dot ${
              apiOnline === null
                ? "dot-gray"
                : apiOnline
                  ? "dot-green"
                  : "dot-red"
            }`}
          />
          <span className="connection-url">http://localhost:8001</span>
          <span className="connection-label">
            {apiOnline === null
              ? "確認中…"
              : apiOnline
                ? "接続中"
                : "接続不可"}
          </span>
          {apiOnline && (
            <span className="connection-hook-hint">
              Hook設定済 — Stop / PreToolUse / PostToolUse
            </span>
          )}
        </div>
      </section>

      {/* 接続ソース */}
      <section className="home-section">
        <h2 className="home-section-title">接続ソース</h2>
        <div className="source-cards">
          {plugins
            .filter(
              (p) =>
                p.status === "active" || p.status === "update_available",
            )
            .map((p) => {
              const srcSessions = sourceSessions[p.source_name] ?? [];
              const latest = srcSessions.sort(
                (a, b) =>
                  new Date(b.last_event_at).getTime() -
                  new Date(a.last_event_at).getTime(),
              )[0];
              return (
                <div key={p.source_name} className="source-card">
                  <div className="source-card-header">
                    <span className={`dot ${STATUS_DOT[p.status]}`} />
                    <span className="source-name">{p.source_name}</span>
                    <span className="source-status-label">
                      {STATUS_LABEL[p.status]}
                    </span>
                  </div>
                  <p className="source-desc">{p.description}</p>
                  <div className="source-stats">
                    <span>{srcSessions.length} セッション</span>
                    {latest && (
                      <span>
                        最終:{" "}
                        {new Date(latest.last_event_at).toLocaleString("ja-JP")}
                      </span>
                    )}
                  </div>
                </div>
              );
            })}
          {plugins.filter((p) => p.status === "coming_soon").length > 0 && (
            <div className="source-card source-card-coming">
              <p className="source-coming-label">
                {plugins.filter((p) => p.status === "coming_soon").length}{" "}
                個のアダプターが近日公開予定
              </p>
              <p className="source-coming-hint">
                プラグイン管理から確認できます
              </p>
            </div>
          )}
        </div>
      </section>

      {/* プラグイン管理 */}
      <section className="home-section">
        <h2 className="home-section-title">プラグイン管理</h2>
        <table className="plugin-table">
          <thead>
            <tr>
              <th>名前</th>
              <th>説明</th>
              <th>状態</th>
              <th>バージョン</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {plugins.map((p) => {
              const upd = updateResults[p.name];
              return (
                <tr
                  key={p.name}
                  className={`plugin-row plugin-row-${p.status}`}
                >
                  <td className="plugin-name">{p.name}</td>
                  <td className="plugin-desc">{p.description}</td>
                  <td>
                    <span className={`status-badge status-${p.status}`}>
                      {STATUS_LABEL[p.status]}
                    </span>
                  </td>
                  <td className="plugin-ver">
                    {p.installed_version ?? "─"}
                    {upd && upd.update_available && (
                      <span className="ver-new"> → {upd.latest_version}</span>
                    )}
                    {upd && !upd.update_available && (
                      <span className="ver-ok"> ✓</span>
                    )}
                  </td>
                  <td className="plugin-actions">
                    {(p.status === "active" ||
                      p.status === "update_available") && (
                      <button
                        className="btn-ghost"
                        disabled={checking === p.name}
                        onClick={() => handleCheckUpdate(p.name)}
                      >
                        {checking === p.name ? "確認中…" : "更新確認"}
                      </button>
                    )}
                    {p.status === "coming_soon" && (
                      <span className="coming-soon-tag">近日公開</span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </section>

      {/* Claude CLIセッション（ログから） */}
      <section className="home-section">
        <h2 className="home-section-title">
          Claude CLI セッション（ログから）
          <span className="section-badge">{scannedSessions.length}</span>
        </h2>
        <table className="session-table">
          <thead>
            <tr>
              <th>セッションID</th>
              <th>メッセージ数</th>
              <th>最終更新</th>
              <th>状態</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {scannedSessions.map((s) => {
              const isIngested = ingestedIds.has(s.session_id);
              const stats = sessionStats[s.session_id];
              const status = getSessionStatus(isIngested, stats);
              const loading = actionLoading[s.session_id];
              const showIngest = status === "未取込" || status === "取込中";
              const showAnalyze = isIngested && !!stats && stats.has_unanalyzed_events;
              const showSummarize =
                isIngested &&
                !!stats &&
                stats.conversation_count > 0 &&
                stats.summarized_count < stats.conversation_count;
              return (
                <tr key={s.session_id} className="session-table-row">
                  <td className="session-table-id">
                    <code>{s.session_id.slice(0, 8)}…</code>
                  </td>
                  <td>{s.message_count}</td>
                  <td>
                    {s.last_message_at
                      ? new Date(s.last_message_at).toLocaleString("ja-JP")
                      : "─"}
                  </td>
                  <td>
                    <span className={`status-badge ${SESSION_STATUS_CLASS[status]}`}>
                      {status}
                    </span>
                    {stats && (
                      <span className="session-conv-count">
                        {stats.summarized_count}/{stats.conversation_count}
                      </span>
                    )}
                  </td>
                  <td className="session-actions">
                    <button
                      className="btn-ghost"
                      disabled={!!loading}
                      onClick={() => void handleRefresh(s.session_id)}
                      title="新規会話を確認"
                    >
                      {loading === "refreshing" ? "確認中…" : "更新"}
                    </button>
                    {showIngest && (
                      <button
                        className="btn-ghost"
                        disabled={!!loading}
                        onClick={() => void handleIngest(s.session_id)}
                        title="未取込の会話をイベントストアに取り込む"
                      >
                        {loading === "ingesting" ? "取込中…" : "取込"}
                      </button>
                    )}
                    {showAnalyze && (
                      <button
                        className="btn-ghost"
                        disabled={!!loading}
                        onClick={() => void handleAnalyze(s.session_id)}
                        title="取込済のデータを会話単位に分析する"
                      >
                        {loading === "analyzing" ? "分析中…" : "分析"}
                      </button>
                    )}
                    {showSummarize && (
                      <button
                        className="btn-ghost"
                        disabled={!!loading}
                        onClick={() => void handleSummarize(s.session_id)}
                        title="未要約の会話を要約する"
                      >
                        {loading === "summarizing" ? "要約中…" : "要約"}
                      </button>
                    )}
                  </td>
                </tr>
              );
            })}
            {scannedSessions.length === 0 && (
              <tr>
                <td colSpan={5} className="table-empty">
                  セッションが見つかりません
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </section>

      {/* 最近のセッション */}
      <section className="home-section">
        <h2 className="home-section-title">最近のセッション</h2>
        <table className="session-table">
          <thead>
            <tr>
              <th>セッションID</th>
              <th>イベント数</th>
              <th>最終更新</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {sessions.slice(0, 10).map((s) => (
              <tr key={s.session_id} className="session-table-row">
                <td className="session-table-id">
                  <code>{s.session_id}</code>
                </td>
                <td>{s.event_count}</td>
                <td>
                  {new Date(s.last_event_at).toLocaleString("ja-JP")}
                </td>
                <td>
                  <button
                    className="btn-ghost"
                    onClick={() => onOpenSession(s.session_id)}
                  >
                    詳細を見る
                  </button>
                </td>
              </tr>
            ))}
            {sessions.length === 0 && (
              <tr>
                <td colSpan={4} className="table-empty">
                  セッションなし
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </section>
    </div>
  );
}
