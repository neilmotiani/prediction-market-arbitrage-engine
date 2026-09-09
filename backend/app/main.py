import json
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.config import Settings
from app.database.session import Database
from app.schemas.domain import now
from app.services.market_data import ResearchRuntime


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        data = {
            "timestamp": now().isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
        }
        for key in ("connector", "snapshots", "checks", "detection_ms"):
            if hasattr(record, key):
                data[key] = getattr(record, key)
        if record.exc_info:
            data["exception"] = self.formatException(record.exc_info)
        return json.dumps(data)


def create_app(settings: Settings | None = None) -> FastAPI:
    config = settings or Settings()
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    logger = logging.getLogger("app")
    logger.handlers = [handler]
    logger.setLevel(logging.INFO)
    logger.propagate = False

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        rt = ResearchRuntime(config, Database(config.database_url))
        application.state.runtime = rt
        await rt.start()
        try:
            yield
        finally:
            await rt.stop()

    application = FastAPI(
        title="Prediction Market Arbitrage Engine", version="0.1.0", lifespan=lifespan
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=config.cors_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )
    application.include_router(router)
    return application


app = create_app()
