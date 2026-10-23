from fastapi.testclient import TestClient

from app import app


def test_health_reports_execution_disabled():
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["trading_execution_enabled"] is False


def test_config_is_signals_only():
    with TestClient(app) as client:
        response = client.get("/api/config")

    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "signals_only"
    assert payload["paper_only"] is True
    assert payload["execution_enabled"] is False


def test_invalid_candidate_symbol_is_rejected_before_market_request():
    with TestClient(app) as client:
        response = client.get("/api/candidate/BTC-USDT")

    assert response.status_code == 400
