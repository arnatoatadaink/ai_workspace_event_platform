import { useEffect, useRef, useState } from "react";
import Plot from "react-plotly.js";
import {
  fetchUmap,
  fetchSessions,
  type PlotlyFigure,
  type SessionInfo,
  type UmapColorBy,
} from "./api";

export function UmapPage() {
  const [sessions, setSessions] = useState<SessionInfo[]>([]);
  const [sessionId, setSessionId] = useState<string>("");
  const [colorBy, setColorBy] = useState<UmapColorBy>("session");
  const [since, setSince] = useState("");
  const [until, setUntil] = useState("");
  const [figure, setFigure] = useState<PlotlyFigure | null>(null);
  const [pointCount, setPointCount] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    fetchSessions().then(setSessions).catch(console.error);
  }, []);

  async function generate() {
    abortRef.current?.abort();
    abortRef.current = new AbortController();
    setLoading(true);
    setError(null);
    try {
      const res = await fetchUmap({
        sessionId: sessionId || undefined,
        since: since || undefined,
        until: until || undefined,
        colorBy,
      });
      setFigure(res.figure);
      setPointCount(res.point_count);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="umap-page">
      <h2 className="umap-title">Topic Map (UMAP)</h2>

      <div className="umap-controls">
        <label>
          セッション
          <select
            value={sessionId}
            onChange={(e) => setSessionId(e.target.value)}
          >
            <option value="">全セッション</option>
            {sessions.map((s) => (
              <option key={s.session_id} value={s.session_id}>
                {s.session_id.slice(0, 16)}…
              </option>
            ))}
          </select>
        </label>

        <label>
          色分け軸
          <select
            value={colorBy}
            onChange={(e) => setColorBy(e.target.value as UmapColorBy)}
          >
            <option value="session">セッション別</option>
            <option value="time">月別</option>
          </select>
        </label>

        <label>
          開始日時
          <input
            type="datetime-local"
            value={since}
            onChange={(e) => setSince(e.target.value)}
          />
        </label>

        <label>
          終了日時
          <input
            type="datetime-local"
            value={until}
            onChange={(e) => setUntil(e.target.value)}
          />
        </label>

        <button className="nav-btn" onClick={generate} disabled={loading}>
          {loading ? "生成中…" : "生成"}
        </button>
      </div>

      {error && <p className="umap-error">{error}</p>}

      {figure && (
        <>
          <p className="umap-meta">
            {pointCount} ポイント — 色分け: {colorBy === "session" ? "セッション別" : "月別"}
          </p>
          <div className="umap-plot-wrapper">
            <Plot
              data={figure.data as Plotly.Data[]}
              layout={{
                ...(figure.layout as Partial<Plotly.Layout>),
                autosize: true,
              }}
              useResizeHandler
              style={{ width: "100%", height: "100%" }}
              config={{ displayModeBar: true, responsive: true }}
            />
          </div>
        </>
      )}

      {!figure && !loading && (
        <p className="umap-hint">「生成」ボタンを押してトピックマップを作成してください。</p>
      )}
    </div>
  );
}
