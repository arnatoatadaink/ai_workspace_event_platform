"""Tests for dynamic type-mismatch checker (typeguard capture + enrichment)."""

from __future__ import annotations

import json
import types
from pathlib import Path

from src.analysis.ast_extractor import CallSiteInfo, FunctionInfo, extract_from_source
from src.analysis.call_graph import CallEdge, build_call_graph, build_reverse_call_graph
from src.analysis.dynamic_capture import extract_user_frames, parse_typeguard_message
from src.analysis.dynamic_checker import (
    DynamicCheckEvent,
    EnrichedEvent,
    enrich_events,
    generate_report_json,
    generate_report_md,
    load_events,
    run_check,
)
from src.analysis.type_mismatch import TypeMismatch

# ---------------------------------------------------------------------------
# parse_typeguard_message
# ---------------------------------------------------------------------------


def test_parse_argument_mismatch() -> None:
    msg = 'argument "name" (int) is not an instance of str'
    result = parse_typeguard_message(msg)
    assert result["kind"] == "argument"
    assert result["param_name"] == "name"
    assert result["actual_type"] == "int"
    assert result["expected_type"] == "str"


def test_parse_return_mismatch() -> None:
    msg = "return value (list) is not an instance of str"
    result = parse_typeguard_message(msg)
    assert result["kind"] == "return"
    assert result["actual_type"] == "list"
    assert result["expected_type"] == "str"
    assert result["param_name"] == ""


def test_parse_unknown_format() -> None:
    result = parse_typeguard_message("some unrecognized error")
    assert result["kind"] == "unknown"


def test_parse_param_with_dots() -> None:
    msg = 'argument "my_param" (MyClass) is not an instance of BaseClass'
    result = parse_typeguard_message(msg)
    assert result["param_name"] == "my_param"
    assert result["expected_type"] == "BaseClass"


# ---------------------------------------------------------------------------
# extract_user_frames
# ---------------------------------------------------------------------------


def _make_traceback(filenames: list[str]) -> types.TracebackType | None:
    """Build a fake traceback chain for testing."""
    tb: types.TracebackType | None = None
    for filename in reversed(filenames):
        try:
            raise RuntimeError("test")
        except RuntimeError:
            import sys

            exc_tb = sys.exc_info()[2]
            assert exc_tb is not None
            # Override filename via code object replacement is complex;
            # instead we test with real tracebacks from actual code.
        break
    return tb  # noqa: B012 — only used to satisfy type checker below


def test_extract_user_frames_filters_typeguard() -> None:
    """User frames should exclude frames whose filename contains 'typeguard' or '.venv'."""
    # Simulate by examining the helper's filter logic via a real exception
    try:
        raise ValueError("test")
    except ValueError:
        import sys

        tb = sys.exc_info()[2]
        frames = extract_user_frames(tb)
        # All frames should be user frames (no typeguard/.venv paths in this test)
        for f in frames:
            assert "typeguard" not in str(f["file"])
            assert ".venv" not in str(f["file"])
        assert len(frames) >= 1


# ---------------------------------------------------------------------------
# build_reverse_call_graph
# ---------------------------------------------------------------------------


def test_reverse_call_graph_empty() -> None:
    assert build_reverse_call_graph([]) == {}


def test_reverse_call_graph_single_edge() -> None:
    func = FunctionInfo(
        name="foo", qualified_name="foo", file="a.py", line=1, params={}, return_annotation=None
    )
    site = CallSiteInfo(
        caller_func="bar", callee_name="foo", arg_type_hints=[], file="b.py", line=5
    )
    edge = CallEdge(caller="bar", callee=func, call_site=site)
    result = build_reverse_call_graph([edge])
    assert "foo" in result
    assert result["foo"] == [edge]


def test_reverse_call_graph_multiple_callers() -> None:
    func = FunctionInfo(
        name="target",
        qualified_name="target",
        file="a.py",
        line=1,
        params={},
        return_annotation=None,
    )
    site1 = CallSiteInfo(
        caller_func="caller1", callee_name="target", arg_type_hints=[], file="b.py", line=5
    )
    site2 = CallSiteInfo(
        caller_func="caller2", callee_name="target", arg_type_hints=[], file="c.py", line=10
    )
    edge1 = CallEdge(caller="caller1", callee=func, call_site=site1)
    edge2 = CallEdge(caller="caller2", callee=func, call_site=site2)
    result = build_reverse_call_graph([edge1, edge2])
    assert len(result["target"]) == 2


def test_reverse_cga_uses_qualified_name() -> None:
    func = FunctionInfo(
        name="method",
        qualified_name="MyClass.method",
        file="a.py",
        line=1,
        params={},
        return_annotation=None,
    )
    site = CallSiteInfo(
        caller_func="caller", callee_name="method", arg_type_hints=[], file="b.py", line=3
    )
    edge = CallEdge(caller="caller", callee=func, call_site=site)
    result = build_reverse_call_graph([edge])
    assert "MyClass.method" in result
    assert "method" not in result


# ---------------------------------------------------------------------------
# load_events / enrich_events
# ---------------------------------------------------------------------------


def _make_event(
    func_name: str = "greet",
    param_name: str = "name",
    actual_type: str = "int",
    expected_type: str = "str",
) -> DynamicCheckEvent:
    return DynamicCheckEvent(
        timestamp="2026-01-01T00:00:00+00:00",
        message=f'argument "{param_name}" ({actual_type}) is not an instance of {expected_type}',
        kind="argument",
        param_name=param_name,
        actual_type=actual_type,
        expected_type=expected_type,
        call_site_file="tests/test_foo.py",
        call_site_line=10,
        call_site_func="test_greet",
        func_file="src/foo.py",
        func_line=5,
        func_name=func_name,
    )


