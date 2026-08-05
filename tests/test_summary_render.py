import csv
import io
import re
from datetime import datetime

from evateam_bot.core.models import Epic, Portfolio, StatusCategory, Task
from evateam_bot.core.summary import SummaryOptions, build_summary
from evateam_bot.core.summary_csv import CSV_HEADER, render_timeline_csv
from evateam_bot.core.summary_html import render_html

NOW = datetime(2026, 8, 5, 12, 0)


def _epic(id_, *, title="Эпик", start=None, end=None, hard=None, project="p1",
          project_name="Проект", url=None):
    return Epic(
        id=id_,
        code=id_.upper(),
        title=title,
        status_code="in_progress",
        status_name="В работе",
        status_category=StatusCategory.IN_PROGRESS,
        project_id=project,
        project_name=project_name,
        plan_start=start,
        plan_end=end,
        deadline=hard,
        url=url,
    )


def _task(id_, *, end=None, hard=None, assignee="Иванов", title="Задача", epic="e1"):
    return Task(
        id=id_,
        code=id_.upper(),
        title=title,
        status_name="В работе",
        status_category=StatusCategory.IN_PROGRESS,
        plan_end=end,
        deadline=hard,
        assignee=assignee,
        epic_id=epic,
    )


def _summary(epics, tasks_by_epic=None, **kwargs):
    portfolio = Portfolio(
        epics=epics,
        tasks_by_epic=tasks_by_epic or {},
        project_names={"p1": "Проект", "p2": "Второй"},
    )
    return build_summary(portfolio, now=NOW, **kwargs)


# --- HTML ----------------------------------------------------------------------


def test_html_is_a_complete_document():
    html = render_html(_summary([_epic("e1", end=datetime(2026, 9, 1))]))
    assert html.startswith("<!DOCTYPE html>")
    assert html.rstrip().endswith("</html>")
    assert "<title>Сводка по проектам</title>" in html


def test_html_is_self_contained():
    """Ни одной внешней зависимости — файл должен открываться без интернета."""
    html = render_html(_summary([_epic("e1", end=datetime(2026, 9, 1))]))
    assert "<script" not in html
    assert not re.search(r'<link[^>]+rel=["\']?stylesheet', html)
    assert not re.search(r'src=["\']https?://', html)
    assert not re.search(r'@import|url\(\s*https?://', html)


def test_html_has_print_styles():
    html = render_html(_summary([_epic("e1")]))
    assert "@media print" in html
    assert "break-inside" in html
    assert "A4" in html or "size:A4" in html.replace(" ", "")


def test_timeline_percentages_stay_in_range():
    epics = [
        _epic("early", start=datetime(2026, 1, 1), end=datetime(2026, 2, 1)),
        _epic("late", start=datetime(2026, 11, 1), end=datetime(2026, 12, 31)),
    ]
    html = render_html(_summary(epics))
    values = [float(v) for v in re.findall(r"(?:left|width):(-?\d+\.\d+)%", html)]
    assert values, "на диаграмме должны быть полосы"
    assert all(-0.01 <= v <= 100.01 for v in values)


def test_epics_without_dates_are_listed_not_hidden():
    html = render_html(_summary([_epic("e1", title="Без дат")]))
    assert "Без сроков (1)" in html
    assert "Без дат" in html


def test_timeline_notes_when_nothing_has_dates():
    html = render_html(_summary([_epic("e1")]))
    assert "дорожную карту построить не из чего" in html


def test_derived_dates_are_marked():
    summary = _summary([_epic("e1")], {"e1": [_task("t1", end=datetime(2026, 9, 1))]})
    html = render_html(summary)
    assert "derived" in html
    assert "даты из задач" in html


def test_idle_epics_collapsed_into_one_line():
    """Развёрнутые «нет задач» топят единственный работающий эпик."""
    epics = [_epic("busy", end=datetime(2026, 1, 1))] + [
        _epic(f"idle{i}", title=f"Пустой {i}") for i in range(5)
    ]
    html = render_html(_summary(epics, {"busy": [_task("t1", end=datetime(2026, 1, 1))]}))
    assert "Ещё 5 эпиков без задач в работе" in html
    assert html.count("Нет задач в работе") == 0


def test_idle_epic_count_is_declined():
    def _html(n):
        epics = [_epic("busy", end=datetime(2026, 1, 1))] + [
            _epic(f"idle{i}") for i in range(n)
        ]
        return render_html(_summary(epics, {"busy": [_task("t1", end=datetime(2026, 1, 1))]}))

    assert "Ещё 1 эпик без" in _html(1)
    assert "Ещё 2 эпика без" in _html(2)
    assert "Ещё 5 эпиков без" in _html(5)
    assert "Ещё 11 эпиков без" in _html(11)


def test_problem_project_is_expanded_and_healthy_collapsed():
    epics = [
        _epic("red", end=datetime(2026, 1, 1), project="p1", project_name="Проект"),
        _epic("green", end=datetime(2027, 1, 1), project="p2", project_name="Второй"),
    ]
    html = render_html(_summary(epics))
    assert '<details class="card" open>' in html  # проблемный раскрыт
    assert '<details class="card">' in html  # здоровый свёрнут


