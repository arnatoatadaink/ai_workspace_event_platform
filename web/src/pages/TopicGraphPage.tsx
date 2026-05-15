import { useCallback, useEffect, useMemo, useState } from "react";
import type { JSX } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  Handle,
  MiniMap,
  Position,
  type Edge,
  type Node,
  type NodeProps,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

const BASE = "http://localhost:8001";

// ─── API types ─────────────────────────────────────────────────────────────

type RawTopicNode = {
  id: string;
  label: string;
  count: number;
  session_count: number;
  x: number;
  y: number;
};

type RawTopicEdge = {
  source: string;
  target: string;
  shared_sessions: number;
};

type TopicGraphResponse = {
  nodes: RawTopicNode[];
  edges: RawTopicEdge[];
  total_nodes: number;
  total_edges: number;
};

async function fetchTopicGraph(
  minTopicCount: number,
  minSharedSessions: number,
): Promise<TopicGraphResponse> {
  const params = new URLSearchParams({
    min_topic_count: String(minTopicCount),
    min_shared_sessions: String(minSharedSessions),
  });
  const res = await fetch(`${BASE}/topic-graph?${params}`);
  if (!res.ok) throw new Error(`GET /topic-graph: ${res.status}`);
  return res.json() as Promise<TopicGraphResponse>;
}

// ─── Custom node ───────────────────────────────────────────────────────────

type TopicNodeData = {
  label: string;
  count: number;
  session_count: number;
  selected: boolean;
} & Record<string, unknown>;

type TopicFlowNode = Node<TopicNodeData, "topic">;

// Size range for nodes: maps count to diameter in px.
const MIN_SIZE = 32;
const MAX_SIZE = 80;

function computeSize(count: number, maxCount: number): number {
  if (maxCount <= 0) return MIN_SIZE;
  const ratio = Math.sqrt(count / maxCount);
  return MIN_SIZE + ratio * (MAX_SIZE - MIN_SIZE);
}

// Colour interpolated from cool-blue (single session) to warm-orange (many sessions).
const SESSION_COLORS = [
  "#4f86c6", // 1 session
  "#5fa85f", // 2
  "#b088d0", // 3
  "#f0a060", // 4
  "#e05050", // 5+
];
function sessionColor(sessionCount: number): string {
  const idx = Math.min(sessionCount - 1, SESSION_COLORS.length - 1);
  return SESSION_COLORS[Math.max(0, idx)];
}

function TopicNode({ data }: NodeProps<TopicFlowNode>): JSX.Element {
  const { label, count, session_count, selected } = data;
  const size = data._size as number;
  const bg = sessionColor(session_count);

  return (
    <>
      {/* Both handle types at center so undirected edges connect from any side */}
      <Handle
        type="target"
        position={Position.Top}
        style={{ opacity: 0, pointerEvents: "none" }}
      />
      <div
        style={{
          width: size,
          height: size,
          borderRadius: "50%",
          background: bg,
          border: selected
            ? "2.5px solid #ffffff"
            : "1.5px solid rgba(255,255,255,0.25)",
          boxShadow: selected ? "0 0 12px rgba(255,255,255,0.6)" : undefined,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          fontSize: Math.max(9, Math.min(13, size * 0.18)),
          fontWeight: 600,
          color: "#fff",
          textAlign: "center",
          padding: "2px 4px",
          lineHeight: 1.2,
          wordBreak: "break-word",
          overflow: "hidden",
          cursor: "pointer",
          transition: "border 0.15s, box-shadow 0.15s",
        }}
        title={`${label}\n出現: ${count}回 / ${session_count}セッション`}
      >
        {label.length > 14 ? `${label.slice(0, 13)}…` : label}
      </div>
      <Handle
        type="source"
        position={Position.Bottom}
        style={{ opacity: 0, pointerEvents: "none" }}
      />
    </>
  );
}

const nodeTypes = { topic: TopicNode };

// ─── Main page ─────────────────────────────────────────────────────────────

