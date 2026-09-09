"""Black-box Compose smoke: API data, persistence, paper fill, settlement, frontend HTML."""

import json
import time
from urllib.request import Request, urlopen


def call(path: str, body: dict | None = None):
    request = Request(
        "http://localhost:8000" + path,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json"},
    )
    with urlopen(request, timeout=10) as response:
        return json.load(response)


def main() -> None:
    for _ in range(30):
        health = call("/health")
        if health["feed_ready"]:
            break
        time.sleep(1)
    assert health["mode"] == "mock" and health["execution"] == "paper"
    markets = call("/markets")
    assert len(markets) == 6 and all(m["snapshots"] for m in markets)
    ops = call("/opportunities")
    assert any(o["status"] == "theoretical" for o in ops)
    assert any(o["status"] == "rejected" for o in ops)
    assert any(o["status"] == "executable" for o in ops)
    trade = call("/simulation/run", {})
    assert len(trade["orders"]) == 2 and float(trade["expected_pnl"]) > 0
    settled = call(
        "/simulation/run",
        {
            "action": "settle",
            "trade_id": trade["id"],
            "resolutions": {key: "YES" for key in trade["market_keys"]},
        },
    )
    assert settled["realized_pnl"] == trade["expected_pnl"]
    assert any(t["id"] == trade["id"] for t in call("/trades"))
    assert call("/markets/polymarket:eth-edge")["history"]
    with urlopen("http://localhost:3000", timeout=15) as response:
        html = response.read().decode()
    assert "Opportunity monitor" in html and "Prediction Market Arbitrage Engine" in html
    print(
        "PASS: 6 markets; all classifications; paired paper fill; settlement; history; dashboard HTML"
    )
    print("Browser rendering and interactive chart behavior require separate browser QA.")


if __name__ == "__main__":
    main()
