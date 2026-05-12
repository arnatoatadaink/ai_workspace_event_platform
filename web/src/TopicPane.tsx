import { useEffect, useState } from "react";
import { fetchActiveTopics, type ActiveTopicItem } from "./api";

interface Props {
  sessionId: string | null;
}

const TREND_LABEL: Record<string, string> = {
  new: "NEW",
  rising: "↑",
  stable: "─",
  falling: "↓",
};

const TREND_CLASS: Record<string, string> = {
  new: "trend-new",
  rising: "trend-rising",
  stable: "trend-stable",
  falling: "trend-falling",
};

export function TopicPane({ sessionId }: Props) {
  const [topics, setTopics] = useState<ActiveTopicItem[]>([]);
  const [windowInfo, setWindowInfo] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!sessionId) {
      setTopics([]);
      setWindowInfo(null);
      return;
    }
    fetchActiveTopics(sessionId)
      .then((res) => {
        setTopics(res.active_topics);
        setWindowInfo(`直近 ${res.window.conversations} 会話`);
      })
      .catch((e: unknown) => setError(String(e)));
  }, [sessionId]);

  if (!sessionId)
    return <div className="pane pane-placeholder">セッションを選択してください</div>;
  if (error) return <div className="pane pane-error">{error}</div>;

  const maxWeight = topics[0]?.weight ?? 1;

  return (
    <div className="pane">
      <h2 className="pane-title">
        アクティブtopic
        {windowInfo && <span className="pane-title-sub">{windowInfo}</span>}
      </h2>
      <ul className="topic-list">
        {topics.map((t) => (
          <li key={t.topic} className="topic-item">
            <span className="topic-name">{t.topic}</span>
            <div className="topic-bar-wrap">
              <div
                className="topic-bar"
                style={{ width: `${(t.weight / maxWeight) * 100}%` }}
              />
            </div>
            <span className={`topic-trend ${TREND_CLASS[t.trend] ?? ""}`}>
              {TREND_LABEL[t.trend] ?? t.trend}
            </span>
            <span className="topic-score">{t.weight.toFixed(2)}</span>
          </li>
        ))}
        {topics.length === 0 && (
          <li className="topic-empty">トピックなし</li>
        )}
      </ul>
    </div>
  );
}
