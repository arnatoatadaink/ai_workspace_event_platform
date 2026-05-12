"""FastAPI route extractor via Python AST."""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path

_HTTP_METHODS = frozenset({"get", "post", "put", "patch", "delete", "head", "options"})


@dataclass
class RouteInfo:
    """A single FastAPI route handler extracted from source."""

    path: str
    method: str  # uppercase: GET, POST, PUT, PATCH, DELETE
    handler_name: str
    response_model: str | None
    tags: list[str]
    file: str
    line: int


class _RouteExtractor(ast.NodeVisitor):
    """AST visitor that collects FastAPI @router.METHOD() route definitions."""

    def __init__(self, file_path: str) -> None:
        self._file = file_path
        self.routes: list[RouteInfo] = []

    def visit_FunctionDef(
        self, node: ast.FunctionDef | ast.AsyncFunctionDef
    ) -> None:
        for decorator in node.decorator_list:
            route = self._try_extract(decorator, node.name, node.lineno)
            if route is not None:
                self.routes.append(route)
        self.generic_visit(node)

    visit_AsyncFunctionDef = visit_FunctionDef  # type: ignore[assignment]

    def _try_extract(
        self, decorator: ast.expr, handler_name: str, line: int
    ) -> RouteInfo | None:
        if not isinstance(decorator, ast.Call):
            return None
        func = decorator.func
        if not isinstance(func, ast.Attribute):
            return None
        method = func.attr.lower()
        if method not in _HTTP_METHODS:
            return None

        path: str | None = None
        if decorator.args:
            first = decorator.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                path = first.value

        response_model: str | None = None
        tags: list[str] = []
        for kw in decorator.keywords:
            if kw.arg == "path" and isinstance(kw.value, ast.Constant):
                path = str(kw.value.value)
            elif kw.arg == "response_model":
                response_model = ast.unparse(kw.value)
            elif kw.arg == "tags" and isinstance(kw.value, ast.List):
                for elt in kw.value.elts:
                    if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                        tags.append(elt.value)

        if path is None:
            return None

        return RouteInfo(
            path=path,
            method=method.upper(),
            handler_name=handler_name,
            response_model=response_model,
            tags=tags,
            file=self._file,
            line=line,
        )


def extract_from_source(source: str, file_path: str) -> list[RouteInfo]:
    """Parse Python source and return all FastAPI route definitions."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    visitor = _RouteExtractor(file_path)
    visitor.visit(tree)
    return visitor.routes


def extract_from_directory(directory: Path) -> list[RouteInfo]:
    """Walk .py files under directory and aggregate route extraction results."""
    routes: list[RouteInfo] = []
    for py_file in sorted(directory.rglob("*.py")):
        source = py_file.read_text(encoding="utf-8")
        routes.extend(extract_from_source(source, str(py_file)))
    return routes
