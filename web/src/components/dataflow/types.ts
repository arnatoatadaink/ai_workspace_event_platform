export type NodeKind =
  | "component"
  | "hook"
  | "fetch_call"
  | "route"
  | "function"
  | "pydantic"
  | "table";

export type EdgeKind =
  | "fetches"
  | "calls"
  | "queries"
  | "models"
  | "uses_hook"
  | "defines";

export interface IRNode {
  id: string;
  kind: NodeKind;
  label: string;
  meta: Record<string, unknown>;
}

export interface IREdge {
  source: string;
  target: string;
  kind: EdgeKind;
  label?: string;
}

export interface DataFlowIR {
  nodes: IRNode[];
  edges: IREdge[];
}
