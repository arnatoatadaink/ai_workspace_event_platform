import { useEffect, useRef, useState } from "react";
import { fetchEvents, type EventItem } from "./api";

interface Props {
  sessionId: string | null;
}

const EVENT_LABEL: Record<string, string> = {
  message: "メッセージ",
  tool_call: "ツール呼び出し",
  tool_result: "ツール結果",
  stop: "停止",
  approval_required: "承認要求",
  summary_update: "要約更新",
  topic_extraction: "トピック抽出",
  state_update: "状態更新",
};

const BASE_FIELDS = new Set([
  "event_id", "session_id", "event_type", "source", "timestamp", "schema_version",
]);

function eventPayload(ev: Record<string, unknown>): Record<string, unknown> {
  return Object.fromEntries(
    Object.entries(ev).filter(([k]) => !BASE_FIELDS.has(k)),
  );
}

export function MessageDetail({ sessionId }: Props) {
  const [events, setEvents] = useState<EventItem[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!sessionId) {
      setEvents([]);
      return;
    }
    setLoading(true);
    fetchEvents(sessionId, 100, 0)
      .then((page) => setEvents(page.items))
      .catch((e: unknown) => setError(String(e)))
      .finally(() => setLoading(false));
  }, [sessionId]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [events]);

  if (!sessionId)
    return <div className="pane pane-placeholder">セッションを選択してください</div>;
  if (error) return <div className="pane pane-error">{error}</div>;

  return (
    <div className="pane">
      <h2 className="pane-title">メッセージ詳細</h2>
      {loading && <div className="pane-loading">読み込み中…</div>}
      <div className="event-list">
        {events.map((ev) => {
          const payload = eventPayload(ev as Record<string, unknown>);
          const payloadStr = JSON.stringify(payload, null, 2);
          return (
            <div key={ev.event_id} className={`event-row event-type-${ev.event_type}`}>
              <span className="event-type-badge">
                {EVENT_LABEL[ev.event_type] ?? ev.event_type}
              </span>
              <span className="event-time">
                {new Date(ev.timestamp).toLocaleTimeString("ja-JP")}
              </span>
              {payloadStr !== "{}" && (
                <pre className="event-payload">{payloadStr}</pre>
              )}
            </div>
          );
        })}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}
