"""Точка входа: запуск транспортов и планировщика."""

from __future__ import annotations

import asyncio
import logging

from .app import App
from .scheduler.runner import build_scheduler

logger = logging.getLogger(__name__)


async def _main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    app = App.build()

    if not app.transports:
        raise SystemExit(
            "Не настроен ни один транспорт. Укажите TELEGRAM_BOT_TOKEN в .env"
        )

    scheduler = build_scheduler(app.service, app.settings)
    scheduler.start()

    for transport in app.transports.values():
        await transport.start()
    logger.info("Бот запущен. Транспорты: %s", ", ".join(app.transports))

    stop = asyncio.Event()
    try:
        await stop.wait()  # работаем до отмены (Ctrl+C)
    except (KeyboardInterrupt, asyncio.CancelledError):  # pragma: no cover
        pass
    finally:
        scheduler.shutdown(wait=False)
        for transport in app.transports.values():
            await transport.stop()
        await app.aclose()


def main() -> None:
    try:
        asyncio.run(_main())
    except KeyboardInterrupt:  # pragma: no cover
        pass


if __name__ == "__main__":
    main()
