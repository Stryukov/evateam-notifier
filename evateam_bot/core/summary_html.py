"""HTML-одностраничник со сводкой — то, что показывают руководителю.

Самодостаточный файл: стили инлайном, никаких внешних скриптов, шрифтов и картинок.
Открывается двойным кликом, печатается в PDF (Ctrl+P), работает без интернета.
Раскрытие карточек — на `<details>`, без JavaScript.
"""

from __future__ import annotations

from datetime import date, datetime

from .formatting import _esc, plural
from .models import EpicSummary, Health, ProjectSummary, Summary
from .summary import month_ticks, position_percent, timeline_bounds, timeline_epics
from .summary_text import HEALTH_EMOJI, HEALTH_LABEL

_CSS = """
:root{--bg:#fff;--fg:#1a1d21;--muted:#6b7280;--line:#e5e7eb;--card:#fff;
--late:#dc2626;--risk:#d97706;--ok:#16a34a;--none:#9ca3af;--accent:#2563eb}
*{box-sizing:border-box}
body{margin:0;padding:24px;background:var(--bg);color:var(--fg);
font:15px/1.5 -apple-system,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif}
h1{font-size:22px;margin:0 0 4px}
h2{font-size:17px;margin:28px 0 12px}
.sub{color:var(--muted);font-size:13px;margin-bottom:20px}
.verdict{font-size:19px;font-weight:600;padding:14px 18px;border-radius:10px;
background:#f9fafb;border-left:5px solid var(--none);margin-bottom:22px}
.verdict.late{border-left-color:var(--late)}
.verdict.risk{border-left-color:var(--risk)}
.verdict.ok{border-left-color:var(--ok)}
.kpis{display:flex;flex-wrap:wrap;gap:12px;margin-bottom:8px}
.kpi{flex:1 1 130px;border:1px solid var(--line);border-radius:10px;padding:12px 14px}
.kpi .n{font-size:26px;font-weight:700;line-height:1.1}
.kpi .l{font-size:12px;color:var(--muted);margin-top:2px}
.kpi.late .n{color:var(--late)}.kpi.risk .n{color:var(--risk)}.kpi.none .n{color:var(--none)}
table{width:100%;border-collapse:collapse;font-size:14px}
th,td{text-align:left;padding:7px 10px;border-bottom:1px solid var(--line);vertical-align:top}
th{font-size:12px;text-transform:uppercase;letter-spacing:.03em;color:var(--muted);font-weight:600}
td.dot{width:26px;text-align:center}
a{color:var(--accent);text-decoration:none}
a:hover{text-decoration:underline}
.miss{color:var(--none);font-style:italic}
.card{border:1px solid var(--line);border-radius:10px;margin-bottom:14px;overflow:hidden}
.card>summary{cursor:pointer;padding:12px 16px;font-weight:600;list-style:none;
display:flex;gap:10px;align-items:baseline;background:#fafafa}
.card>summary::-webkit-details-marker{display:none}
.card>summary::before{content:"▸";color:var(--muted)}
.card[open]>summary::before{content:"▾"}
.card .meta{font-weight:400;color:var(--muted);font-size:13px;margin-left:auto}
.epic{padding:6px 16px 14px}
.epic-head{display:flex;gap:8px;align-items:baseline;margin:14px 0 6px;flex-wrap:wrap}
.epic-title{font-weight:600}
.badge{font-size:12px;color:var(--muted);border:1px solid var(--line);
border-radius:20px;padding:1px 9px}
.badge.late{color:var(--late);border-color:var(--late)}
.badge.risk{color:var(--risk);border-color:var(--risk)}
.tl{border:1px solid var(--line);border-radius:10px;padding:14px 16px;overflow-x:auto}
.tl-scale{position:relative;height:18px;margin-left:210px;border-bottom:1px solid var(--line)}
.tl-tick{position:absolute;top:0;font-size:11px;color:var(--muted);
border-left:1px solid var(--line);padding-left:4px;height:18px;white-space:nowrap}
.tl-row{display:flex;align-items:center;margin-top:7px;min-width:640px}
.tl-label{width:200px;flex:0 0 200px;padding-right:10px;font-size:13px;
white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.tl-track{position:relative;flex:1;height:22px;background:#f6f7f9;border-radius:5px}
.tl-bar{position:absolute;top:3px;height:16px;min-width:3px;border-radius:4px;
color:#fff;font-size:11px;line-height:16px;padding:0 6px;white-space:nowrap;overflow:hidden}
.tl-bar.late{background:var(--late)}.tl-bar.risk{background:var(--risk)}
.tl-bar.ok{background:var(--ok)}.tl-bar.no_date{background:var(--none)}
.tl-bar.derived{background-image:repeating-linear-gradient(45deg,
rgba(255,255,255,.35) 0 5px,transparent 5px 10px)}
/* Полоса без планового окончания — растворяется вправо. */
.tl-bar.open{-webkit-mask-image:linear-gradient(to right,#000 60%,transparent);
mask-image:linear-gradient(to right,#000 60%,transparent)}
.tl-hard{position:absolute;top:0;height:22px;width:2px;background:var(--late)}
.tl-hard::after{content:"▼";position:absolute;top:-11px;left:-4px;
font-size:9px;color:var(--late)}
.tl-today{position:absolute;top:-4px;bottom:-4px;width:2px;background:var(--late);opacity:.7}
.note{color:var(--muted);font-size:13px;margin-top:12px}
footer{margin-top:32px;padding-top:14px;border-top:1px solid var(--line);
color:var(--muted);font-size:12px}
@media print{
  @page{size:A4 landscape;margin:10mm}
  body{padding:0;font-size:12px}
  .card,.tl,.kpi{break-inside:avoid;page-break-inside:avoid}
  .card>summary::before{content:""}
  details:not([open])>*{display:revert}
  details{display:block}
  a{color:inherit;text-decoration:none}
}
"""


