from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from app.schemas.domain import MarketSnapshot


class VenueConnector(ABC):
    """Read-only interface. Batches keep complementary snapshots together."""

    @abstractmethod
    def stream(self) -> AsyncIterator[list[MarketSnapshot]]:
        raise NotImplementedError
