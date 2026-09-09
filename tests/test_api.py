import time

import pytest
from app.config import Settings
from app.main import create_app
from fastapi.testclient import TestClient


def config(tmp_path):
    return Settings(
        _env_file=None, database_url=f"sqlite+aiosqlite:///{tmp_path}/test.db", poll_interval=0.2
    )


def ready(client):
    for _ in range(100):
        data = client.get("/opportunities").json()
        if data:
            return data
        time.sleep(0.02)
    pytest.fail("Mock feed did not initialize")


def test_api_feed_persistence_execution_and_settlement(tmp_path):
    settings = config(tmp_path)
    with TestClient(create_app(settings)) as client:
        ops = ready(client)
        assert client.get("/health").json()["execution"] == "paper"
        markets = client.get("/markets").json()
        assert len(markets) == 6
        assert client.get("/markets/polymarket:eth-edge").json()["history"]
        assert client.get("/markets/unknown").status_code == 404
        assert all(
            float(o["net_edge"]) >= 0.01 for o in client.get("/opportunities?min_edge=.01").json()
        )
        assert client.get("/opportunities?history=true").json()
        op = next(o for o in ops if o["status"] == "executable")
        response = client.post("/simulation/run", json={"opportunity_id": op["id"]})
        assert response.status_code == 200, response.text
        trade = response.json()
        assert len(trade["orders"]) == 2
        assert float(trade["expected_pnl"]) > 0
        assert client.post("/simulation/run", json={"opportunity_id": op["id"]}).status_code == 409
        settled = client.post(
            "/simulation/run",
            json={
                "action": "settle",
                "trade_id": trade["id"],
                "resolutions": {k: "YES" for k in trade["market_keys"]},
            },
        )
        assert settled.status_code == 200
        assert float(settled.json()["realized_pnl"]) == pytest.approx(float(trade["expected_pnl"]))
        assert client.get("/metrics").json()["snapshots_processed"] >= 12
        assert (
            client.post(
                "/simulation/run",
                json={
                    "action": "settle",
                    "trade_id": trade["id"],
                    "resolutions": {k: "YES" for k in trade["market_keys"]},
                },
            ).status_code
            == 409
        )
    with TestClient(create_app(settings)) as client:
        ready(client)
        assert client.get("/trades").json()[0]["id"] == trade["id"]
        assert float(client.get("/metrics").json()["simulated_pnl"]) > 0


def test_websocket_and_mapping_validation(tmp_path):
    with TestClient(create_app(config(tmp_path))) as client:
        ready(client)
        with client.websocket_connect("/ws/opportunities") as ws:
            event = ws.receive_json()
            assert event["type"] == "opportunities" and len(event["data"]) == 8
        mapping = client.get("/contract-mappings").json()[0]
        assert client.post("/contract-mappings", json=mapping).status_code == 201
        assert (
            client.post(
                "/contract-mappings", json={**mapping, "same_resolution": False}
            ).status_code
            == 422
        )
        assert (
            client.post(
                "/contract-mappings", json={**mapping, "resolution_key": "invalid"}
            ).status_code
            == 422
        )


def test_no_live_credentials_is_healthful_but_not_ready(tmp_path):
    settings = config(tmp_path)
    settings.mode = "live"
    with TestClient(create_app(settings)) as client:
        assert client.get("/health").json()["feed_ready"] is False
        assert client.get("/markets").json() == []
        assert client.post("/simulation/run", json={}).status_code == 409