def render_html(summary: Summary, *, title: str = "Сводка по проектам") -> str:
    parts = [
        "<!DOCTYPE html>",
        '<html lang="ru"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width,initial-scale=1">',
        f"<title>{_esc(title)}</title>",
        f"<style>{_CSS}</style>",
        "</head><body>",
        f"<h1>{_esc(title)}</h1>",
        f'<div class="sub">{_header_note(summary)}</div>',
    ]

    if summary.is_empty:
        parts += [_empty_block(summary), "</body></html>"]
        return "\n".join(parts)

    parts.append(_verdict_block(summary))
    parts.append(_kpi_block(summary))
    parts.append(_timeline_block(summary))
    parts.append(_attention_block(summary))
    parts.append("<h2>Проекты</h2>")
    parts.extend(_project_card(project) for project in summary.projects)
    parts.append(_footer(summary))
    parts.append("</body></html>")
    return "\n".join(parts)


# --- блоки ---------------------------------------------------------------------


def _header_note(summary: Summary) -> str:
    codes = ", ".join(summary.status_codes) or "все"
    return (
        f"Сформировано {summary.generated_at.strftime('%d.%m.%Y %H:%M')} · "
        f"эпики со статусами: {_esc(codes)} · "
        f"порог «под угрозой»: {summary.risk_days} дн."
    )


def _empty_block(summary: Summary) -> str:
    return (
        '<div class="verdict">⚪ Нет эпиков с выбранными статусами</div>'
        f"<p>Просмотрено эпиков: {summary.epics_total_scanned}, "
        f"без распознанного статуса: {summary.epics_unknown_status}.</p>"
        "<p class='note'>Переведите эпики в нужный статус в EvaTeam либо расширьте "
        "список <code>SUMMARY_EPIC_STATUS_CODES</code> в <code>.env</code>.</p>"
    )


def _verdict_block(summary: Summary) -> str:
    kpi = summary.kpi
    if kpi.epics_late:
        tone, text = "late", f"🔴 Сорван крайний срок у эпиков: {kpi.epics_late}"
        if kpi.epics_risk:
            text += f", под угрозой: {kpi.epics_risk}"
    elif kpi.epics_risk:
        tone, text = "risk", f"🟡 Под угрозой эпиков: {kpi.epics_risk}"
    elif kpi.epics and kpi.epics_no_date == kpi.epics:
        tone, text = "", "⚪ Сроков нет ни у одного эпика — статус не определить"
    else:
        tone, text = "ok", "🟢 Всё по плану"
    return f'<div class="verdict {tone}">{text}</div>'


