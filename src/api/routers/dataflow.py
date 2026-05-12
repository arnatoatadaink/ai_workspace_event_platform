"""DataFlow IR API router: exposes static analysis results as a graph."""

from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import APIRouter

from src.analysis.ir_builder import DataFlowIR, build_ir

router = APIRouter(prefix="/dataflow", tags=["dataflow"])

_SRC_DIR = Path("src")
_PROJECT_ROOT = Path(".")


@router.get("/ir", response_model=DataFlowIR)
async def get_dataflow_ir() -> DataFlowIR:
    """Return the data flow graph IR built from static analysis of the src/ directory."""
    return await asyncio.to_thread(build_ir, _SRC_DIR, _PROJECT_ROOT)
