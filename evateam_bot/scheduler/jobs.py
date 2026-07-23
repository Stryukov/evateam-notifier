"""Ручной запуск заданий для проверки:

    python -m evateam_bot.scheduler.jobs --run digest
    python -m evateam_bot.scheduler.jobs --run deadlines
"""

from __future__ import annotations

import argparse
import asyncio
import logging

from ..app import App


async def _run(job: str) -> None:
    app = App.build()
    try:
        if job == "digest":
            count = await app.service.send_daily_digests()
            print(f"Дайджест отправлен: {count} пользователям")
        elif job == "deadlines":
            count = await app.service.send_deadline_reminders()
            print(f"Напоминания о просрочке отправлены: {count} пользователям")
        else:  # pragma: no cover
            raise SystemExit(f"Неизвестное задание: {job}")
    finally:
        await app.aclose()


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description="Ручной запуск заданий бота")
    parser.add_argument("--run", required=True, choices=["digest", "deadlines"])
    args = parser.parse_args()
    asyncio.run(_run(args.run))


if __name__ == "__main__":
    main()
