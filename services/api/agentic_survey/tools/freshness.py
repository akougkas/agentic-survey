import logging
import os
import time

from agentic_survey.config import get_settings

logger = logging.getLogger(__name__)


def run_once() -> None:
    settings = get_settings()
    logger.info(
        "Freshness worker heartbeat: default schedule=%s public_base_url=%s",
        settings.freshness_default_cron,
        settings.public_base_url,
    )


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    poll_seconds = int(os.environ.get("SURVEY_WORKER_POLL_SECONDS", "60"))
    while True:
        run_once()
        time.sleep(poll_seconds)


if __name__ == "__main__":
    main()