def _kpi_block(summary: Summary) -> str:
    kpi = summary.kpi
    tiles = [
        ("", kpi.projects, "проектов"),
        ("", kpi.epics, "эпиков"),
        ("late", kpi.epics_late, "отстают"),
        ("risk", kpi.epics_risk, "под угрозой"),
        ("", kpi.tasks, "задач в работе"),
        ("none", f"{kpi.date_coverage_pct}%", "задач со сроком"),
    ]
    cells = "".join(
        f'<div class="kpi {tone}"><div class="n">{value}</div><div class="l">{label}</div></div>'
        for tone, value, label in tiles
    )
    return f'<div class="kpis">{cells}</div>'


def _timeline_block(summary: Summary) -> str:
    start, end = timeline_bounds(summary)
    dated = timeline_epics(summary)
    placed = {item.epic.id for item in dated}
    undated = [e for e in summary.all_epics if e.epic.id not in placed]

    ticks = "".join(
        f'<div class="tl-tick" style="left:{offset:.2f}%">{_esc(label)}</div>'
        for label, offset in month_ticks(start, end)
    )
    rows = "".join(_timeline_row(item, start, end) for item in dated)
    today = position_percent(summary.generated_at.date(), start, end)

    body = [
        "<h2>Дорожная карта по эпикам</h2>",
        '<div class="tl">',
        f'<div class="tl-scale">{ticks}</div>',
    ]
    if rows:
        body.append(
            f'<div style="position:relative">'
            f'<div class="tl-today" style="left:calc(210px + (100% - 210px) * {today / 100:.4f})"'
            f' title="сегодня"></div>{rows}</div>'
        )
    else:
        body.append(
            '<p class="note">Ни у одного эпика не заданы плановые даты — '
            "дорожную карту построить не из чего.</p>"
        )
    body.append("</div>")

    if undated:
        items = "".join(
            f"<li>{_epic_link(item)} — {_esc(item.epic.project_name or '')}</li>"
            for item in undated
        )
        body.append(
            f'<p class="note">⚪ Без сроков ({len(undated)}) — не размещены на диаграмме:</p>'
            f'<ul class="note">{items}</ul>'
        )
    return "\n".join(body)


def _timeline_row(item: EpicSummary, start: date, end: date) -> str:
    left = position_percent(item.start_date.date(), start, end)
    if item.end_date:
        right = position_percent(item.end_date.date(), start, end)
        span = f"{item.start_date.strftime('%d.%m')} → {item.end_date.strftime('%d.%m')}"
        open_cls = ""
    else:
        # Окончание не задано — тянем полосу до правого края и растворяем её.
        right = 100.0
        span = f"{item.start_date.strftime('%d.%m')} → ?"
        open_cls = " open"
    width = max(right - left, 0.6)

    classes = f"{item.health.value}{' derived' if item.dates_are_derived else ''}{open_cls}"
    title = "окончание не задано" if item.open_ended else span
    label = f"{item.epic.code} · {item.epic.title}" if item.epic.code else item.epic.title

    # Крайний срок — отдельная засечка, он живёт по своей шкале.
    hard = ""
    if item.hard_end:
        hard_pos = position_percent(item.hard_end.date(), start, end)
        hard = (
            f'<div class="tl-hard" style="left:{hard_pos:.2f}%" '
            f'title="крайний срок {item.hard_end.strftime("%d.%m.%Y")}"></div>'
        )
    return (
        f'<div class="tl-row"><div class="tl-label" title="{_esc(label)}">{_esc(label)}</div>'
        f'<div class="tl-track"><div class="tl-bar {classes}" title="{_esc(title)}" '
        f'style="left:{left:.2f}%;width:{width:.2f}%">{span}</div>{hard}</div></div>'
    )


