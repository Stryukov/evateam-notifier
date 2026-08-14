"""Smoke-скрипт: проверить связь с EvaTeam и подтвердить Open items.

    python -m evateam_bot.evateam.smoke --person user@example.ru
    python -m evateam_bot.evateam.smoke --epics

`--person` печатает найденного пользователя и его задачи.
`--epics` печатает эпики (CmfTask с logic_prefix=task.epic) с кодами статусов и
плановыми датами — этим подтверждаются имена полей для сводки по проектам.

Если падает — по тексту ошибки корректируем метод/фильтр/режим аутентификации
(см. evateam/tasks.py, .env).
"""

from __future__ import annotations

import argparse
import asyncio
from collections import Counter

from ..config import get_settings
from .client import EvaTeamClient
from .dto import _rel_field, _rel_key
from .tasks import (
    ACTIVE_STATUS_TYPES,
    CLOSED_STATUS_TYPE,
    EPIC_FIELDS,
    EPIC_LOGIC_PREFIX,
    METHOD_TASK_LIST,
    EvaTeamTasks,
    _extract_items,
)


async def _run(query: str) -> None:
    settings = get_settings()
    print(f"Base URL: {settings.evateam_base_url}")
    print(f"Auth mode: {settings.evateam_auth_mode}")
    print(f"Verify SSL: {settings.evateam_verify_ssl}")
    print(f"Proxy: {settings.resolve_proxy()}")
    async with EvaTeamClient(
        settings.evateam_base_url,
        settings.evateam_token,
        settings.evateam_auth_mode,
        admin_mode=settings.evateam_admin_mode,
        verify=settings.evateam_verify_ssl,
        proxy=settings.resolve_proxy(),
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


async def _run_epics() -> None:
    """Диагностика эпиков: подтвердить имена полей для сводки по проектам."""
    settings = get_settings()
    print(f"Base URL: {settings.evateam_base_url}")
    print(f"Фильтр эпиков в .env: {settings.summary_epic_status_codes}")
    async with EvaTeamClient(
        settings.evateam_base_url,
        settings.evateam_token,
        settings.evateam_auth_mode,
        admin_mode=settings.evateam_admin_mode,
        verify=settings.evateam_verify_ssl,
        proxy=settings.resolve_proxy(),
    ) as client:
        epics_raw = _extract_items(
            await client.call(
                METHOD_TASK_LIST,
                kwargs={
                    "filter": [
                        ["logic_prefix", "==", EPIC_LOGIC_PREFIX],
                        ["cache_status_type", "!=", CLOSED_STATUS_TYPE],
                    ],
                    "fields": EPIC_FIELDS,
                    "order_by": ["name"],
                },
            )
        )
        print(f"\n=== Незакрытых эпиков: {len(epics_raw)} ===")

        # Сколько активных задач висит на каждом эпике.
        children: Counter[str] = Counter()
        for status_type in ACTIVE_STATUS_TYPES:
            items = _extract_items(
                await client.call(
                    METHOD_TASK_LIST,
                    kwargs={
                        "filter": [["cache_status_type", "==", status_type]],
                        "fields": ["id", "epic_id", "logic_prefix"],
                    },
                )
            )
            for item in items:
                if item.get("epic_id") and item.get("logic_prefix") != EPIC_LOGIC_PREFIX:
                    children[item["epic_id"]] += 1

        by_code: Counter[str] = Counter()
        for epic in epics_raw:
            status_code = _rel_key(epic.get("status"), "code")
            by_code[status_code or "(нет status.code)"] += 1
            project = _rel_field(epic.get("parent")) or _rel_field(epic.get("project")) or "—"
            print(
                f"  {str(epic.get('code')):<9} "
                f"code={str(status_code):<12} "
                f"name={str(_rel_key(epic.get('status'), 'name')):<16} "
                f"plan={str(epic.get('plan_start_date'))[:10]}..{str(epic.get('plan_end_date'))[:10]} "
                f"dl={str(epic.get('deadline'))[:10]:<11} "
                f"задач={children.get(epic.get('id'), 0):<3} "
                f"[{project}] {epic.get('name')}"
            )

        print("\n=== Эпиков по кодам статусов ===")
        for code, count in by_code.most_common():
            print(f"  {code:<24} {count}")
        selected = settings.parsed_epic_status_codes()
        matched = sum(count for code, count in by_code.items() if code in selected)
        print(f"\nПод фильтр {selected} попадает эпиков: {matched}")
        if not matched:
            print(
                "  Сводка будет ПУСТОЙ. Чтобы увидеть данные, добавьте нужный код "
                "в SUMMARY_EPIC_STATUS_CODES (.env)."
            )


def main() -> None:
    parser = argparse.ArgumentParser(description="EvaTeam API smoke-тест")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--person", help="email или логин пользователя")
    group.add_argument(
        "--epics", action="store_true", help="показать эпики, их статусы и плановые даты"
    )
    args = parser.parse_args()
    asyncio.run(_run_epics() if args.epics else _run(args.person))


if __name__ == "__main__":
    main()
