"""Экспорт дорожной карты в CSV под Google Sheets Timeline view.

Колонки повторяют то, что ожидает Timeline: название карточки, даты начала и конца,
группа (строка диаграммы), описание и цвет. Импортировать → Вставка → Таймлайн.

Одна строка = один эпик, группировка по проекту: Timeline группирует по одной
колонке, и смешивать в ней проекты и эпики нельзя без потери смысла.
"""

from __future__ import annotations

import csv
import io

from .models import Health, Summary

CSV_HEADER = [
    "Card title",
    "Start date",
    "End date",
    "Card group",
    "Card detail",
    "Card color",
]

#: Значения в колонке цвета — читаемые метки, Sheets раскрасит по ним карточки.
COLOR_LABEL: dict[Health, str] = {
    Health.LATE: "Просрочено",
    Health.RISK: "Под угрозой",
    Health.OK: "По плану",
    Health.NO_DATE: "Без срока",
}

DATE_FORMAT = "%Y-%m-%d"


def render_timeline_csv(summary: Summary) -> str:
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow(CSV_HEADER)

    for project in summary.projects:
        for item in project.epics:
            # Timeline не разместит карточку без обеих дат — такие пропускаем,
            # их количество видно в HTML и в сводке.
            if not (item.start_date and item.end_date):
                continue
            epic = item.epic
            title = f"{epic.code} · {epic.title}" if epic.code else epic.title
            writer.writerow([
                title,
                item.start_date.strftime(DATE_FORMAT),
                item.end_date.strftime(DATE_FORMAT),
                project.name,
                _detail(item),
                COLOR_LABEL[item.health],
            ])
    return buffer.getvalue()


def _detail(item) -> str:
    if item.is_idle:
        return "нет задач в работе"
    parts = [f"задач: {item.total}"]
    people = sorted({t.assignee for t in item.tasks if t.assignee})
    if people:
        parts.append(", ".join(people))
    if item.dates_are_derived:
        parts.append("даты выведены из задач")
    return " · ".join(parts)
