"""DB schema extractor: DDL tables, Pydantic models, and SQL query references."""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path


# ─── data models ──────────────────────────────────────────────────────────────


@dataclass
class ColumnInfo:
    """A column extracted from a DDL CREATE TABLE statement."""

    name: str
    col_type: str
    nullable: bool
    is_pk: bool


@dataclass
class SqlTableInfo:
    """A SQL table extracted from inline DDL."""

    name: str
    columns: list[ColumnInfo]
    source_file: str
    source_line: int


@dataclass
class PydanticFieldInfo:
    """An annotated field in a Pydantic model."""

    name: str
    annotation: str


@dataclass
class PydanticModelInfo:
    """A Pydantic BaseModel subclass extracted via AST."""

    name: str
    module: str  # dot-notation, e.g. src.schemas.internal_event_v1
    fields: list[PydanticFieldInfo]
    source_file: str
    source_line: int


@dataclass
class SqlQueryInfo:
    """A SQL query reference found inside a string literal."""

    tables: list[str]
    operation: str  # SELECT, INSERT, UPDATE, DELETE
    function_scope: str
    source_file: str
    source_line: int


@dataclass
class DbExtractionResult:
    """Aggregated DB extraction results from one or more source files."""

    tables: list[SqlTableInfo] = field(default_factory=list)
    pydantic_models: list[PydanticModelInfo] = field(default_factory=list)
    sql_queries: list[SqlQueryInfo] = field(default_factory=list)


# ─── shared utility ───────────────────────────────────────────────────────────


def _file_to_module(file_path: str, project_root: Path) -> str:
    """Convert an absolute file path to a dot-notation module string."""
    try:
        rel = Path(file_path).resolve().relative_to(project_root.resolve())
    except ValueError:
        rel = Path(file_path)
    return ".".join(rel.with_suffix("").parts)


# ─── DDL parsing ──────────────────────────────────────────────────────────────

_DDL_RE = re.compile(
    r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(\w+)\s*\((.+?)\)",
    re.IGNORECASE | re.DOTALL,
)

_CONSTRAINT_KEYWORDS = frozenset(
    {"PRIMARY", "FOREIGN", "UNIQUE", "CHECK", "INDEX", "CONSTRAINT"}
)


def _split_col_defs(body: str) -> list[str]:
    """Split DDL column body by top-level commas (respects nested parentheses)."""
    parts: list[str] = []
    depth = 0
    buf: list[str] = []
    for ch in body:
        if ch == "(":
            depth += 1
            buf.append(ch)
        elif ch == ")":
            depth -= 1
            buf.append(ch)
        elif ch == "," and depth == 0:
            parts.append("".join(buf).strip())
            buf = []
        else:
            buf.append(ch)
    if buf:
        parts.append("".join(buf).strip())
    return [p for p in parts if p]


def _parse_column(col_def: str) -> ColumnInfo | None:
    """Return a ColumnInfo from one DDL column definition, or None for table constraints."""
    tokens = col_def.split()
    if not tokens:
        return None
    if tokens[0].upper() in _CONSTRAINT_KEYWORDS:
        return None
    name = tokens[0]
    col_type = tokens[1] if len(tokens) > 1 else "UNKNOWN"
    upper = col_def.upper()
    is_pk = "PRIMARY KEY" in upper
    nullable = "NOT NULL" not in upper and not is_pk
    return ColumnInfo(name=name, col_type=col_type, nullable=nullable, is_pk=is_pk)


def _extract_ddl(source: str, file_path: str) -> list[SqlTableInfo]:
    """Scan source text for CREATE TABLE statements and extract table schemas."""
    results: list[SqlTableInfo] = []
    for match in _DDL_RE.finditer(source):
        table_name = match.group(1)
        body = match.group(2)
        line = source[: match.start()].count("\n") + 1
        columns = [c for col_def in _split_col_defs(body) if (c := _parse_column(col_def)) is not None]
        results.append(
            SqlTableInfo(
                name=table_name,
                columns=columns,
                source_file=file_path,
                source_line=line,
            )
        )
    return results


# ─── Pydantic model extraction ────────────────────────────────────────────────

_PYDANTIC_BASES = frozenset({"BaseModel", "BaseSettings"})


class _PydanticVisitor(ast.NodeVisitor):
    """AST visitor that collects Pydantic BaseModel subclasses."""

    def __init__(self, file_path: str, module: str) -> None:
        self._file = file_path
        self._module = module
        self.models: list[PydanticModelInfo] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        base_names = {
            b.id
            if isinstance(b, ast.Name)
            else b.attr
            if isinstance(b, ast.Attribute)
            else ""
            for b in node.bases
        }
        if base_names & _PYDANTIC_BASES:
            fields: list[PydanticFieldInfo] = []
            for item in node.body:
                if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                    fields.append(
                        PydanticFieldInfo(
                            name=item.target.id,
                            annotation=ast.unparse(item.annotation),
                        )
                    )
            self.models.append(
                PydanticModelInfo(
                    name=node.name,
                    module=self._module,
                    fields=fields,
                    source_file=self._file,
                    source_line=node.lineno,
                )
            )
        self.generic_visit(node)