def test_open_ended_bar_is_drawn_and_marked():
    """Начало есть, окончания нет — полоса до правого края, а не пропуск строки."""
    html = render_html(_summary([_epic("e1", start=datetime(2026, 7, 20))]))
    assert "tl-bar" in html
    assert "open" in html
    assert "окончание не задано" in html
    assert "→ ?" in html


def test_hard_deadline_shown_as_marker_on_timeline():
    html = render_html(_summary([
        _epic("e1", start=datetime(2026, 8, 1), end=datetime(2026, 9, 1),
              hard=datetime(2026, 9, 20))
    ]))
    assert "tl-hard" in html
    assert "крайний срок 20.09.2026" in html


def test_task_table_has_both_date_columns():
    summary = _summary(
        [_epic("e1", hard=datetime(2026, 1, 1))],
        {"e1": [_task("t1", end=datetime(2026, 9, 1), hard=datetime(2026, 9, 10))]},
    )
    html = render_html(summary)
    assert "<th>Плановая дата</th>" in html
    assert "<th>Крайний срок</th>" in html
    assert "01.09.2026" in html and "10.09.2026" in html


def test_timeline_uses_plan_dates_not_deadline():
    """Дорожная карта строится по мягким срокам — эпик только с крайним не на карте."""
    html = render_html(_summary([_epic("e1", hard=datetime(2026, 9, 1))]))
    assert "дорожную карту построить не из чего" in html


def test_missing_values_are_explicit():
    summary = _summary([_epic("e1", end=datetime(2026, 1, 1))],
                       {"e1": [_task("t1", assignee=None)]})
    html = render_html(summary)
    assert "без исполнителя" in html
    assert "без срока" in html


def test_html_escapes_user_content():
    epic = _epic("e1", title="A < B & C", end=datetime(2026, 1, 1))
    html = render_html(_summary([epic]))
    assert "A &lt; B &amp; C" in html
    assert "A < B & C" not in html


def test_empty_summary_html_explains_why():
    portfolio = Portfolio(epics=[_epic("e1")], project_names={})
    summary = build_summary(portfolio, now=NOW, options=SummaryOptions(status_codes=("pause",)))
    html = render_html(summary)
    assert "Нет эпиков с выбранными статусами" in html
    assert "SUMMARY_EPIC_STATUS_CODES" in html


def test_verdict_reflects_state():
    late = render_html(_summary([_epic("e1", hard=datetime(2026, 1, 1))]))
    assert "Сорван крайний срок у эпиков: 1" in late
    assert "Всё по плану" in render_html(_summary([_epic("e1", end=datetime(2027, 1, 1))]))
    assert "Сроков нет ни у одного эпика" in render_html(_summary([_epic("e1")]))
    # Просроченная плановая дата без крайнего срока — жёлтая, не красная.
    assert "Под угрозой эпиков: 1" in render_html(
        _summary([_epic("e1", end=datetime(2026, 1, 1))])
    )


# --- CSV -----------------------------------------------------------------------


def _rows(summary):
    return list(csv.reader(io.StringIO(render_timeline_csv(summary))))


def test_csv_header_matches_google_timeline():
    rows = _rows(_summary([_epic("e1", start=datetime(2026, 8, 1), end=datetime(2026, 9, 1))]))
    assert rows[0] == CSV_HEADER


def test_csv_row_shape():
    summary = _summary(
        [_epic("e1", title="Эпик", start=datetime(2026, 8, 1), end=datetime(2026, 9, 1))],
        {"e1": [_task("t1", end=datetime(2026, 8, 15), assignee="Иванов")]},
    )
    title, start, end, group, detail, color = _rows(summary)[1]
    assert title == "E1 · Эпик"
    assert start == "2026-08-01"
    assert end == "2026-09-01"
    assert group == "Проект"
    assert "Иванов" in detail
    assert color in {"Просрочено", "Под угрозой", "По плану", "Без срока"}


def test_csv_skips_epics_without_both_dates():
    summary = _summary([
        _epic("dated", start=datetime(2026, 8, 1), end=datetime(2026, 9, 1)),
        _epic("undated"),
        _epic("half", start=datetime(2026, 8, 1)),
    ])
    assert [row[0] for row in _rows(summary)[1:]] == ["DATED · Эпик"]


def test_csv_quotes_commas_in_russian_names():
    epic = _epic("e1", title="Биллинг, этап 2",
                 start=datetime(2026, 8, 1), end=datetime(2026, 9, 1))
    raw = render_timeline_csv(_summary([epic]))
    assert '"E1 · Биллинг, этап 2"' in raw
    assert _rows(_summary([epic]))[1][0] == "E1 · Биллинг, этап 2"


def test_csv_color_reflects_two_deadlines():
    behind = _summary([_epic("e1", start=datetime(2026, 1, 1), end=datetime(2026, 2, 1))])
    assert _rows(behind)[1][5] == "Под угрозой"  # отстаёт от плана

    late = _summary([
        _epic("e1", start=datetime(2026, 1, 1), end=datetime(2026, 2, 1),
              hard=datetime(2026, 3, 1))
    ])
    assert _rows(late)[1][5] == "Просрочено"  # сорван крайний срок


def test_csv_detail_includes_hard_deadline():
    summary = _summary([
        _epic("e1", start=datetime(2026, 8, 1), end=datetime(2026, 9, 1),
              hard=datetime(2026, 9, 15))
    ])
    assert "крайний срок: 2026-09-15" in _rows(summary)[1][4]
