import pytest
from unittest.mock import patch
from httpx import AsyncClient, ASGITransport
from app.main import create_app

ENV_VARS = {"OPENAI_API_KEY": "test-key", "ADMIN_API_KEY": "test-admin"}


@pytest.fixture
def app():
    with patch.dict("os.environ", ENV_VARS):
        return create_app()


@pytest.mark.asyncio
async def test_classify_validates_short_input(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/v1/classify", json={"description": "짧은"})
        assert resp.status_code == 422


@pytest.mark.asyncio
async def test_classify_validates_top_n(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/v1/classify", json={"description": "리튬이온 배터리 양극재 제조 기술", "top_n": 25})
        assert resp.status_code == 422


@pytest.mark.asyncio
async def test_refresh_requires_admin_key(app):
    transport = ASGITransport(app=app)
    with patch.dict("os.environ", ENV_VARS):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/v1/data/refresh")
            assert resp.status_code == 422
            resp = await client.post("/api/v1/data/refresh", headers={"X-Admin-Key": "wrong"})
            assert resp.status_code == 403


@pytest.mark.asyncio
async def test_health_endpoint(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/health")
        assert resp.status_code == 200
