from __future__ import annotations

import pytest
import respx
from fastapi.testclient import TestClient

from src.app.main import create_app


@pytest.fixture
def app():
    """Fresh app instance per test."""
    return create_app()


@pytest.fixture
def client(app):
    """Bypass response caching so each test exercises its outbound mocks."""
    with TestClient(
        app,
        raise_server_exceptions=False,
        headers={"Cache-Control": "no-cache"},
    ) as c:
        yield c


@pytest.fixture
def mock_http():
    """Intercept all outbound httpx calls; fail on unexpected network access."""
    with respx.mock(assert_all_mocked=True) as router:
        yield router