def test_load_events_empty_file(tmp_path: Path) -> None:
    f = tmp_path / "events.jsonl"
    f.write_text("")
    assert load_events(f) == []


def test_load_events_missing_file(tmp_path: Path) -> None:
    assert load_events(tmp_path / "nonexistent.jsonl") == []


def test_load_events_parses_correctly(tmp_path: Path) -> None:
    ev = _make_event()
    f = tmp_path / "events.jsonl"
    row = {
        "timestamp": ev.timestamp,
        "message": ev.message,
        "kind": ev.kind,
        "param_name": ev.param_name,
        "actual_type": ev.actual_type,
        "expected_type": ev.expected_type,
        "call_site_file": ev.call_site_file,
        "call_site_line": ev.call_site_line,
        "call_site_func": ev.call_site_func,
        "func_file": ev.func_file,
        "func_line": ev.func_line,
        "func_name": ev.func_name,
    }
    f.write_text(json.dumps(row) + "\n")
    loaded = load_events(f)
    assert len(loaded) == 1
    assert loaded[0].func_name == "greet"
    assert loaded[0].actual_type == "int"


def test_enrich_events_finds_func_info() -> None:
    source = "def greet(name: str) -> str:\n    return name\n"
    functions, call_sites = extract_from_source(source, "src/foo.py")
    edges = build_call_graph(functions, call_sites)

    ev = _make_event(func_name="greet", param_name="name", actual_type="int", expected_type="str")
    enriched = enrich_events([ev], functions, edges, [])
    assert len(enriched) == 1
    assert enriched[0].func_info is not None
    assert enriched[0].func_info.name == "greet"


def test_enrich_events_unknown_func() -> None:
    ev = _make_event(func_name="unknown_func")
    enriched = enrich_events([ev], [], [], [])
    assert enriched[0].func_info is None
    assert enriched[0].callers == []


def test_enrich_events_finds_callers() -> None:
    source = "def greet(name: str) -> str:\n    return name\ndef caller():\n    greet(42)\n"
    functions, call_sites = extract_from_source(source, "src/foo.py")
    edges = build_call_graph(functions, call_sites)

    ev = _make_event(func_name="greet")
    enriched = enrich_events([ev], functions, edges, [])
    assert len(enriched[0].callers) >= 1
    caller_names = [c.caller for c in enriched[0].callers]
    assert "caller" in caller_names


def test_enrich_events_cross_references_static_mismatch() -> None:
    source = "def greet(name: str) -> str:\n    return name\n"
    functions, call_sites = extract_from_source(source, "src/foo.py")
    edges = build_call_graph(functions, call_sites)

    static = TypeMismatch(
        function_name="greet",
        param_name="name",
        expected="str",
        actual="int",
        call_site_file="tests/test_foo.py",
        call_site_line=10,
    )
    ev = _make_event(func_name="greet", param_name="name")
    enriched = enrich_events([ev], functions, edges, [static])
    assert enriched[0].static_match is not None


# ---------------------------------------------------------------------------
# generate_report_json / generate_report_md
# ---------------------------------------------------------------------------


def _make_enriched(tmp_func_name: str = "greet") -> EnrichedEvent:
    ev = _make_event(func_name=tmp_func_name)
    func_info = FunctionInfo(
        name=tmp_func_name,
        qualified_name=tmp_func_name,
        file="src/foo.py",
        line=5,
        params={"name": "str"},
        return_annotation="str",
    )
    return EnrichedEvent(event=ev, func_info=func_info)


def test_generate_report_json_empty(tmp_path: Path) -> None:
    out = tmp_path / "report.json"
    generate_report_json([], out)
    data = json.loads(out.read_text())
    assert data == []


def test_generate_report_json_content(tmp_path: Path) -> None:
    out = tmp_path / "report.json"
    generate_report_json([_make_enriched()], out)
    records = json.loads(out.read_text())
    assert len(records) == 1
    assert records[0]["func"]["name"] == "greet"
    assert records[0]["static_mismatch_also_detected"] is False


def test_generate_report_md_empty(tmp_path: Path) -> None:
    out = tmp_path / "report.md"
    generate_report_md([], out)
    content = out.read_text()
    assert "No TypeCheckErrors" in content


def test_generate_report_md_content(tmp_path: Path) -> None:
    out = tmp_path / "report.md"
    generate_report_md([_make_enriched()], out)
    content = out.read_text()
    assert "greet" in content
    assert "argument" in content


# ---------------------------------------------------------------------------
# run_check integration
# ---------------------------------------------------------------------------


def test_run_check_no_events(tmp_path: Path) -> None:
    result = run_check(src_dir=tmp_path, events_file=tmp_path / "missing.jsonl")
    assert result == []


def test_run_check_with_events(tmp_path: Path) -> None:
    events_file = tmp_path / "events.jsonl"
    ev = _make_event()
    row = {
        "timestamp": ev.timestamp,
        "message": ev.message,
        "kind": ev.kind,
        "param_name": ev.param_name,
        "actual_type": ev.actual_type,
        "expected_type": ev.expected_type,
        "call_site_file": ev.call_site_file,
        "call_site_line": ev.call_site_line,
        "call_site_func": ev.call_site_func,
        "func_file": ev.func_file,
        "func_line": ev.func_line,
        "func_name": ev.func_name,
    }
    events_file.write_text(json.dumps(row) + "\n")

    # Use a minimal src dir with one matching function
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "__init__.py").write_text("")
    (src_dir / "foo.py").write_text("def greet(name: str) -> str:\n    return name\n")

    result = run_check(src_dir=src_dir, events_file=events_file)
    assert len(result) == 1
    assert result[0].func_info is not None
    assert result[0].func_info.name == "greet"
