"""Browser-visible HTTP contracts for the app's actual middleware registration."""
import ast
import os
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient

from utils.rate_limiter import RateLimitMiddleware


ORIGIN = "https://dashboard.example.test"


def _middleware_app():
    # Execute the real registration without importing main's database/bootstrap
    # side effects. Requests still exercise the real ASGI middleware classes.
    path = Path(__file__).with_name("main.py")
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    nodes = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "_cors_origins":
            nodes.append(node)
        elif isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "cors_origins"
            for target in node.targets
        ):
            nodes.append(node)
        elif (
            isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Attribute)
            and isinstance(node.value.func.value, ast.Name)
            and node.value.func.value.id == "app"
            and node.value.func.attr == "add_middleware"
        ):
            nodes.append(node)
    app = FastAPI()

    @app.get("/contract")
    def endpoint():
        return {"ok": True}

    namespace = {
        "os": os,
        "app": app,
        "CORSMiddleware": CORSMiddleware,
        "RateLimitMiddleware": RateLimitMiddleware,
    }
    with patch.dict(os.environ, {"CORS_ALLOWED_ORIGINS": ORIGIN}):
        exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), "exec"), namespace)
    return app


def test_allowed_get_keeps_rate_limit_and_cors_headers():
    with patch("utils.rate_limiter.check_rate_limit", return_value=(True, 0, 42)) as check:
        with TestClient(_middleware_app()) as client:
            response = client.get("/contract", headers={"Origin": ORIGIN})
    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert response.headers["access-control-allow-origin"] == ORIGIN
    assert response.headers["x-ratelimit-limit"] == "100"
    assert response.headers["x-ratelimit-remaining"] == "42"
    check.assert_called_once()


def test_denied_get_exposes_429_to_allowed_browser_origin():
    with patch("utils.rate_limiter.check_rate_limit", return_value=(False, 17, 0)) as check:
        with TestClient(_middleware_app()) as client:
            response = client.get("/contract", headers={"Origin": ORIGIN})
    assert response.status_code == 429
    assert response.headers["retry-after"] == "17"
    assert response.headers["access-control-allow-origin"] == ORIGIN
    assert response.headers["access-control-allow-credentials"] == "true"
    check.assert_called_once()


def test_denied_get_does_not_allow_unconfigured_browser_origin():
    with patch("utils.rate_limiter.check_rate_limit", return_value=(False, 17, 0)):
        with TestClient(_middleware_app()) as client:
            response = client.get("/contract", headers={"Origin": "https://unconfigured.example.test"})
    assert response.status_code == 429
    assert "access-control-allow-origin" not in response.headers


def test_allowed_preflight_succeeds_when_request_budget_is_exhausted():
    with patch("utils.rate_limiter.check_rate_limit", return_value=(False, 17, 0)) as check:
        with TestClient(_middleware_app()) as client:
            response = client.options("/contract", headers={
                "Origin": ORIGIN,
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "authorization",
            })
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == ORIGIN
    check.assert_not_called()


def test_unconfigured_preflight_is_rejected_without_spending_request_budget():
    with patch("utils.rate_limiter.check_rate_limit", return_value=(False, 17, 0)) as check:
        with TestClient(_middleware_app()) as client:
            response = client.options("/contract", headers={
                "Origin": "https://unconfigured.example.test",
                "Access-Control-Request-Method": "GET",
            })
    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers
    check.assert_not_called()
