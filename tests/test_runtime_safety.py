from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from app.config import Settings
from app.connectors.mock import demo_batch
from app.database.session import Database
from app.main import create_app
from app.services.market_data import ResearchRuntime
from fastapi.testclient import TestClient
from test_api import ready


async def test_stopped_feed_loses_executable_status(tmp_path):
    settings = Settings(_env_file=None, database_url=f"sqlite+aiosqlite:///{tmp_path}/stale.db")
    rt = ResearchRuntime(settings, Database(settings.database_url), connector_factory=lambda: [])
    await rt.start()
    await rt.ingest(demo_batch())
    assert any(o.status == "executable" for o in rt.current_opportunities())
    for op in rt.opportunities:
        op.snapshots = [
            s.model_copy(update={"timestamp": s.timestamp - timedelta(seconds=60)})
            for s in op.snapshots
        ]
    assert all(o.status != "executable" for o in rt.current_opportunities())
    assert rt.metrics()["executable_opportunities"] == 0
    await rt.stop()


async def test_subscriber_backpressure_keeps_latest(tmp_path):
    import asyncio

    settings = Settings(_env_file=None, database_url=f"sqlite+aiosqlite:///{tmp_path}/queue.db")
    rt = ResearchRuntime(settings, Database(settings.database_url))
    queue = asyncio.Queue(maxsize=2)
    rt.subscribers.add(queue)
    for i in range(3):
        rt.publish({"sequence": i})
    assert (await queue.get())["sequence"] == 1
    assert (await queue.get())["sequence"] == 2
    await rt.db.close()


def test_concurrent_simulations_do_not_double_fill(tmp_path):
    settings = Settings(
        _env_file=None, database_url=f"sqlite+aiosqlite:///{tmp_path}/race.db", poll_interval=100
    )
    with TestClient(create_app(settings)) as client:
        op = next(o for o in ready(client) if o["status"] == "executable")
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(
                executor.map(
                    lambda _: (
                        client.post(
                            "/simulation/run", json={"opportunity_id": op["id"]}
                        ).status_code
                    ),
                    range(2),
                )
            )
        assert sorted(results) == [200, 409]
        assert len(client.get("/trades").json()) == 1


def test_drawer_id_survives_feed_refresh(tmp_path):
    settings = Settings(
        _env_file=None, database_url=f"sqlite+aiosqlite:///{tmp_path}/drawer.db", poll_interval=100
    )
    with TestClient(create_app(settings)) as client:
        op = next(o for o in ready(client) if o["status"] == "executable")
        client.portal.call(client.app.state.runtime.ingest, demo_batch(1))
        assert all(o["id"] != op["id"] for o in client.get("/opportunities").json())
        assert client.post("/simulation/run", json={"opportunity_id": op["id"]}).status_code == 200
        client.portal.call(client.app.state.runtime.ingest, demo_batch(2))
        assert client.post("/simulation/run", json={"opportunity_id": op["id"]}).status_code == 409


async def test_failed_database_commit_does_not_mutate_paper_ledger(engine, tmp_path):
    from app.services.paper_trading import PaperExecutionProvider
    from conftest import snapshot

    db = Database(f"sqlite+aiosqlite:///{tmp_path}/missing-schema.db")
    provider = PaperExecutionProvider(db, engine)
    y, n = snapshot(), snapshot("0.5", "NO")
    from sqlalchemy.exc import OperationalError

    with pytest.raises(OperationalError):
        await provider.execute_order(engine.evaluate(y, n), {s.book_key: s for s in (y, n)})
    assert provider.trades == [] and provider.consumed == set()
    assert provider.free_capital == engine.settings.paper_capital
    await db.close()