def _extract_pydantic(
    source: str, file_path: str, project_root: Path
) -> list[PydanticModelInfo]:
    """Extract Pydantic BaseModel subclasses from Python source."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    module = _file_to_module(file_path, project_root)
    visitor = _PydanticVisitor(file_path, module)
    visitor.visit(tree)
    return visitor.models


# ─── SQL query reference extraction ──────────────────────────────────────────

_SQL_KEYWORDS_RE = re.compile(
    r"\b(?:SELECT|INSERT|UPDATE|DELETE)\b",
    re.IGNORECASE,
)
_FROM_RE = re.compile(r"\bFROM\b\s+(\w+)", re.IGNORECASE)
_JOIN_RE = re.compile(r"\bJOIN\b\s+(\w+)", re.IGNORECASE)
_INTO_RE = re.compile(r"\bINTO\b\s+(\w+)", re.IGNORECASE)
_UPDATE_RE = re.compile(r"^\s*UPDATE\s+(\w+)", re.IGNORECASE | re.MULTILINE)


def _op_from_sql(text: str) -> str:
    upper = text.upper()
    if "INSERT" in upper:
        return "INSERT"
    if "UPDATE" in upper:
        return "UPDATE"
    if "DELETE" in upper:
        return "DELETE"
    return "SELECT"


def _tables_from_sql(text: str) -> list[str]:
    tables: list[str] = []
    for m in _FROM_RE.finditer(text):
        tables.append(m.group(1))
    for m in _JOIN_RE.finditer(text):
        tables.append(m.group(1))
    for m in _INTO_RE.finditer(text):
        tables.append(m.group(1))
    for m in _UPDATE_RE.finditer(text):
        tables.append(m.group(1))
    return list(dict.fromkeys(tables))


class _SqlQueryVisitor(ast.NodeVisitor):
    """Visits string literals to find SQL query references to known tables."""

    def __init__(self, file_path: str, known_tables: set[str] | None) -> None:
        self._file = file_path
        self._known_tables: set[str] | None = known_tables
        self._scope_stack: list[str] = []
        self.queries: list[SqlQueryInfo] = []

    def _current_scope(self) -> str:
        return ".".join(self._scope_stack) if self._scope_stack else "<module>"

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._scope_stack.append(node.name)
        self.generic_visit(node)
        self._scope_stack.pop()

    def visit_FunctionDef(
        self, node: ast.FunctionDef | ast.AsyncFunctionDef
    ) -> None:
        self._scope_stack.append(node.name)
        self.generic_visit(node)
        self._scope_stack.pop()

    visit_AsyncFunctionDef = visit_FunctionDef  # type: ignore[assignment]

    def visit_Constant(self, node: ast.Constant) -> None:
        if not isinstance(node.value, str):
            return
        text = node.value
        if not _SQL_KEYWORDS_RE.search(text):
            return
        tables = _tables_from_sql(text)
        if self._known_tables is not None:
            tables = [t for t in tables if t in self._known_tables]
        if not tables:
            return
        self.queries.append(
            SqlQueryInfo(
                tables=tables,
                operation=_op_from_sql(text),
                function_scope=self._current_scope(),
                source_file=self._file,
                source_line=node.lineno,
            )
        )


def _extract_sql_queries(
    source: str, file_path: str, known_tables: set[str] | None
) -> list[SqlQueryInfo]:
    """Extract SQL query references from string literals in source."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    visitor = _SqlQueryVisitor(file_path, known_tables)
    visitor.visit(tree)
    return visitor.queries


# ─── public API ───────────────────────────────────────────────────────────────


def extract_from_source(
    source: str,
    file_path: str,
    project_root: Path,
    known_tables: set[str] | None = None,
) -> DbExtractionResult:
    """Extract DB schema information from a single Python source string."""
    tables = _extract_ddl(source, file_path)
    pydantic_models = _extract_pydantic(source, file_path, project_root)
    sql_queries = _extract_sql_queries(source, file_path, known_tables)
    return DbExtractionResult(
        tables=tables, pydantic_models=pydantic_models, sql_queries=sql_queries
    )


def extract_from_directory(
    directory: Path,
    project_root: Path | None = None,
) -> DbExtractionResult:
    """Walk .py files under directory and aggregate DB schema extraction results.

    Two-pass: first collect all DDL table names, then extract SQL query references
    filtered to only those table names.
    """
    root = project_root or directory
    result = DbExtractionResult()

    # First pass: DDL tables + collect source texts
    all_sources: list[tuple[str, str]] = []
    for py_file in sorted(directory.rglob("*.py")):
        source = py_file.read_text(encoding="utf-8")
        all_sources.append((source, str(py_file)))
        result.tables.extend(_extract_ddl(source, str(py_file)))

    known_tables = {t.name for t in result.tables}

    # Second pass: Pydantic models + SQL query references
    for source, file_path in all_sources:
        result.pydantic_models.extend(_extract_pydantic(source, file_path, root))
        result.sql_queries.extend(_extract_sql_queries(source, file_path, known_tables))

    return result
