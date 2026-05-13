import { useEffect, useState } from "react";
import type { JSX } from "react";
import { FlowGraph } from "../components/dataflow/FlowGraph";
import type { DataFlowIR, NodeKind } from "../components/dataflow/types";

const BASE = "http://localhost:8001";

async function fetchIR(): Promise<DataFlowIR> {
  const res = await fetch(`${BASE}/dataflow/ir`);
  if (!res.ok) throw new Error(`GET /dataflow/ir: ${res.status}`);
  return res.json() as Promise<DataFlowIR>;
}

const ALL_KINDS: NodeKind[] = [
  "component",
  "hook",
  "fetch_call",
  "route",
  "function",
  "pydantic",
  "table",
];

const KIND_LABELS: Record<NodeKind, string> = {
  component: "コンポーネント",
  hook: "フック",
  fetch_call: "Fetch",
  route: "APIルート",
  function: "Python関数",
  pydantic: "Pydanticモデル",
  table: "DBテーブル",
};

export function DataFlowPage(): JSX.Element {
  const [ir, setIr] = useState<DataFlowIR | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [visibleKinds, setVisibleKinds] = useState<Set<NodeKind>>(
    new Set(ALL_KINDS),
  );

  useEffect(() => {
    // one-time fetch on mount — dependencies intentionally empty
    fetchIR()
      .then(setIr)
      .catch((e: unknown) => setError(String(e)))
      .finally(() => setLoading(false));
  }, []); // analyze-ignore: empty-deps

  function toggleKind(kind: NodeKind): void {
    setVisibleKinds((prev) => {
      const next = new Set(prev);
      if (next.has(kind)) {
        next.delete(kind);
      } else {
        next.add(kind);
      }
      return next;
    });
  }

  if (loading) return <div className="pane-loading">静的解析中...</div>;
  if (error) return <div className="pane-error">エラー: {error}</div>;
  if (!ir) return <div className="pane-loading">データなし</div>;

  const filteredNodes = ir.nodes.filter((n) => visibleKinds.has(n.kind));
  const filteredNodeIds = new Set(filteredNodes.map((n) => n.id));
  const filteredEdges = ir.edges.filter(
    (e) => filteredNodeIds.has(e.source) && filteredNodeIds.has(e.target),
  );

  return (
    <div className="dataflow-page">
      <div className="dataflow-controls">
        <span className="dataflow-controls-label">表示レイヤー：</span>
        {ALL_KINDS.map((kind) => (
          <label key={kind} className="dataflow-kind-toggle">
            <input
              type="checkbox"
              checked={visibleKinds.has(kind)}
              onChange={() => toggleKind(kind)}
            />
            {KIND_LABELS[kind]}
          </label>
        ))}
        <span className="dataflow-stats">
          {filteredNodes.length} ノード / {filteredEdges.length} エッジ
        </span>
        <span className="dataflow-hint">ノードをクリック → フローをハイライト（再クリック / 背景クリックで解除）</span>
      </div>
      <div className="dataflow-graph">
        <FlowGraph nodes={filteredNodes} edges={filteredEdges} />
      </div>
    </div>
  );
}
