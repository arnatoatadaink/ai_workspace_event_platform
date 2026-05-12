"""Plugin management endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from src.api.plugin_catalog import PluginEntry, build_live_catalog

router = APIRouter(tags=["plugins"])


class CheckUpdateResponse(BaseModel):
    name: str
    installed_version: str | None
    latest_version: str
    update_available: bool


@router.get("/plugins", response_model=list[PluginEntry])
async def list_plugins(request: Request) -> list[PluginEntry]:
    """Return all known plugins with live status."""
    adapters: dict = getattr(request.app.state, "adapters", {})
    return build_live_catalog(set(adapters.keys()))


@router.post("/plugins/{name}/check-update", response_model=CheckUpdateResponse)
async def check_plugin_update(name: str, request: Request) -> CheckUpdateResponse:
    """Check whether a newer version of the plugin is available.

    Currently returns catalog data only (no network call).
    Future: fetch from package registry.
    """
    adapters: dict = getattr(request.app.state, "adapters", {})
    catalog = build_live_catalog(set(adapters.keys()))
    entry = next((e for e in catalog if e.name == name), None)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"Plugin '{name}' not found")
    return CheckUpdateResponse(
        name=entry.name,
        installed_version=entry.installed_version,
        latest_version=entry.latest_version,
        update_available=(
            entry.installed_version is not None and entry.installed_version != entry.latest_version
        ),
    )
