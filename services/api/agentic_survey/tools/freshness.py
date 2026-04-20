from __future__ import annotations

import argparse
import asyncio
import logging

from agentic_survey.config import get_settings
from agentic_survey.repository import get_repository
from agentic_survey.services.ingestion import run_forever, run_once

logger = logging.getLogger(__name__)


async def _async_main(*, once: bool) -> int:
    settings = get_settings()
    repository = get_repository()

    router = None
    if settings.llm_enabled:
        # Local import: the router wraps LiteLLM which pulls heavy deps.
        from agentic_survey.llm.router import get_litellm_router

        router = get_litellm_router()
    else:
        logger.warning(
            "SURVEY_LLM_ENABLED=false; ingestion worker will skip embedding and fail"
            " sources that reach the embedding step. Set SURVEY_LLM_ENABLED=true"
            " to ingest URL/PDF sources end-to-end."
        )

    if once:
        completed = await run_once(
            repository=repository, router=router, settings=settings
        )
        logger.info("run_once completed=%d", completed)
        return 0

    await run_forever(repository=repository, router=router, settings=settings)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Freshness worker: drain queued knowledge_source rows through"
        " the ingestion pipeline (fetch → extract → chunk → embed → pending_approval)."
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single tick and exit (used by smoke and CI).",
    )
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    try:
        return asyncio.run(_async_main(once=args.once))
    except KeyboardInterrupt:
        logger.info("freshness worker interrupted; exiting cleanly")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
