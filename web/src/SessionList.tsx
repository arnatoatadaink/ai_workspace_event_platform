import { useEffect, useState } from "react";
import { fetchSessions, type SessionInfo } from "./api";

interface Props {
  selectedId: string | null;
  onSelect: (id: string) => void;
}

export function SessionList({ selectedId, onSelect }: Props) {
  const [sessions, setSessions] = useState<SessionInfo[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchSessions()
      .then(setSessions)
      .catch((e: unknown) => setError(String(e)));
  }, []);

  if (error) return <div className="pane-error">{error}</div>;

  return (
    <div className="pane">
      <h2 className="pane-title">セッション一覧</h2>
      <ul className="session-list">
        {sessions.map((s) => (
          <li
            key={s.session_id}
            className={`session-item${s.session_id === selectedId ? " selected" : ""}`}
            onClick={() => onSelect(s.session_id)}
          >
            <span className="session-id">{s.session_id.slice(0, 12)}…</span>
            <span className="session-meta">{s.event_count} events</span>
            <span className="session-date">
              {new Date(s.last_event_at).toLocaleString("ja-JP")}
            </span>
          </li>
        ))}
        {sessions.length === 0 && (
          <li className="session-empty">セッションなし</li>
        )}
      </ul>
    </div>
  );
}
