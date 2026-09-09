"""Print deterministic scenarios through the real engine, without a server."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
import json

from app.config import Settings
from app.connectors.mock import demo_batch
from app.schemas.domain import ContractMapping
from app.services.arbitrage import ArbitrageEngine
from app.services.contract_matching import ContractMatcher


def main() -> None:
    path = Path(__file__).resolve().parents[1] / "docs/contract-mappings.json"
    mappings = [ContractMapping.model_validate(m) for m in json.loads(path.read_text())]
    engine = ArbitrageEngine(Settings(_env_file=None), ContractMatcher(0.85, mappings))
    for op in engine.scan(demo_batch()):
        print(
            f"{op.market_keys!s:52} {op.status:12} gross={op.gross_edge:.4f} "
            f"net={op.net_edge} size={op.available_size} {op.rejection_reason or ''}"
        )


if __name__ == "__main__":
    main()
