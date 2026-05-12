import { useMemo } from "react";
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

// ─── custom node ──────────────────────────────────────────────────────────────

type FlowNodeData = { label: string; kind: NodeKind } & Record<string, unknown>;
type FlowNode = Node<FlowNodeData, "custom">;

function CustomNode({ data }: NodeProps<FlowNode>): JSX.Element {
  const color = NODE_COLORS[data.kind] ?? "#9a9a9a";
  return (
    <div
      style={{
        background: color,
        border: "1px solid rgba(0,0,0,0.25)",
        borderRadius: 6,
        padding: "4px 10px",
        fontSize: 11,
        fontFamily: "monospace",
        width: NODE_W,
        boxSizing: "border-box",
        color: "#1a1a2e",
        overflow: "hidden",
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

// ─── layout ───────────────────────────────────────────────────────────────────

function computeLayout(
  irNodes: IRNode[],
  irEdges: IREdge[],
): { nodes: FlowNode[]; edges: Edge[] } {
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

  return {
    nodes: irNodes.map((n): FlowNode => {
      const pos = g.node(n.id) ?? { x: 0, y: 0 };
      return {
        id: n.id,
        type: "custom",
        position: { x: pos.x - NODE_W / 2, y: pos.y - NODE_H / 2 },
        data: { label: n.label, kind: n.kind, ...n.meta },
      };
    }),
    edges: validEdges.map((e, i): Edge => ({
      id: `e${i}-${e.source}-${e.target}`,
      source: e.source,
      target: e.target,
      label: e.label ?? e.kind,
      animated: e.kind === "fetches",
      style: { stroke: "#666" },
      labelStyle: { fontSize: 9, fill: "#aaa" },
      labelBgStyle: { fill: "rgba(13,17,23,0.8)" },
    })),
  };
}

// ─── component ────────────────────────────────────────────────────────────────

type FlowGraphProps = {
  nodes: IRNode[];
  edges: IREdge[];
};

export function FlowGraph({ nodes: irNodes, edges: irEdges }: FlowGraphProps): JSX.Element {
  const { nodes, edges } = useMemo(
    () => computeLayout(irNodes, irEdges),
    [irNodes, irEdges],
  );

  return (
    <div style={{ width: "100%", height: "100%" }}>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
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
