from __future__ import annotations

import asyncio
import logging
import signal

from sqlalchemy.orm import configure_mappers

from app.core.config import settings
from app.db import base as _model_registry  # noqa: F401

from .service import run_worker


logger = logging.getLogger(__name__)


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    # The worker is a standalone entrypoint, so it must load the complete model
    # registry before SQLAlchemy resolves relationships or foreign keys. Fail
    # during startup if the registry is incomplete, before emitting a heartbeat.
    configure_mappers()

    logger.info("Starting onboarding worker commit=%s", settings.APP_COMMIT_SHA)
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop_event.set)
    await run_worker(stop_event)


if __name__ == "__main__":
    asyncio.run(main())
