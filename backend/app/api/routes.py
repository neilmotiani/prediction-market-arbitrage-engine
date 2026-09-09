import asyncio
from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    Request,
    WebSocket,
    WebSocketDisconnect,
)
from sqlalchemy import select

from app.models.entities import MappingRecord, OpportunityRecord, SnapshotRecord
from app.schemas.domain import ContractMapping, SimulationRequest
from app.services.market_data import ResearchRuntime

router = APIRouter()


def runtime(request: Request) -> ResearchRuntime:
    return request.app.state.runtime


Runtime = Annotated[ResearchRuntime, Depends(runtime)]


@router.get("/health")
async def health(rt: Runtime) -> dict:
    async with rt.db.sessions() as session:
        from sqlalchemy import text

        await session.execute(text("SELECT 1"))
    metrics = rt.metrics()
    return {
        "status": "ok",
        "mode": rt.settings.mode,
        "execution": "paper",
        "feed_ready": bool(rt.books),
        "connections": metrics["connections"],
    }


@router.get("/markets")
async def markets(rt: Runtime) -> list[dict]:
    grouped: dict[str, dict] = {}
    for s in rt.books.values():
        record = grouped.setdefault(
            s.key,
            {
                "id": s.key,
                "title": s.title,
                "venue": s.venue,
                "market_id": s.market_id,
                "snapshots": [],
            },
        )
        record["snapshots"].append(s.model_dump(mode="json"))
    return list(grouped.values())


@router.get("/markets/{market_id}")
async def market_detail(market_id: str, rt: Runtime) -> dict:
    books = [s.model_dump(mode="json") for s in rt.books.values() if s.key == market_id]
    if not books:
        raise HTTPException(404, "Market not found; use the venue-qualified ID from /markets")
    async with rt.db.sessions() as session:
        records = (
            await session.scalars(
                select(SnapshotRecord)
                .where(SnapshotRecord.market_key == market_id)
                .order_by(SnapshotRecord.timestamp.desc())
                .limit(240)
            )
        ).all()
    return {"id": market_id, "snapshots": books, "history": [r.payload for r in reversed(records)]}


@router.get("/opportunities")
async def opportunities(
    rt: Runtime,
    min_edge: float | None = Query(default=None, ge=-2, le=1),
    history: bool = False,
    limit: int = Query(default=100, ge=1, le=500),
) -> list[dict]:
    if history:
        async with rt.db.sessions() as session:
            records = (
                await session.scalars(
                    select(OpportunityRecord)
                    .order_by(OpportunityRecord.timestamp.desc())
                    .limit(limit)
                )
            ).all()
        data = [r.payload for r in records]
    else:
        data = [o.model_dump(mode="json") for o in rt.opportunities]
    return [
        o
        for o in data
        if min_edge is None or (o["net_edge"] is not None and float(o["net_edge"]) >= min_edge)
    ]


@router.get("/trades")
async def trades(rt: Runtime, limit: int = Query(default=100, ge=1, le=500)) -> list[dict]:
    return list(reversed(rt.paper.trades[-limit:]))


@router.get("/metrics")
async def metrics(rt: Runtime) -> dict:
    return rt.metrics()


@router.get("/contract-mappings")
async def mappings(rt: Runtime) -> list[ContractMapping]:
    return rt.matcher.mappings


@router.post("/contract-mappings", status_code=201)
async def create_mapping(mapping: ContractMapping, rt: Runtime) -> ContractMapping:
    async with rt.lock:
        keys = {s.key: s for s in rt.books.values()}
        left, right = keys.get(mapping.left_key), keys.get(mapping.right_key)
        if left is None or right is None or left.venue == right.venue:
            raise HTTPException(422, "Select two monitored contracts on distinct venues")
        if (
            left.resolution_key != right.resolution_key
            or left.resolution_key != mapping.resolution_key
        ):
            raise HTTPException(
                422, "Resolution keys must match the adapter's configured settlement definitions"
            )
        identity = "|".join(sorted([mapping.left_key, mapping.right_key]))
        async with rt.db.sessions() as session:
            await session.merge(MappingRecord(id=identity, payload=mapping.model_dump(mode="json")))
            await session.commit()
        rt.matcher.mappings = [
            m
            for m in rt.matcher.mappings
            if {m.left_key, m.right_key} != {mapping.left_key, mapping.right_key}
        ]
        rt.matcher.mappings.append(mapping)
    return mapping


@router.post("/simulation/run")
async def simulate(body: SimulationRequest, rt: Runtime) -> dict:
    async with rt.lock:
        try:
            if body.action == "settle":
                if not body.trade_id:
                    raise ValueError("trade_id is required")
                result = await rt.paper.settle(body.trade_id, body.resolutions)
            else:
                candidates = [
                    o
                    for o in rt.opportunities
                    if o.status == "executable"
                    and (not body.opportunity_id or o.id == body.opportunity_id)
                ]
                candidates.sort(key=lambda o: o.net_edge or 0, reverse=True)
                if not candidates:
                    raise ValueError("No current executable opportunity matches this request")
                result = await rt.paper.execute_order(candidates[0], rt.books)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        rt.publish({"type": "trade", "data": result, "metrics": rt.metrics()})
        return result


@router.websocket("/ws/opportunities")
async def opportunity_stream(websocket: WebSocket) -> None:
    rt: ResearchRuntime = websocket.app.state.runtime
    origin = websocket.headers.get("origin")
    if origin and origin not in rt.settings.cors_origins:
        await websocket.close(code=1008)
        return
    await websocket.accept()
    queue: asyncio.Queue = asyncio.Queue(maxsize=2)
    rt.subscribers.add(queue)
    try:
        await websocket.send_json(
            {
                "type": "opportunities",
                "data": [o.model_dump(mode="json") for o in rt.opportunities],
                "metrics": rt.metrics(),
            }
        )
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=10)
            except TimeoutError:
                event = {"type": "heartbeat", "metrics": rt.metrics()}
            await websocket.send_json(event)
    except (WebSocketDisconnect, RuntimeError, OSError):
        pass
    finally:
        rt.subscribers.discard(queue)
