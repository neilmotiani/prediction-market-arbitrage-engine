from decimal import Decimal as D

import pytest
from app.database.session import Database
from app.services.paper_trading import PaperExecutionProvider
from conftest import snapshot
from test_quant import mapping


async def test_paper_revalidation_accounting_and_restart(engine, tmp_path):
    db = Database(f"sqlite+aiosqlite:///{tmp_path}/paper.db")
    await db.initialize()
    provider = PaperExecutionProvider(db, engine)
    y, n = snapshot(), snapshot("0.5", "NO")
    books = {s.book_key: s for s in (y, n)}
    op = engine.evaluate(y, n)
    trade = await provider.execute_order(op, books)
    assert provider.free_capital == D(9905)
    assert provider.get_position(y.key) == D(100)
    with pytest.raises(ValueError, match="already consumed"):
        await provider.execute_order(op, books)
    assert not await provider.cancel_order(trade["orders"][0]["id"])
    restored = PaperExecutionProvider(db, engine)
    await restored.restore()
    assert restored.free_capital == provider.free_capital
    with pytest.raises(ValueError, match="already consumed"):
        await restored.execute_order(op, books)
    settled = await restored.settle(trade["id"], {y.key: "NO"})
    assert D(settled["realized_pnl"]) == 5
    assert restored.free_capital == 10005
    await db.close()


async def test_revalidation_prevents_changed_prices(engine, tmp_path):
    db = Database(f"sqlite+aiosqlite:///{tmp_path}/paper.db")
    await db.initialize()
    provider = PaperExecutionProvider(db, engine)
    y, n = snapshot(), snapshot("0.5", "NO")
    op = engine.evaluate(y, n)
    bad = snapshot("0.7", "NO")
    with pytest.raises(ValueError, match="Revalidation failed"):
        await provider.execute_order(op, {y.book_key: y, bad.book_key: bad})
    assert provider.trades == []
    await db.close()


async def test_cross_venue_divergent_settlement_can_lose(engine, tmp_path):
    db = Database(f"sqlite+aiosqlite:///{tmp_path}/paper.db")
    await db.initialize()
    engine.matcher.mappings.append(mapping())
    provider = PaperExecutionProvider(db, engine)
    y = snapshot("0.43", resolution_key="same")
    n = snapshot("0.52", "NO", venue="kalshi", resolution_key="same")
    trade = await provider.execute_order(engine.evaluate(y, n), {s.book_key: s for s in (y, n)})
    result = await provider.settle(trade["id"], {y.key: "NO", n.key: "YES"})
    assert D(result["realized_pnl"]) == -95
    await db.close()
