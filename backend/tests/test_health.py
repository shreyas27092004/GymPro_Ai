import pytest
from httpx import AsyncClient
from app.settings import settings
from app.ratelimit import InMemoryRateLimiter


@pytest.mark.asyncio
async def test_health_liveness(client: AsyncClient):
    """Liveness probe test."""
    response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"


@pytest.mark.asyncio
async def test_ready_readiness(client: AsyncClient):
    """Readiness probe test."""
    response = await client.get("/ready")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ready"
    assert "environment" in data
    assert "database" in data
    assert "rabbitmq" in data


def test_settings_loaded():
    """Verify settings loaded with required security configurations."""
    assert settings.jwt_private_key != ""
    assert settings.jwt_public_key != ""
    assert settings.token_hmac_secret != ""
    assert settings.payments_mode in ["mock", "razorpay", "disabled"]


def test_rate_limiter_sliding_window():
    """Verify in-process sliding window rate limiter."""
    limiter = InMemoryRateLimiter()
    key = "test_user_key"
    limit = 3
    window_s = 1.0

    # 3 calls should pass
    assert limiter.check(key, limit, window_s) is True
    assert limiter.check(key, limit, window_s) is True
    assert limiter.check(key, limit, window_s) is True

    # 4th call within same window should fail
    assert limiter.check(key, limit, window_s) is False


@pytest.mark.asyncio
async def test_metrics_prometheus_and_json(client: AsyncClient):
    """Verify Prometheus exposition and JSON metrics endpoints."""
    # Hit health to generate metrics
    res = await client.get("/health")
    assert "x-trace-id" in res.headers or "X-Trace-Id" in res.headers

    # Check /metrics text exposition
    metrics_res = await client.get("/metrics")
    assert metrics_res.status_code == 200
    assert "gympro_requests_total" in metrics_res.text

    # Check /metrics/json
    json_res = await client.get("/metrics/json")
    assert json_res.status_code == 200
    summary = json_res.json()
    assert "requests_total" in summary
    assert "status_distribution" in summary