def _attention_block(summary: Summary) -> str:
    items = summary.attention
    if not items:
        return ""
    rows = "".join(
        f'<tr><td class="dot">{HEALTH_EMOJI[item.health]}</td>'
        f"<td>{_epic_link(item)}</td>"
        f"<td>{_esc(item.epic.project_name or '')}</td>"
        f"<td>{_deadline_cell(item)}</td>"
        f"<td>{_esc(_epic_note(item))}</td></tr>"
        for item in items
    )
    return (
        "<h2>Требуют решения</h2>"
        "<table><thead><tr><th></th><th>Эпик</th><th>Проект</th>"
        "<th>Сроки</th><th>Комментарий</th></tr></thead>"
        f"<tbody>{rows}</tbody></table>"
    )


def _project_card(project: ProjectSummary) -> str:
    is_problem = project.health in (Health.LATE, Health.RISK)
    open_attr = " open" if is_problem else ""
    meta = (
        f"эпиков: {len(project.epics)} · задач: {project.total_tasks}"
        + (f" · отстают: {project.late_epics}" if project.late_epics else "")
    )

    # Эпики без задач в работе схлопываем в одну строку: развёрнутые заголовки
    # с «нет задач» заслоняют то немногое, что действительно движется.
    active = [item for item in project.epics if not item.is_idle]
    idle = [item for item in project.epics if item.is_idle]

    body = "".join(_epic_block(item) for item in active)
    if idle:
        codes = ", ".join(_epic_link(item) for item in idle)
        word = plural(len(idle), "эпик", "эпика", "эпиков")
        # «Ещё» уместно, только если выше действительно что-то показано.
        prefix = f"Ещё {len(idle)}" if active else str(len(idle))
        body += f'<p class="note">⚪ {prefix} {word} без задач в работе: {codes}</p>'
    return (
        f'<details class="card"{open_attr}>'
        f"<summary>{HEALTH_EMOJI[project.health]} {_esc(project.name)}"
        f'<span class="meta">{meta}</span></summary>'
        f'<div class="epic">{body}</div></details>'
    )


def _epic_block(item: EpicSummary) -> str:
    badges = [f'<span class="badge {_tone(item.health)}">{HEALTH_LABEL[item.health]}</span>']
    if item.end_date:
        badges.append(f'<span class="badge">план до {item.end_date.strftime("%d.%m.%Y")}</span>')
    elif item.open_ended:
        badges.append('<span class="badge">окончание не задано</span>')
    if item.hard_end:
        badges.append(
            f'<span class="badge {"late" if (item.days_left_hard or 0) < 0 else ""}">'
            f'крайний {item.hard_end.strftime("%d.%m.%Y")}</span>'
        )
    if item.dates_are_derived:
        badges.append('<span class="badge">даты из задач</span>')
    if item.epic.responsible:
        badges.append(f'<span class="badge">{_esc(item.epic.responsible)}</span>')

    head = (
        f'<div class="epic-head"><span class="epic-title">{_epic_link(item)}</span>'
        f"{''.join(badges)}</div>"
    )
    if item.is_idle:
        return head + '<p class="miss">Нет задач в работе.</p>'

    rows = "".join(
        f'<tr><td class="dot">{_task_dot(item, task)}</td>'
        f"<td>{_task_link(task)}</td>"
        f"<td>{_esc(task.status_name)}</td>"
        f"<td>{_cell(task.assignee, 'без исполнителя')}</td>"
        f"<td>{_cell(_fmt_date(task.soft_end), 'без срока')}</td>"
        f"<td>{_hard_cell(item, task)}</td></tr>"
        for task in item.tasks
    )
    return (
        head
        + "<table><thead><tr><th></th><th>Задача</th><th>Статус</th>"
        "<th>Исполнитель</th><th>Плановая дата</th><th>Крайний срок</th></tr></thead>"
        f"<tbody>{rows}</tbody></table>"
    )


def _hard_cell(item: EpicSummary, task) -> str:
    """Крайний срок; просроченный — красным, это сорванное обязательство.

    Просрочку не пересчитываем: задачи с сорванным крайним сроком уже отобраны
    в `item.blockers` на едином `now`.
    """
    if not task.hard_end:
        return '<span class="miss">не задан</span>'
    text = _esc(task.hard_end.strftime("%d.%m.%Y"))
    if task in item.blockers:
        return f'<b style="color:var(--late)">{text}</b>'
    return text


