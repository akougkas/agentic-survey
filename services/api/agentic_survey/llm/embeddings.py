from dataclasses import dataclass


@dataclass(slots=True)
class EmbeddingRequest:
    text: str
    model: str


class EmbeddingClient:
    async def embed(self, request: EmbeddingRequest) -> list[float]:
        _ = request
        return []
