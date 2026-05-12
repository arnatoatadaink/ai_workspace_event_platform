"""Intermediate Representation (IR) builder for the data flow graph.

Combines Python static analysis (AST, call graph, routes, DB schema) with
frontend analysis exported by web/scripts/analysis/ir-exporter.ts into a
single JSON graph (nodes + edges) consumed by the ReactFlow visualizer.

Static-only phase: dynamic overlay (FrontendDebugEvent coloring) is deferred.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from src.analysis.ast_extractor import FunctionInfo
from src.analysis.ast_extractor import extract_from_directory as py_extract
from src.analysis.call_graph import build_call_graph
from src.analysis.db_schema_extractor import extract_from_directory as db_extract
from src.analysis.route_extractor import RouteInfo
from src.analysis.route_extractor import extract_from_directory as route_extract

# ─── IR types ─────────────────────────────────────────────────────────────────

NodeKind = Literal[
    "component", "hook", "fetch_call", "route", "function", "pydantic", "table"
]
EdgeKind = Literal["fetches", "calls", "queries", "models", "uses_hook", "defines"]


class IRNode(BaseModel):
    """A node in the data flow graph."""

    id: str
    kind: NodeKind
    label: str
    meta: dict[str, object] = Field(default_factory=dict)


class IREdge(BaseModel):
    """A directed edge in the data flow graph."""

    source: str
    target: str
    kind: EdgeKind
    label: str = ""


class DataFlowIR(BaseModel):
    """The complete data flow intermediate representation."""

    nodes: list[IRNode]
    edges: list[IREdge]


# ─── helpers ──────────────────────────────────────────────────────────────────

_TEMPLATE_VAR_RE = re.compile(r"\$\{[^}]+\}")
_PATH_VAR_RE = re.compile(r"\{[^}]+\}")
_CLASS_NAME_RE = re.compile(r"\b([A-Z][A-Za-z0-9_]*)\b")


def _file_to_module(file_path: str, project_root: Path) -> str:
    """Convert an absolute file path to a dot-notation module string."""
    try:
        rel = Path(file_path).resolve().relative_to(project_root.resolve())
    except ValueError:
        rel = Path(file_path)
    return ".".join(rel.with_suffix("").parts)


def _func_node_id(func: FunctionInfo, project_root: Path) -> str:
    module = _file_to_module(func.file, project_root)
    return f"py:{module}:{func.qualified_name}"


def _normalize_path(path: str) -> str:
    """Normalize URL path for matching: replace variable segments with {*}."""
    path = _TEMPLATE_VAR_RE.sub("{*}", path)
    path = _PATH_VAR_RE.sub("{*}", path)
    return path


def _bfs_reachable(
    start_qnames: set[str],
    call_map: dict[str, list[str]],
    max_hops: int,
) -> set[str]:
    """BFS from start_qnames through call_map, up to max_hops."""
    visited = set(start_qnames)
    frontier = set(start_qnames)
    for _ in range(max_hops):
        next_frontier: set[str] = set()
        for qname in frontier:
            for callee in call_map.get(qname, []):
                if callee not in visited:
                    visited.add(callee)
                    next_frontier.add(callee)
        frontier = next_frontier
        if not frontier:
            break
    return visited


def _load_frontend_analysis(project_root: Path) -> dict[str, list[dict[str, object]]]:
    """Load frontend IR produced by ir-exporter.ts, or return empty structure."""
    path = project_root / "runtime" / "frontend_analysis.json"
    if not path.exists():
        return {"nodes": [], "edges": []}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return {"nodes": [], "edges": []}
    return data  # type: ignore[return-value]


# ─── public API ───────────────────────────────────────────────────────────────


def build_ir(src_dir: Path, project_root: Path = Path(".")) -> DataFlowIR:
    """Build the complete data flow IR from static analysis of src_dir.

    Steps:
      1. Python AST + call graph extraction
      2. FastAPI route extraction
      3. DB schema extraction (DDL + Pydantic + SQL queries)
      4. Frontend analysis from runtime/frontend_analysis.json
      5. Merge into nodes + edges, filtered to reduce noise
    """
    # ── extraction ──────────────────────────────────────────────────────────
    py_functions, py_call_sites = py_extract(src_dir)
    call_edges = build_call_graph(py_functions, py_call_sites)
    routes = route_extract(src_dir)
    db_result = db_extract(src_dir, project_root)
    fe_data = _load_frontend_analysis(project_root)

    # ── build indices ────────────────────────────────────────────────────────
    func_by_file_name: dict[tuple[str, str], FunctionInfo] = {}
    for func in py_functions:
        func_by_file_name.setdefault((func.file, func.name), func)

    # caller qualified_name → list of callee qualified_names
    call_map: dict[str, list[str]] = {}
    for edge in call_edges:
        call_map.setdefault(edge.caller, []).append(edge.callee.qualified_name)

    # ── function filter ──────────────────────────────────────────────────────
    route_handler_qnames: set[str] = set()
    for route in routes:
        handler = func_by_file_name.get((route.file, route.handler_name))
        if handler:
            route_handler_qnames.add(handler.qualified_name)

    query_func_qnames: set[str] = {q.function_scope for q in db_result.sql_queries}

    included_qnames = _bfs_reachable(
        route_handler_qnames | query_func_qnames, call_map, max_hops=2
    )
    included_funcs = [f for f in py_functions if f.qualified_name in included_qnames]

    # qualified_name → node id (first match wins when names collide across files)
    func_id_by_qname: dict[str, str] = {}
    for func in included_funcs:
        func_id_by_qname.setdefault(func.qualified_name, _func_node_id(func, project_root))

    # ── accumulate nodes + edges ─────────────────────────────────────────────
    nodes: list[IRNode] = []
    edges: list[IREdge] = []
    node_ids: set[str] = set()

    def _add(node: IRNode) -> None:
        if node.id not in node_ids:
            nodes.append(node)
            node_ids.add(node.id)

    # frontend nodes
    for fe_node in fe_data.get("nodes", []):
        if not isinstance(fe_node, dict):
            continue
        _add(
            IRNode(
                id=str(fe_node.get("id", "")),
                kind=fe_node.get("kind", "component"),  # type: ignore[arg-type]
                label=str(fe_node.get("label", "")),
                meta=fe_node.get("meta", {}),  # type: ignore[arg-type]
            )
        )

    # API route nodes
    for route in routes:
        route_id = f"api:{route.method}:{route.path}"
        _add(
            IRNode(
                id=route_id,
                kind="route",
                label=f"{route.method} {route.path}",
                meta={
                    "method": route.method,
                    "path": route.path,
                    "response_model": route.response_model,
                    "tags": route.tags,
                    "file": route.file,
                    "line": route.line,
                },
            )
        )

    # Python function nodes (filtered)
    for func in included_funcs:
        func_id = _func_node_id(func, project_root)
        _add(
            IRNode(
                id=func_id,
                kind="function",
                label=func.name,
                meta={
                    "file": func.file,
                    "line": func.line,
                    "qualified_name": func.qualified_name,
                    "return_type": func.return_annotation,
                },
            )
        )

    # Pydantic model nodes
    for model in db_result.pydantic_models:
        model_id = f"py:{model.module}:{model.name}"
        _add(
            IRNode(
                id=model_id,
                kind="pydantic",
                label=model.name,
                meta={
                    "file": model.source_file,
                    "line": model.source_line,
                    "fields": [
                        {"name": f.name, "type": f.annotation} for f in model.fields
                    ],
                },
            )
        )

    # DB table nodes
    for table in db_result.tables:
        _add(
            IRNode(
                id=f"db:{table.name}",
                kind="table",
                label=table.name,
                meta={
                    "file": table.source_file,
                    "line": table.source_line,
                    "columns": [
                        {
                            "name": c.name,
                            "type": c.col_type,
                            "nullable": c.nullable,
                            "is_pk": c.is_pk,
                        }
                        for c in table.columns
                    ],
                },
            )
        )

    # ── edges ────────────────────────────────────────────────────────────────

    # frontend edges (uses_hook etc.)
    for fe_edge in fe_data.get("edges", []):
        if not isinstance(fe_edge, dict):
            continue
        edges.append(
            IREdge(
                source=str(fe_edge.get("source", "")),
                target=str(fe_edge.get("target", "")),
                kind=fe_edge.get("kind", "uses_hook"),  # type: ignore[arg-type]
                label=str(fe_edge.get("label", "")),
            )
        )

    # fetches: fe:fetch → api:route (matched by normalized path + method)
    fe_fetch_nodes = {
        str(n.get("id", "")): n
        for n in fe_data.get("nodes", [])
        if isinstance(n, dict) and n.get("kind") == "fetch_call"
    }
    for route in routes:
        route_id = f"api:{route.method}:{route.path}"
        normalized_route = _normalize_path(route.path)
        for fetch_id, fetch_node in fe_fetch_nodes.items():
            meta = fetch_node.get("meta", {})
            if not isinstance(meta, dict):
                continue
            fetch_method = str(meta.get("method", "GET"))
            fetch_path = _normalize_path(str(meta.get("path", "")))
            if fetch_method == route.method and fetch_path == normalized_route:
                edges.append(IREdge(source=fetch_id, target=route_id, kind="fetches"))

    # defines: api:route → py:function
    for route in routes:
        route_id = f"api:{route.method}:{route.path}"
        handler = func_by_file_name.get((route.file, route.handler_name))
        if handler:
            func_id = func_id_by_qname.get(handler.qualified_name)
            if func_id and func_id in node_ids:
                edges.append(
                    IREdge(source=route_id, target=func_id, kind="defines")
                )

    # models: api:route → py:pydantic (from response_model annotation)
    pydantic_by_name: dict[str, str] = {}
    for model in db_result.pydantic_models:
        model_id = f"py:{model.module}:{model.name}"
        if model_id in node_ids:
            pydantic_by_name.setdefault(model.name, model_id)

    for route in routes:
        if not route.response_model:
            continue
        route_id = f"api:{route.method}:{route.path}"
        for cls_name in _CLASS_NAME_RE.findall(route.response_model):
            model_id = pydantic_by_name.get(cls_name)
            if model_id:
                edges.append(
                    IREdge(source=route_id, target=model_id, kind="models")
                )

    # calls: py:func → py:func (filtered call graph)
    included_qname_set = {f.qualified_name for f in included_funcs}
    seen_call_pairs: set[tuple[str, str]] = set()
    for edge in call_edges:
        if edge.caller not in included_qname_set:
            continue
        if edge.callee.qualified_name not in included_qname_set:
            continue
        src_id = func_id_by_qname.get(edge.caller)
        tgt_id = func_id_by_qname.get(edge.callee.qualified_name)
        if src_id and tgt_id and src_id != tgt_id:
            key = (src_id, tgt_id)
            if key not in seen_call_pairs:
                seen_call_pairs.add(key)
                edges.append(IREdge(source=src_id, target=tgt_id, kind="calls"))

    # queries: py:func → db:table
    for query in db_result.sql_queries:
        src_id = func_id_by_qname.get(query.function_scope)
        if not src_id:
            continue
        for table_name in query.tables:
            tgt_id = f"db:{table_name}"
            if tgt_id in node_ids:
                edges.append(
                    IREdge(
                        source=src_id,
                        target=tgt_id,
                        kind="queries",
                        label=query.operation,
                    )
                )

    return DataFlowIR(nodes=nodes, edges=edges)