def _footer(summary: Summary) -> str:
    kpi = summary.kpi
    return (
        "<footer>"
        f"Просмотрено эпиков: {summary.epics_total_scanned}, "
        f"в отчёте: {kpi.epics}, без распознанного статуса: {summary.epics_unknown_status}. "
        f"Эпиков без задач в работе: {kpi.epics_idle}."
        "<br><br>"
        "<b>Два срока.</b> «Плановая дата окончания» — мягкий срок, по нему строится "
        "дорожная карта. «Крайний срок» — жёсткое обязательство, на диаграмме показан "
        "красной засечкой ▼."
        "<br>"
        "<b>Статус считается автоматически, жёсткий срок строже мягкого:</b> "
        "🔴 сорван крайний срок · 🟡 отстаём от плановой даты либо любой срок в пределах "
        f"{summary.risk_days} дн. · 🟢 оба срока впереди · ⚪ сроки не заданы. "
        "Статус эпика и проекта — худший из дочерних."
        "</footer>"
    )


# --- мелочи --------------------------------------------------------------------


def _tone(health: Health) -> str:
    return health.value if health in (Health.LATE, Health.RISK) else ""


def _epic_link(item: EpicSummary) -> str:
    epic = item.epic
    text = f"{epic.code} · {epic.title}" if epic.code else epic.title
    if epic.url:
        return f'<a href="{_esc(epic.url)}">{_esc(text)}</a>'
    return _esc(text)


def _task_link(task) -> str:
    text = f"{task.code} · {task.title}" if task.code else task.title
    if task.url:
        return f'<a href="{_esc(task.url)}">{_esc(text)}</a>'
    return _esc(text)


def _task_dot(item: EpicSummary, task) -> str:
    if task in item.blockers:
        return HEALTH_EMOJI[Health.LATE]
    if task in item.behind_plan:
        return HEALTH_EMOJI[Health.RISK]
    if task.soft_end is None and task.hard_end is None:
        return HEALTH_EMOJI[Health.NO_DATE]
    return ""


def _deadline_cell(item: EpicSummary) -> str:
    """Плановая дата окончания и, отдельной строкой, крайний срок."""
    parts = []
    if item.end_date:
        text = item.end_date.strftime("%d.%m.%Y")
        if item.days_left is not None and item.days_left < 0:
            text += f" (отстаёт на {abs(item.days_left)} дн.)"
        parts.append(_esc(text))
    elif item.open_ended:
        parts.append('<span class="miss">окончание не задано</span>')
    else:
        parts.append('<span class="miss">не задана</span>')

    if item.hard_end:
        text = "крайний: " + item.hard_end.strftime("%d.%m.%Y")
        if item.days_left_hard is not None and item.days_left_hard < 0:
            text += f" (просрочен на {abs(item.days_left_hard)} дн.)"
            parts.append(f'<b style="color:var(--late)">{_esc(text)}</b>')
        else:
            parts.append(f'<span class="miss">{_esc(text)}</span>')
    return "<br>".join(parts)


def _epic_note(item: EpicSummary) -> str:
    if item.is_idle:
        return "нет задач в работе"
    notes = [f"задач: {item.total}"]
    if item.blockers:
        notes.append(f"сорван крайний срок: {len(item.blockers)}")
    if item.behind_plan:
        notes.append(f"отстают от плана: {len(item.behind_plan)}")
    if item.tasks_without_date:
        notes.append(f"без плановой даты: {item.tasks_without_date}")
    if item.tasks_without_assignee:
        notes.append(f"без исполнителя: {item.tasks_without_assignee}")
    return ", ".join(notes)


def _cell(value: str | None, placeholder: str) -> str:
    return _esc(value) if value else f'<span class="miss">{placeholder}</span>'


def _fmt_date(value: datetime | None) -> str | None:
    return value.strftime("%d.%m.%Y") if value else None
