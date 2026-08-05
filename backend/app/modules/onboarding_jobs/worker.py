from __future__ import annotations

import asyncio
import logging
import signal

from app.core.config import settings

from .service import run_worker


logger = logging.getLogger(__name__)


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    logger.info("Starting onboarding worker commit=%s", settings.APP_COMMIT_SHA)
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop_event.set)
    await run_worker(stop_event)


if __name__ == "__main__":
    asyncio.run(main())
