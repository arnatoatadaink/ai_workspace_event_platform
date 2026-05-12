"""Tests for src/analysis/db_schema_extractor.py."""

from pathlib import Path

import pytest

from src.analysis.db_schema_extractor import (
    DbExtractionResult,
    _extract_ddl,
    _extract_pydantic,
    _parse_column,
    _split_col_defs,
    extract_from_source,
)

# ─── _split_col_defs ─────────────────────────────────────────────────────────


def test_split_col_defs_basic() -> None:
    parts = _split_col_defs("id TEXT PRIMARY KEY, name TEXT NOT NULL, age INT")
    assert len(parts) == 3


def test_split_col_defs_nested_parens() -> None:
    body = "id TEXT, fk TEXT REFERENCES other(id)"
    parts = _split_col_defs(body)
    assert len(parts) == 2


def test_split_col_defs_empty_parts_filtered() -> None:
    parts = _split_col_defs("id TEXT,  ")
    assert len(parts) == 1


# ─── _parse_column ───────────────────────────────────────────────────────────


def test_parse_column_basic() -> None:
    col = _parse_column("name TEXT NOT NULL")
    assert col is not None
    assert col.name == "name"
    assert col.col_type == "TEXT"
    assert not col.nullable


def test_parse_column_primary_key() -> None:
    col = _parse_column("id TEXT PRIMARY KEY")
    assert col is not None
    assert col.is_pk
    assert not col.nullable


def test_parse_column_nullable() -> None:
    col = _parse_column("email TEXT")
    assert col is not None
    assert col.nullable
    assert not col.is_pk


def test_parse_column_constraint_skipped() -> None:
    assert _parse_column("PRIMARY KEY (id, name)") is None
    assert _parse_column("FOREIGN KEY (fk) REFERENCES t(id)") is None
    assert _parse_column("UNIQUE (email)") is None


# ─── _extract_ddl ────────────────────────────────────────────────────────────

_DDL_SOURCE = '''
sql = """
CREATE TABLE IF NOT EXISTS users (
    user_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT,
    created_at TEXT NOT NULL
)
"""
'''


def test_ddl_table_name() -> None:
    tables = _extract_ddl(_DDL_SOURCE, "test.py")
    assert len(tables) == 1
    assert tables[0].name == "users"


def test_ddl_columns_count() -> None:
    tables = _extract_ddl(_DDL_SOURCE, "test.py")
    assert len(tables[0].columns) == 4


def test_ddl_column_names() -> None:
    tables = _extract_ddl(_DDL_SOURCE, "test.py")
    names = [c.name for c in tables[0].columns]
    assert "user_id" in names
    assert "email" in names


def test_ddl_primary_key() -> None:
    tables = _extract_ddl(_DDL_SOURCE, "test.py")
    pk_cols = [c for c in tables[0].columns if c.is_pk]
    assert len(pk_cols) == 1
    assert pk_cols[0].name == "user_id"


def test_ddl_no_tables() -> None:
    tables = _extract_ddl("# no SQL here\nx = 1", "test.py")
    assert tables == []


def test_ddl_multiple_tables() -> None:
    source = """
CREATE TABLE a (id TEXT PRIMARY KEY);
CREATE TABLE b (x INT, y INT);
"""
    tables = _extract_ddl(source, "test.py")
    names = {t.name for t in tables}
    assert names == {"a", "b"}


# ─── _extract_pydantic ───────────────────────────────────────────────────────

_PYDANTIC_SOURCE = '''
from pydantic import BaseModel

class UserModel(BaseModel):
    id: str
    name: str
    age: int | None = None
'''


def test_pydantic_model_name() -> None:
    models = _extract_pydantic(_PYDANTIC_SOURCE, "test.py", Path("."))
    assert len(models) == 1
    assert models[0].name == "UserModel"


def test_pydantic_fields() -> None:
    models = _extract_pydantic(_PYDANTIC_SOURCE, "test.py", Path("."))
    field_names = [f.name for f in models[0].fields]
    assert "id" in field_names
    assert "name" in field_names
    assert "age" in field_names


def test_pydantic_non_model_skipped() -> None:
    source = "class Plain:\n    x: int\n"
    models = _extract_pydantic(source, "test.py", Path("."))
    assert models == []


def test_pydantic_module_path() -> None:
    models = _extract_pydantic(
        _PYDANTIC_SOURCE, "/project/src/schemas/events.py", Path("/project")
    )
    assert models[0].module == "src.schemas.events"


# ─── extract_from_source (combined) ─────────────────────────────────────────

_COMBINED_SOURCE = '''
from pydantic import BaseModel

class Event(BaseModel):
    event_id: str

_DDL = """
CREATE TABLE IF NOT EXISTS events (
    event_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL
)
"""

def insert_event() -> None:
    sql = "INSERT INTO events (event_id, session_id) VALUES (?, ?)"
'''


def test_combined_tables() -> None:
    result = extract_from_source(_COMBINED_SOURCE, "test.py", Path("."), known_tables={"events"})
    assert len(result.tables) == 1
    assert result.tables[0].name == "events"


def test_combined_pydantic() -> None:
    result = extract_from_source(_COMBINED_SOURCE, "test.py", Path("."))
    assert len(result.pydantic_models) == 1
    assert result.pydantic_models[0].name == "Event"


def test_combined_sql_queries() -> None:
    result = extract_from_source(_COMBINED_SOURCE, "test.py", Path("."), known_tables={"events"})
    assert len(result.sql_queries) == 1
    assert result.sql_queries[0].operation == "INSERT"
    assert "events" in result.sql_queries[0].tables


def test_sql_query_no_known_tables_filters_all() -> None:
    # Without known_tables, queries are not filtered (empty set means no filter)
    result = extract_from_source(_COMBINED_SOURCE, "test.py", Path("."), known_tables=set())
    # known_tables is empty → no matches, so queries should be empty
    assert result.sql_queries == []


def test_returns_dataclass() -> None:
    result = extract_from_source("x = 1", "test.py", Path("."))
    assert isinstance(result, DbExtractionResult)
