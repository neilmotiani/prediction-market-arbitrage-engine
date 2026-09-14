"""Explain the scan funnel without treating every rejection as a missed profit."""

from collections import Counter
from typing import Any

from app.schemas.domain import Opportunity


def scan_diagnostics(opportunities: list[Opportunity]) -> dict[str, Any]:
    quoted = [o for o in opportunities if o.yes_price is not None and o.no_price is not None]
    gross = [o for o in quoted if o.gross_edge > 0]
    net = [o for o in gross if o.net_edge is not None and o.net_edge > 0]
    reasons: Counter[str] = Counter()
    for op in opportunities:
        reasons.update(filter(None, (op.rejection_reason or "").split("; ")))
    closest = sorted(
        quoted, key=lambda o: o.net_edge if o.net_edge is not None else -10, reverse=True
    )[:5]
    return {
        "checks": len(opportunities),
        "quoted_pairs": len(quoted),
        "positive_gross": len(gross),
        "positive_net": len(net),
        "executable": sum(o.status == "executable" for o in opportunities),
        "cross_venue_pairs": sum(o.strategy_type == "cross_venue" for o in opportunities),
        "rejection_reasons": dict(reasons.most_common()),
        "closest_pairs": [
            {
                "market": o.market,
                "gross_edge": str(o.gross_edge),
                "net_edge": str(o.net_edge) if o.net_edge is not None else None,
                "size": str(o.available_size),
                "rejection_reason": o.rejection_reason,
            }
            for o in closest
        ],
    }
