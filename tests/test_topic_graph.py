"""Tests for src/replay/topic_graph.py — pure helper functions."""

from __future__ import annotations

import pytest

from src.replay.topic_graph import (
    TopicGraphEdge,
    TopicGraphNode,
    _aggregate_rows,
    _build_edges,
    _scale_to_canvas,
)


# ─── _aggregate_rows ──────────────────────────────────────────────────────────


def test_aggregate_rows_empty() -> None:
    sessions, counts = _aggregate_rows([])
    assert sessions == {}
    assert counts == {}


def test_aggregate_rows_single_entry() -> None:
    rows = [{"topic": "Python", "session_id": "s1", "count": 3}]
    sessions, counts = _aggregate_rows(rows)
    assert sessions == {"Python": {"s1"}}
    assert counts == {"Python": 3}


def test_aggregate_rows_same_topic_multiple_sessions() -> None:
    rows = [
        {"topic": "Python", "session_id": "s1", "count": 2},
        {"topic": "Python", "session_id": "s2", "count": 5},
    ]
    sessions, counts = _aggregate_rows(rows)
    assert sessions["Python"] == {"s1", "s2"}
    assert counts["Python"] == 7


def test_aggregate_rows_multiple_topics() -> None:
    rows = [
        {"topic": "Python", "session_id": "s1", "count": 2},
        {"topic": "FastAPI", "session_id": "s1", "count": 1},
        {"topic": "Python", "session_id": "s2", "count": 3},
    ]
    sessions, counts = _aggregate_rows(rows)
    assert sessions["Python"] == {"s1", "s2"}
    assert sessions["FastAPI"] == {"s1"}
    assert counts["Python"] == 5
    assert counts["FastAPI"] == 1


# ─── _build_edges ─────────────────────────────────────────────────────────────


def test_build_edges_empty() -> None:
    assert _build_edges(set(), {}, 1) == []


def test_build_edges_single_topic() -> None:
    assert _build_edges({"Python"}, {"Python": {"s1"}}, 1) == []


def test_build_edges_no_shared_sessions() -> None:
    """Topics in different sessions get no edge."""
    topic_sessions = {"Python": {"s1"}, "FastAPI": {"s2"}}
    edges = _build_edges({"Python", "FastAPI"}, topic_sessions, 1)
    assert edges == []


def test_build_edges_one_shared_session() -> None:
    topic_sessions = {"Python": {"s1", "s2"}, "FastAPI": {"s1", "s3"}}
    edges = _build_edges({"Python", "FastAPI"}, topic_sessions, 1)
    assert len(edges) == 1
    e = edges[0]
    assert e.shared_sessions == 1
    assert e.source == "t:FastAPI"  # sorted alphabetically
    assert e.target == "t:Python"


def test_build_edges_min_shared_sessions_filter() -> None:
    """min_shared_sessions=2 filters out pairs sharing only 1 session."""
    topic_sessions = {"A": {"s1", "s2"}, "B": {"s1", "s3"}, "C": {"s2", "s3"}}
    edges_1 = _build_edges({"A", "B", "C"}, topic_sessions, min_shared_sessions=1)
    edges_2 = _build_edges({"A", "B", "C"}, topic_sessions, min_shared_sessions=2)
    assert len(edges_1) == 3  # every pair shares 1 session
    assert len(edges_2) == 0  # no pair shares 2 sessions


def test_build_edges_two_shared_sessions() -> None:
    topic_sessions = {"X": {"s1", "s2", "s3"}, "Y": {"s1", "s2", "s4"}}
    edges = _build_edges({"X", "Y"}, topic_sessions, min_shared_sessions=2)
    assert len(edges) == 1
    assert edges[0].shared_sessions == 2


def test_build_edges_multiple_pairs() -> None:
    sessions = {
        "A": {"s1", "s2"},
        "B": {"s1", "s2"},
        "C": {"s1"},
    }
    edges = _build_edges({"A", "B", "C"}, sessions, min_shared_sessions=1)
    # A-B share s1,s2; A-C share s1; B-C share s1
    assert len(edges) == 3
    ab = next(e for e in edges if "A" in e.source and "B" in e.target or "B" in e.source and "A" in e.target)
    assert ab.shared_sessions == 2


def test_build_edges_node_not_in_sessions() -> None:
    """Topics missing from topic_sessions get empty set (no crash)."""
    edges = _build_edges({"X", "Y"}, {}, 1)
    assert edges == []


# ─── _scale_to_canvas ─────────────────────────────────────────────────────────


def test_scale_to_canvas_empty() -> None:
    assert _scale_to_canvas([], [], {}, {}) == []


def test_scale_to_canvas_single_point() -> None:
    """Single point placed at canvas center (degenerate range → no division by zero)."""
    nodes = _scale_to_canvas(
        ["Python"],
        [(1.0, 2.0)],
        {"Python": 5},
        {"Python": {"s1"}},
    )
    assert len(nodes) == 1
    n = nodes[0]
    assert n.id == "t:Python"
    assert n.label == "Python"
    assert n.count == 5
    assert n.session_count == 1
    # Single point: range is 0, so placed at padding * canvas offset
    assert isinstance(n.x, float)
    assert isinstance(n.y, float)


def test_scale_to_canvas_two_points() -> None:
    nodes = _scale_to_canvas(
        ["A", "B"],
        [(0.0, 0.0), (10.0, 5.0)],
        {"A": 1, "B": 2},
        {"A": {"s1"}, "B": {"s1", "s2"}},
    )
    assert len(nodes) == 2
    a = next(n for n in nodes if n.label == "A")
    b = next(n for n in nodes if n.label == "B")
    # A is min, B is max → B has larger x and y
    assert b.x > a.x
    assert b.y > a.y
    assert b.session_count == 2
    assert a.session_count == 1


def test_scale_to_canvas_ids_prefixed() -> None:
    nodes = _scale_to_canvas(
        ["Python", "FastAPI"],
        [(0.0, 0.0), (1.0, 1.0)],
        {"Python": 3, "FastAPI": 2},
        {"Python": {"s1"}, "FastAPI": {"s1"}},
    )
    ids = {n.id for n in nodes}
    assert "t:Python" in ids
    assert "t:FastAPI" in ids


def test_scale_to_canvas_coords_in_bounds() -> None:
    """All scaled coords must fall within canvas dimensions."""
    from src.replay.topic_graph import _CANVAS_H, _CANVAS_W

    import random
    random.seed(0)
    topics = [f"topic_{i}" for i in range(20)]
    raw = [(random.uniform(-5, 15), random.uniform(-3, 8)) for _ in topics]
    counts = {t: random.randint(1, 10) for t in topics}
    sessions = {t: {f"s{random.randint(0, 3)}"} for t in topics}

    nodes = _scale_to_canvas(topics, raw, counts, sessions)
    for n in nodes:
        assert 0 <= n.x <= _CANVAS_W, f"{n.label}: x={n.x} out of [0, {_CANVAS_W}]"
        assert 0 <= n.y <= _CANVAS_H, f"{n.label}: y={n.y} out of [0, {_CANVAS_H}]"
