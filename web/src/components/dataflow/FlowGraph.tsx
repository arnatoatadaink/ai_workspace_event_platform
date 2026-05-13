import React, { useMemo, useState } from "react";
import type { JSX } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  Handle,
  Position,
  type Node,
  type Edge,
  type NodeProps,
} from "@xyflow/react";
import { graphlib, layout } from "@dagrejs/dagre";
import "@xyflow/react/dist/style.css";
import type { IREdge, IRNode, NodeKind } from "./types";

// ─── constants ────────────────────────────────────────────────────────────────

const NODE_W = 168;
const NODE_H = 48;

const NODE_COLORS: Record<NodeKind, string> = {
  component: "#4f86c6",
  hook: "#6baed6",
  fetch_call: "#a6d4fa",
  route: "#f0a060",
  function: "#9a9a9a",
  pydantic: "#b088d0",
  table: "#5fa85f",
};

const KIND_LABELS: Record<NodeKind, string> = {
  component: "Component",
  hook: "Hook",
  fetch_call: "Fetch",
  route: "Route",
  function: "Function",
  pydantic: "Pydantic",
  table: "Table",
};

// ─── types ────────────────────────────────────────────────────────────────────

type HighlightState = "selected" | "path" | "dimmed" | "normal";

type FlowNodeData = {
  label: string;
  kind: NodeKind;
  highlightState: HighlightState;
} & Record<string, unknown>;

type FlowNode = Node<FlowNodeData, "custom">;

// ─── custom node ──────────────────────────────────────────────────────────────

function CustomNode({ data }: NodeProps<FlowNode>): JSX.Element {
  const baseColor = NODE_COLORS[data.kind] ?? "#9a9a9a";
  const hs = data.highlightState;

  let border = "1px solid rgba(0,0,0,0.25)";
  let opacity = 1;
  let boxShadow: string | undefined = undefined;

  if (hs === "selected") {
    border = "2.5px solid #ffffff";
    boxShadow = "0 0 12px rgba(255,255,255,0.55)";
  } else if (hs === "path") {
    border = "1.5px solid rgba(255,255,255,0.5)";
  } else if (hs === "dimmed") {
    opacity = 0.18;
  }

  return (
    <div
      style={{
        background: baseColor,
        border,
        borderRadius: 6,
        padding: "4px 10px",
        fontSize: 11,
        fontFamily: "monospace",
        width: NODE_W,
        boxSizing: "border-box",
        color: "#1a1a2e",
        overflow: "hidden",
        opacity,
        boxShadow,
        transition: "opacity 0.15s, box-shadow 0.15s",
        cursor: "pointer",
      }}
    >
      <Handle type="target" position={Position.Left} style={{ background: "rgba(0,0,0,0.3)" }} />
      <div style={{ fontSize: 9, opacity: 0.65, textTransform: "uppercase", marginBottom: 1 }}>
        {KIND_LABELS[data.kind] ?? data.kind}
      </div>
      <div
        title={data.label}
        style={{
          fontWeight: 600,
          whiteSpace: "nowrap",
          overflow: "hidden",
          textOverflow: "ellipsis",
        }}
      >
        {data.label}
      </div>
      <Handle type="source" position={Position.Right} style={{ background: "rgba(0,0,0,0.3)" }} />
    </div>
  );
}

const nodeTypes = { custom: CustomNode };

// ─── dagre layout (positions only, recomputed only when IR changes) ────────────

type BaseLayout = {
  positions: Map<string, { x: number; y: number }>;
  validEdges: IREdge[];
};

function computeBaseLayout(irNodes: IRNode[], irEdges: IREdge[]): BaseLayout {
  const g = new graphlib.Graph();
  g.setDefaultEdgeLabel(() => ({}));
  g.setGraph({ rankdir: "LR", ranksep: 100, nodesep: 56 });

  for (const n of irNodes) {
    g.setNode(n.id, { width: NODE_W, height: NODE_H });
  }

  const nodeIdSet = new Set(irNodes.map((n) => n.id));
  const validEdges = irEdges.filter(
    (e) => nodeIdSet.has(e.source) && nodeIdSet.has(e.target),
  );
  for (const e of validEdges) {
    g.setEdge(e.source, e.target);
  }

  layout(g);

  const positions = new Map<string, { x: number; y: number }>();
  for (const n of irNodes) {
    const pos = g.node(n.id) ?? { x: 0, y: 0 };
    positions.set(n.id, { x: pos.x - NODE_W / 2, y: pos.y - NODE_H / 2 });
  }

  return { positions, validEdges };
}

// ─── highlight BFS ────────────────────────────────────────────────────────────

