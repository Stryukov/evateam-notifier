"""Ручной запуск заданий для проверки:

    python -m evateam_bot.scheduler.jobs --run digest
    python -m evateam_bot.scheduler.jobs --run deadlines
    python -m evateam_bot.scheduler.jobs --run summary --no-send
"""

from __future__ import annotations

import argparse
import asyncio
import logging

from ..app import App
from ..reports import write_report_files


async def _run(job: str, *, no_send: bool = False, chat: str | None = None) -> None:
    app = App.build()
    try:
        if job == "digest":
            count = await app.service.send_daily_digests()
            print(f"Дайджест отправлен: {count} пользователям")
        elif job == "deadlines":
            count = await app.service.send_deadline_reminders()
            print(f"Напоминания о просрочке отправлены: {count} пользователям")
        elif job == "evening":
            count = await app.service.send_evening_reminders()
            print(f"Вечерние напоминания отправлены: {count} пользователям")
        elif job == "summary":
            await _run_summary(app, no_send=no_send, chat=chat)
        else:  # pragma: no cover
            raise SystemExit(f"Неизвестное задание: {job}")
    finally:
        await app.aclose()


async def _run_summary(app: App, *, no_send: bool, chat: str | None) -> None:
    if no_send:
        # Быстрая итерация по вёрстке: собрать файлы и не трогать мессенджер.
        summary = await app.service.build_summary()
        files = write_report_files(summary, output_dir=app.settings.summary_output_dir)
        kpi = summary.kpi
        print(
            f"Проектов: {kpi.projects}, эпиков: {kpi.epics}, задач: {kpi.tasks}, "
            f"отстают: {kpi.epics_late}, под угрозой: {kpi.epics_risk}"
        )
        if summary.is_empty:
            print(
                f"Отчёт пуст: под фильтр {summary.status_codes} не попал ни один "
                f"из {summary.epics_total_scanned} эпиков. "
                "Расширьте SUMMARY_EPIC_STATUS_CODES в .env."
            )
        for artifact in files.all:
            print(f"  {artifact.path}")
        return

    if chat:
        ok = await app.service.send_summary("telegram", chat)
        print("Сводка отправлена" if ok else "Сводка пуста — отправлено пояснение")
    else:
        count = await app.service.send_summary_to_all()
        print(f"Сводка отправлена: {count} пользователям")


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description="Ручной запуск заданий бота")
    parser.add_argument(
        "--run", required=True, choices=["digest", "deadlines", "evening", "summary"]
    )
    parser.add_argument("--chat", help="отправить только в этот chat_id (только для summary)")
    parser.add_argument(
        "--no-send",
        action="store_true",
        help="только сформировать файлы отчёта и напечатать пути (только для summary)",
    )
    args = parser.parse_args()
    asyncio.run(_run(args.run, no_send=args.no_send, chat=args.chat))


if __name__ == "__main__":
    main()
