"""Path helpers for Claude CLI transcript files.

Transcript files live at:
    ~/.claude/projects/<slug>/<session_id>.jsonl

where <slug> is the project CWD with every non-alphanumeric character replaced
by a hyphen (matching Claude Code's own directory-naming convention).
"""

from __future__ import annotations

import os
import re
from pathlib import Path


def cwd_to_claude_project_dir(cwd: str | Path | None = None) -> Path:
    """Return ~/.claude/projects/<slug>/ derived from *cwd* (defaults to os.getcwd())."""
    resolved = str(Path(cwd).resolve() if cwd else Path(os.getcwd()).resolve())
    slug = re.sub(r"[^a-zA-Z0-9]", "-", resolved)
    return Path.home() / ".claude" / "projects" / slug


def transcript_path_for_session(session_id: str, cwd: str | Path | None = None) -> Path:
    """Return the expected transcript path for *session_id* in the given project dir."""
    return cwd_to_claude_project_dir(cwd) / f"{session_id}.jsonl"
