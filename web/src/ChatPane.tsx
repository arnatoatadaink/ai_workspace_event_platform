import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { fetchEvents, type EventItem } from "./api";

const PAGE_SIZE = 50;
const lsCountKey = (id: string) => `awep:chat:displayCount:${id}`;
const lsScrollKey = (id: string) => `awep:chat:scrollTop:${id}`;

interface ChatMessage {
  event_id: string;
  timestamp: string;
  role: "user" | "assistant";
  content: string;
}

function toMessage(ev: EventItem): ChatMessage | null {
  if (ev.event_type !== "message") return null;
  if (ev.role !== "user" && ev.role !== "assistant") return null;
  if (typeof ev.content !== "string") return null;
  return {
    event_id: ev.event_id,
    timestamp: ev.timestamp,
    role: ev.role as "user" | "assistant",
    content: ev.content as string,
  };
}

interface Props {
  sessionId: string | null;
  onToggleSidebar: () => void;
  sidebarOpen: boolean;
}

export function ChatPane({ sessionId, onToggleSidebar, sidebarOpen }: Props) {
  const [allMessages, setAllMessages] = useState<ChatMessage[]>([]);
  const [displayCount, setDisplayCount] = useState(PAGE_SIZE);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const containerRef = useRef<HTMLDivElement>(null);
  const sentinelRef = useRef<HTMLDivElement>(null);
  const prevScrollHeight = useRef(0);
  const didInitialScroll = useRef(false);

  useEffect(() => {
    if (!sessionId) {
      setAllMessages([]);
      setDisplayCount(PAGE_SIZE);
      setError(null);
      return;
    }

    didInitialScroll.current = false;
    setLoading(true);
    setError(null);
    setAllMessages([]);

    const saved = localStorage.getItem(lsCountKey(sessionId));
    setDisplayCount(saved ? Math.max(PAGE_SIZE, parseInt(saved, 10)) : PAGE_SIZE);

    fetchEvents(sessionId, 1000, 0)
      .then((page) => {
        const msgs = page.items
          .map(toMessage)
          .filter((m): m is ChatMessage => m !== null);
        setAllMessages(msgs);
      })
      .catch((e: unknown) => setError(String(e)))
      .finally(() => setLoading(false));
  }, [sessionId]);

  // Scroll to bottom (or restore) after first load of a session
  useLayoutEffect(() => {
    if (didInitialScroll.current || allMessages.length === 0 || !containerRef.current) return;
    didInitialScroll.current = true;
    const saved = sessionId ? localStorage.getItem(lsScrollKey(sessionId)) : null;
    if (saved !== null) {
      containerRef.current.scrollTop = parseInt(saved, 10);
    } else {
      containerRef.current.scrollTop = containerRef.current.scrollHeight;
    }
  }, [allMessages, sessionId]);

  // Maintain scroll position when older messages are prepended
  useLayoutEffect(() => {
    if (!containerRef.current || prevScrollHeight.current === 0) return;
    containerRef.current.scrollTop +=
      containerRef.current.scrollHeight - prevScrollHeight.current;
    prevScrollHeight.current = 0;
  }, [displayCount]);

  // Save displayCount to localStorage whenever it changes
  useEffect(() => {
    if (sessionId) localStorage.setItem(lsCountKey(sessionId), String(displayCount));
  }, [sessionId, displayCount]);

  // IntersectionObserver: load older messages when sentinel enters viewport
  useEffect(() => {
    const sentinel = sentinelRef.current;
    const container = containerRef.current;
    if (!sentinel || !container) return;

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (!entry.isIntersecting || loading) return;
        setDisplayCount((prev) => {
          if (prev >= allMessages.length) return prev;
          prevScrollHeight.current = container.scrollHeight;
          return Math.min(prev + PAGE_SIZE, allMessages.length);
        });
      },
      { root: container, threshold: 0.1 },
    );
    observer.observe(sentinel);
    return () => observer.disconnect();
  }, [loading, allMessages.length]);

  function handleScroll() {
    if (sessionId && containerRef.current) {
      localStorage.setItem(lsScrollKey(sessionId), String(containerRef.current.scrollTop));
    }
  }

  const hasMore = displayCount < allMessages.length;
  const displayed = allMessages.slice(Math.max(0, allMessages.length - displayCount));

  return (
    <div className="chat-pane">
      <div className="chat-header">
        <span className="chat-header-title">チャット</span>
        <button className="chat-sidebar-toggle" onClick={onToggleSidebar}>
          {sidebarOpen ? "Detail ▶" : "◀ Detail"}
        </button>
      </div>

      {error && <div className="chat-error">{error}</div>}

      {!sessionId ? (
        <div className="chat-placeholder">セッションを選択してください</div>
      ) : (
        <div className="chat-messages" ref={containerRef} onScroll={handleScroll}>
          {hasMore && (
            <div ref={sentinelRef} className="chat-sentinel">
              ↑ 過去のメッセージ
            </div>
          )}

          {!loading && allMessages.length === 0 && (
            <div className="chat-empty-state">
              <p className="chat-empty-title">メッセージがありません</p>
              <p className="chat-empty-hint">
                ホームタブで「取込」→「分析」を実行するとメッセージが表示されます。
              </p>
            </div>
          )}

          {displayed.map((msg) => (
            <div key={msg.event_id} className={`chat-bubble chat-bubble--${msg.role}`}>
              <div className="chat-bubble-meta">
                <span className="chat-bubble-role">
                  {msg.role === "user" ? "You" : "AI"}
                </span>
                <span className="chat-bubble-time">
                  {new Date(msg.timestamp).toLocaleTimeString("ja-JP")}
                </span>
              </div>
              <div className="chat-bubble-content">{msg.content}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
