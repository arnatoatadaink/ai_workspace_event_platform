import { useEffect, useState } from "react";
import { fetchConversations, type ConversationItem } from "./api";

interface Props {
  sessionId: string | null;
}

export function ConversationPane({ sessionId }: Props) {
  const [conversations, setConversations] = useState<ConversationItem[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [cursor, setCursor] = useState<string | null>(null);
  const [hasMore, setHasMore] = useState(false);

  useEffect(() => {
    if (!sessionId) {
      setConversations([]);
      setCursor(null);
      return;
    }
    fetchConversations(sessionId)
      .then((page) => {
        setConversations(page.items);
        setCursor(page.next_cursor);
        setHasMore(page.next_cursor !== null);
      })
      .catch((e: unknown) => setError(String(e)));
  }, [sessionId]);

  function loadMore() {
    if (!sessionId || !cursor) return;
    fetchConversations(sessionId, cursor)
      .then((page) => {
        setConversations((prev) => [...prev, ...page.items]);
        setCursor(page.next_cursor);
        setHasMore(page.next_cursor !== null);
      })
      .catch((e: unknown) => setError(String(e)));
  }

  if (!sessionId)
    return <div className="pane pane-placeholder">セッションを選択してください</div>;
  if (error) return <div className="pane pane-error">{error}</div>;

  return (
    <div className="pane">
      <h2 className="pane-title">会話・要約</h2>
      <ul className="conv-list">
        {conversations.map((c) => (
          <li key={c.conversation_id} className={`conv-item${c.is_pending ? " conv-item-pending" : ""}`}>
            <div className="conv-time">
              {new Date(c.created_at).toLocaleString("ja-JP")}
              {c.is_pending
                ? <span className="conv-badge conv-badge-pending">進行中</span>
                : <span className="conv-meta">{c.message_count} イベント</span>
              }
            </div>
            {c.is_pending && (
              <p className="conv-pending-note">{c.message_count} イベント（未完了・STOPなし）</p>
            )}
            {c.summary_short && <p className="conv-summary">{c.summary_short}</p>}
            {c.topics && c.topics.length > 0 && (
              <div className="conv-topics">
                {c.topics.map((t) => (
                  <span key={t} className="conv-topic-tag">{t}</span>
                ))}
              </div>
            )}
          </li>
        ))}
        {conversations.length === 0 && (
          <li className="conv-empty">会話なし</li>
        )}
      </ul>
      {hasMore && (
        <button className="load-more-btn" onClick={loadMore}>
          さらに読み込む
        </button>
      )}
    </div>
  );
}
