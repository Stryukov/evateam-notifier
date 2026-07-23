"""Smoke-скрипт: проверить связь с EvaTeam и подтвердить Open items.

    python -m evateam_bot.evateam.smoke --person user@example.ru

Печатает найденного пользователя и его задачи. Если падает — по тексту ошибки
корректируем метод/фильтр/режим аутентификации (см. evateam/tasks.py, .env).
"""

from __future__ import annotations

import argparse
import asyncio

from ..config import get_settings
from .client import EvaTeamClient
from .tasks import EvaTeamTasks


async def _run(query: str) -> None:
    settings = get_settings()
    print(f"Base URL: {settings.evateam_base_url}")
    print(f"Auth mode: {settings.evateam_auth_mode}")
    async with EvaTeamClient(
        settings.evateam_base_url,
        settings.evateam_token,
        settings.evateam_auth_mode,
    ) as client:
        tasks_api = EvaTeamTasks(client, base_url=settings.evateam_base_url)

        print(f"\n=== Поиск пользователя по «{query}» ===")
        people = await tasks_api.find_person(query)
        if not people:
            print("Пользователь не найден. Проверьте METHOD_PERSON_LIST и синтаксис фильтра.")
            return
        for person in people:
            print(f"  {person.id}  {person.name}  <{person.email or person.login}>")

        person = people[0]
        print(f"\n=== Задачи пользователя {person.name} ===")
        tasks = await tasks_api.get_tasks_for_person(person.id)
        if not tasks:
            print("Задач нет (или нужно поправить METHOD_TASK_LIST/фильтр).")
        for task in tasks:
            code = task.code or task.id
            deadline = task.deadline.isoformat() if task.deadline else "—"
            print(f"  [{code}] {task.title} | {task.status_name} "
                  f"({task.status_category.value}) | дедлайн: {deadline}")


def main() -> None:
    parser = argparse.ArgumentParser(description="EvaTeam API smoke-тест")
    parser.add_argument("--person", required=True, help="email или логин пользователя")
    args = parser.parse_args()
    asyncio.run(_run(args.person))


if __name__ == "__main__":
    main()