type HighlightInfo = { upstream: Set<string>; downstream: Set<string> } | null;

function computeHighlight(
  selectedId: string,
  irEdges: IREdge[],
): { upstream: Set<string>; downstream: Set<string> } {
  const forward = new Map<string, string[]>();
  const backward = new Map<string, string[]>();

  for (const e of irEdges) {
    if (!forward.has(e.source)) forward.set(e.source, []);
    forward.get(e.source)!.push(e.target);
    if (!backward.has(e.target)) backward.set(e.target, []);
    backward.get(e.target)!.push(e.source);
  }

  function bfs(start: string, adj: Map<string, string[]>): Set<string> {
    const visited = new Set<string>();
    const queue = [start];
    while (queue.length > 0) {
      const cur = queue.shift()!;
      for (const next of adj.get(cur) ?? []) {
        if (!visited.has(next)) {
          visited.add(next);
          queue.push(next);
        }
      }
    }
    return visited;
  }

  return { downstream: bfs(selectedId, forward), upstream: bfs(selectedId, backward) };
}

function getNodeHighlightState(
  nodeId: string,
  selectedId: string | null,
  info: HighlightInfo,
): HighlightState {
  if (selectedId === null) return "normal";
  if (nodeId === selectedId) return "selected";
  if (info === null) return "normal";
  if (info.upstream.has(nodeId) || info.downstream.has(nodeId)) return "path";
  return "dimmed";
}

function isEdgeOnPath(e: IREdge, selectedId: string | null, info: HighlightInfo): boolean {
  if (selectedId === null || info === null) return false;
  const srcOk = e.source === selectedId || info.upstream.has(e.source);
  const tgtOk = e.target === selectedId || info.downstream.has(e.target);
  return srcOk && tgtOk;
}

// ─── component ────────────────────────────────────────────────────────────────

type FlowGraphProps = {
  nodes: IRNode[];
  edges: IREdge[];
};

export function FlowGraph({ nodes: irNodes, edges: irEdges }: FlowGraphProps): JSX.Element {
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const baseLayout = useMemo(() => computeBaseLayout(irNodes, irEdges), [irNodes, irEdges]);

  const highlightInfo: HighlightInfo = useMemo(
    () => (selectedId !== null ? computeHighlight(selectedId, irEdges) : null),
    [selectedId, irEdges],
  );

  const hasSelection = selectedId !== null;

  const nodes: FlowNode[] = useMemo(
    () =>
      irNodes.map((n): FlowNode => ({
        id: n.id,
        type: "custom",
        position: baseLayout.positions.get(n.id) ?? { x: 0, y: 0 },
        data: {
          label: n.label,
          kind: n.kind,
          ...n.meta,
          highlightState: getNodeHighlightState(n.id, selectedId, highlightInfo),
        },
      })),
    [irNodes, baseLayout, selectedId, highlightInfo],
  );

  const edges: Edge[] = useMemo(
    () =>
      baseLayout.validEdges.map((e, i): Edge => {
        const onPath = isEdgeOnPath(e, selectedId, highlightInfo);
        const dimmed = hasSelection && !onPath;
        return {
          id: `e${i}-${e.source}-${e.target}`,
          source: e.source,
          target: e.target,
          label: e.label ?? e.kind,
          animated: onPath || e.kind === "fetches",
          style: {
            stroke: onPath ? "#ffffff" : dimmed ? "rgba(100,100,100,0.2)" : "#666",
            strokeWidth: onPath ? 2 : 1,
          },
          labelStyle: { fontSize: 9, fill: onPath ? "#fff" : "#aaa" },
          labelBgStyle: { fill: "rgba(13,17,23,0.8)" },
        };
      }),
    [baseLayout, selectedId, highlightInfo, hasSelection],
  );

  const handleNodeClick = (_: React.MouseEvent, node: Node): void => {
    setSelectedId((prev) => (prev === node.id ? null : node.id));
  };

  const handlePaneClick = (): void => {
    setSelectedId(null);
  };

  return (
    <div style={{ width: "100%", height: "100%" }}>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        onNodeClick={handleNodeClick}
        onPaneClick={handlePaneClick}
        fitView
        fitViewOptions={{ padding: 0.1 }}
        minZoom={0.05}
        maxZoom={2}
        proOptions={{ hideAttribution: true }}
      >
        <Background color="#30363d" gap={20} />
        <Controls />
        <MiniMap
          nodeColor={(n) => NODE_COLORS[(n.data as FlowNodeData).kind] ?? "#9a9a9a"}
          style={{ background: "#161b22" }}
        />
      </ReactFlow>
    </div>
  );
}
