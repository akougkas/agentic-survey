from collections.abc import AsyncIterator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

router = APIRouter(prefix="/turns", tags=["turns"])


async def _sse_keepalive() -> AsyncIterator[str]:
    yield "event: ready\ndata: {\"status\":\"connected\"}\n\n"


@router.get("/stream")
async def stream_turns() -> StreamingResponse:
    return StreamingResponse(_sse_keepalive(), media_type="text/event-stream")
