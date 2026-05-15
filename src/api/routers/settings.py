"""Settings API: summarizer backend configuration.

Endpoints
---------
GET  /settings/summarizer        Return current config (api_key masked).
PUT  /settings/summarizer        Validate, persist, and hot-swap the backend.
POST /settings/summarizer/test   Test-connect with provided config (no persist).
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from src.api.settings_store import (
    BackendKind,
    SummarizerSettings,
    build_backend,
    load_summarizer_settings,
    mask_api_key,
    save_summarizer_settings,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/settings", tags=["settings"])


class SummarizerSettingsResponse(BaseModel):
    backend: BackendKind
    base_url: str
    api_key_masked: str
    model: str


class SummarizerSettingsPut(BaseModel):
    backend: Optional[BackendKind] = None
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    model: Optional[str] = None


class TestConnectionRequest(BaseModel):
    backend: BackendKind
    base_url: str = "http://192.168.2.104:52624/v1"
    api_key: str = "lm"
    model: str = "gemma-4-31b-it@q6_k"


class TestConnectionResponse(BaseModel):
    ok: bool
    model_used: str
    latency_ms: float
    error: Optional[str] = None


def _to_response(s: SummarizerSettings) -> SummarizerSettingsResponse:
    return SummarizerSettingsResponse(
        backend=s.backend,
        base_url=s.base_url,
        api_key_masked=mask_api_key(s.api_key),
        model=s.model,
    )


@router.get("/summarizer", response_model=SummarizerSettingsResponse)
async def get_summarizer_settings() -> SummarizerSettingsResponse:
    """Return the current summarizer configuration.  API key is masked."""
    return _to_response(load_summarizer_settings())


@router.put("/summarizer", response_model=SummarizerSettingsResponse)
async def put_summarizer_settings(
    body: SummarizerSettingsPut,
    request: Request,
) -> SummarizerSettingsResponse:
    """Update summarizer settings, validate by constructing the backend, then persist.

    Fields omitted from the request body keep their current values.
    Setting ``api_key`` to an empty string clears the stored key.
    """
    current = load_summarizer_settings()

    updated = SummarizerSettings(
        backend=body.backend if body.backend is not None else current.backend,
        base_url=body.base_url if body.base_url is not None else current.base_url,
        api_key=body.api_key if body.api_key is not None else current.api_key,
        model=body.model if body.model is not None else current.model,
    )

    try:
        new_backend = build_backend(updated)
    except ImportError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Required package not installed: {exc}",
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Failed to construct backend: {exc}",
        ) from exc

    save_summarizer_settings(updated)

    # Hot-swap runtime backend.
    request.app.state.summarizer = new_backend
    pipeline = getattr(request.app.state, "pipeline", None)
    if pipeline is not None:
        pipeline.update_summarizer(new_backend)

    logger.info(
        "Summarizer updated: backend=%s model=%s", updated.backend, updated.model
    )
    return _to_response(updated)


@router.post("/summarizer/test", response_model=TestConnectionResponse)
async def test_summarizer_connection(body: TestConnectionRequest) -> TestConnectionResponse:
    """Test connectivity and model availability without persisting changes.

    Sends a minimal summarization request and returns latency.
    """
    import time

    test_settings = SummarizerSettings(
        backend=body.backend,
        base_url=body.base_url,
        api_key=body.api_key,
        model=body.model,
    )

    try:
        backend = build_backend(test_settings)
    except ImportError as exc:
        return TestConnectionResponse(
            ok=False,
            model_used=body.model,
            latency_ms=0.0,
            error=f"Required package not installed: {exc}",
        )
    except Exception as exc:
        return TestConnectionResponse(
            ok=False,
            model_used=body.model,
            latency_ms=0.0,
            error=str(exc),
        )

    from src.replay.summarizer import SummarizerBackend

    if not isinstance(backend, SummarizerBackend):
        return TestConnectionResponse(
            ok=False,
            model_used=body.model,
            latency_ms=0.0,
            error="Backend does not implement SummarizerBackend protocol",
        )

    try:
        t0 = time.monotonic()
        await backend.generate("User: Hello\nAssistant: Hi there.")  # type: ignore[attr-defined]
        latency_ms = (time.monotonic() - t0) * 1000
        return TestConnectionResponse(
            ok=True,
            model_used=body.model,
            latency_ms=round(latency_ms, 1),
        )
    except Exception as exc:
        return TestConnectionResponse(
            ok=False,
            model_used=body.model,
            latency_ms=0.0,
            error=str(exc),
        )
