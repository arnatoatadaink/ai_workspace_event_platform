"""Replay Engine: Plotly figure builder for UMAP scatter plots.

Converts a list of TopicPoint objects into a Plotly figure dict (data + layout)
suitable for JSON serialisation and ``react-plotly.js`` rendering.

Usage::

    points = await run_umap(db, backend, UMAPFilter(color_by="session"))
    fig = build_plotly_figure(points, color_by="session")
    # fig is a plain dict — JSON-serialisable
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from src.replay.umap_runner import TopicPoint

_MARKER_SIZEREF_SCALE = 0.5
_MARKER_SIZEMIN = 4
_MARKER_SIZEMAX = 20


def build_plotly_figure(points: list[TopicPoint], color_by: str = "session") -> dict[str, Any]:
    """Build a Plotly figure dict from a list of TopicPoint objects.

    Groups points by ``color_label`` and creates one scatter trace per group.
    Marker size is proportional to topic occurrence count.

    Args:
        points: Output of :func:`~src.replay.umap_runner.run_umap`.
        color_by: Label axis used in the legend (informational only here).

    Returns:
        A plain dict with ``data`` (list of trace dicts) and ``layout`` keys,
        directly usable as ``react-plotly.js`` ``figure`` prop.
    """
    if not points:
        return _empty_figure()

    max_count = max(p.count for p in points)

    groups: dict[str, list[TopicPoint]] = defaultdict(list)
    for p in points:
        groups[p.color_label].append(p)

    traces: list[dict[str, Any]] = []
    for label, group_points in sorted(groups.items()):
        sizes = [_scale_size(p.count, max_count) for p in group_points]
        traces.append(
            {
                "type": "scatter",
                "mode": "markers+text",
                "name": label,
                "x": [p.x for p in group_points],
                "y": [p.y for p in group_points],
                "text": [p.topic for p in group_points],
                "textposition": "top center",
                "hovertemplate": (
                    "<b>%{text}</b><br>"
                    "Count: %{customdata[0]}<br>"
                    "Session: %{customdata[1]}<br>"
                    "First seen: %{customdata[2]}<extra></extra>"
                ),
                "customdata": [
                    [p.count, p.session_id, p.first_seen[:10] if p.first_seen else ""]
                    for p in group_points
                ],
                "marker": {
                    "size": sizes,
                    "opacity": 0.8,
                    "line": {"width": 0.5, "color": "white"},
                },
            }
        )

    layout: dict[str, Any] = {
        "title": {"text": f"Topic Map — color by {color_by}"},
        "xaxis": {"showgrid": False, "zeroline": False, "showticklabels": False},
        "yaxis": {"showgrid": False, "zeroline": False, "showticklabels": False},
        "hovermode": "closest",
        "legend": {"title": {"text": color_by}},
        "plot_bgcolor": "#1a1a2e",
        "paper_bgcolor": "#16213e",
        "font": {"color": "#e0e0e0"},
        "margin": {"l": 20, "r": 20, "t": 40, "b": 20},
    }

    return {"data": traces, "layout": layout}


def _scale_size(count: int, max_count: int) -> int:
    if max_count <= 0:
        return _MARKER_SIZEMIN
    ratio = count / max_count
    return int(_MARKER_SIZEMIN + ratio * (_MARKER_SIZEMAX - _MARKER_SIZEMIN))


def _empty_figure() -> dict[str, Any]:
    return {
        "data": [],
        "layout": {
            "title": {"text": "Topic Map — no data"},
            "annotations": [
                {
                    "text": "No topics found for the selected filter.",
                    "xref": "paper",
                    "yref": "paper",
                    "x": 0.5,
                    "y": 0.5,
                    "showarrow": False,
                    "font": {"size": 14},
                }
            ],
            "plot_bgcolor": "#1a1a2e",
            "paper_bgcolor": "#16213e",
            "font": {"color": "#e0e0e0"},
        },
    }