export function TopicGraphPage(): JSX.Element {
  const [data, setData] = useState<TopicGraphResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [minTopicCount, setMinTopicCount] = useState(2);
  const [minSharedSessions, setMinSharedSessions] = useState(1);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    setSelectedId(null);
    fetchTopicGraph(minTopicCount, minSharedSessions)
      .then(setData)
      .catch((e: unknown) => setError(String(e)))
      .finally(() => setLoading(false));
  }, [minTopicCount, minSharedSessions]);

  // Load on first mount
  useEffect(() => {
    load();
  }, []); // analyze-ignore: empty-deps

  const maxCount = useMemo(
    () => Math.max(1, ...(data?.nodes.map((n) => n.count) ?? [1])),
    [data],
  );

  const nodes: TopicFlowNode[] = useMemo(() => {
    if (!data) return [];
    return data.nodes.map((n) => ({
      id: n.id,
      type: "topic" as const,
      position: { x: n.x, y: n.y },
      data: {
        label: n.label,
        count: n.count,
        session_count: n.session_count,
        selected: n.id === selectedId,
        _size: computeSize(n.count, maxCount),
      },
      // Disable default ReactFlow drag-to-reposition while using UMAP layout
      draggable: true,
    }));
  }, [data, maxCount, selectedId]);

  const edges: Edge[] = useMemo(() => {
    if (!data) return [];
    return data.edges.map((e, i) => ({
      id: `e${i}`,
      source: e.source,
      target: e.target,
      label: e.shared_sessions > 1 ? String(e.shared_sessions) : undefined,
      style: {
        stroke: "rgba(180,180,200,0.45)",
        strokeWidth: Math.min(3, e.shared_sessions),
      },
      animated: false,
      type: "straight",
    }));
  }, [data]);

  function handleNodeClick(_: React.MouseEvent, node: Node): void {
    setSelectedId((prev) => (prev === node.id ? null : node.id));
  }

  function handlePaneClick(): void {
    setSelectedId(null);
  }

  const selectedNode = data?.nodes.find((n) => n.id === selectedId);

  return (
    <div className="topic-graph-page">
      <div className="topic-graph-controls">
        <label className="tg-param">
          最小出現数
          <input
            type="number"
            min={1}
            max={50}
            value={minTopicCount}
            onChange={(e: React.ChangeEvent<HTMLInputElement>) =>
              setMinTopicCount(Number(e.target.value))
            }
          />
        </label>
        <label className="tg-param">
          最小共有セッション数
          <input
            type="number"
            min={1}
            max={20}
            value={minSharedSessions}
            onChange={(e: React.ChangeEvent<HTMLInputElement>) =>
              setMinSharedSessions(Number(e.target.value))
            }
          />
        </label>
        <button className="tg-reload-btn" onClick={load} disabled={loading}>
          {loading ? "生成中…" : "グラフ更新"}
        </button>
        {data && (
          <span className="tg-stats">
            {data.total_nodes} ノード / {data.total_edges} エッジ
          </span>
        )}
        <span className="tg-hint">
          ノードクリックで詳細表示 / 背景クリックで解除
        </span>
      </div>

      {error && <div className="pane-error">エラー: {error}</div>}

      {!loading && data?.total_nodes === 0 && (
        <div className="pane-loading">
          表示できるトピックがありません。セッションを取込・要約してから再実行してください。
        </div>
      )}

      {data && data.total_nodes > 0 && (
        <div className="topic-graph-canvas">
          <ReactFlow
            nodes={nodes}
            edges={edges}
            nodeTypes={nodeTypes}
            onNodeClick={handleNodeClick}
            onPaneClick={handlePaneClick}
            fitView
            fitViewOptions={{ padding: 0.1 }}
            minZoom={0.2}
            maxZoom={3}
            nodesConnectable={false}
            nodesDraggable={true}
          >
            <Background color="rgba(255,255,255,0.04)" gap={40} />
            <Controls />
            <MiniMap
              nodeColor={(n) => {
                const d = n.data as TopicNodeData;
                return sessionColor(d.session_count ?? 1);
              }}
              maskColor="rgba(0,0,0,0.6)"
            />
          </ReactFlow>

          {selectedNode && (
            <div className="tg-detail-panel">
              <div className="tg-detail-title">{selectedNode.label}</div>
              <table className="tg-detail-table">
                <tbody>
                  <tr>
                    <th>出現回数</th>
                    <td>{selectedNode.count}</td>
                  </tr>
                  <tr>
                    <th>セッション数</th>
                    <td>{selectedNode.session_count}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      <div className="tg-legend">
        <span>ノード色 — セッション数:</span>
        {[1, 2, 3, 4, "5+"].map((n, i) => (
          <span key={i} className="tg-legend-item">
            <span
              className="tg-legend-dot"
              style={{ background: SESSION_COLORS[Math.min(i, SESSION_COLORS.length - 1)] }}
            />
            {n}
          </span>
        ))}
        <span style={{ marginLeft: 16 }}>ノードサイズ = 出現頻度</span>
        <span style={{ marginLeft: 16 }}>エッジ太さ = 共有セッション数</span>
      </div>
    </div>
  );
}
