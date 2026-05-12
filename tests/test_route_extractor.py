"""Tests for src/analysis/route_extractor.py."""

import pytest

from src.analysis.route_extractor import RouteInfo, extract_from_source

_ROUTER_SOURCE = '''
from fastapi import APIRouter
router = APIRouter()

@router.get("/items")
async def list_items():
    pass

@router.post("/items", response_model=ItemResponse, tags=["items"])
async def create_item():
    pass

@router.get("/items/{item_id}", response_model=list[ItemResponse])
async def get_item(item_id: str):
    pass
'''


def test_basic_get_route() -> None:
    routes = extract_from_source(_ROUTER_SOURCE, "test.py")
    get_routes = [r for r in routes if r.method == "GET" and r.path == "/items"]
    assert len(get_routes) == 1
    r = get_routes[0]
    assert r.handler_name == "list_items"
    assert r.response_model is None
    assert r.tags == []


def test_post_with_response_model_and_tags() -> None:
    routes = extract_from_source(_ROUTER_SOURCE, "test.py")
    post = next(r for r in routes if r.method == "POST")
    assert post.path == "/items"
    assert post.response_model == "ItemResponse"
    assert post.tags == ["items"]


def test_path_parameter() -> None:
    routes = extract_from_source(_ROUTER_SOURCE, "test.py")
    r = next(r for r in routes if "{item_id}" in r.path)
    assert r.method == "GET"
    assert r.handler_name == "get_item"


def test_list_response_model() -> None:
    routes = extract_from_source(_ROUTER_SOURCE, "test.py")
    r = next(r for r in routes if "{item_id}" in r.path)
    assert r.response_model == "list[ItemResponse]"


def test_non_http_decorator_skipped() -> None:
    source = '''
@app.on_event("startup")
async def startup():
    pass

@pytest.fixture
def my_fixture():
    pass
'''
    assert extract_from_source(source, "test.py") == []


def test_sync_function_routes() -> None:
    source = '''
@router.get("/sync")
def sync_handler():
    pass
'''
    routes = extract_from_source(source, "test.py")
    assert len(routes) == 1
    assert routes[0].handler_name == "sync_handler"


def test_all_http_methods() -> None:
    source = '''
@router.get("/r")
async def h_get(): pass

@router.post("/r")
async def h_post(): pass

@router.put("/r/{id}")
async def h_put(id: str): pass

@router.patch("/r/{id}")
async def h_patch(id: str): pass

@router.delete("/r/{id}")
async def h_delete(id: str): pass
'''
    routes = extract_from_source(source, "test.py")
    methods = {r.method for r in routes}
    assert methods == {"GET", "POST", "PUT", "PATCH", "DELETE"}


def test_file_and_line_populated() -> None:
    routes = extract_from_source(_ROUTER_SOURCE, "routers/items.py")
    assert all(r.file == "routers/items.py" for r in routes)
    assert all(r.line > 0 for r in routes)


def test_syntax_error_returns_empty() -> None:
    assert extract_from_source("def broken(: pass", "bad.py") == []


def test_empty_source() -> None:
    assert extract_from_source("", "empty.py") == []
