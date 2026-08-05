from datetime import date, datetime

from evateam_bot.core.models import (
    Epic,
    Health,
    HealthReason,
    Portfolio,
    StatusCategory,
    Task,
)
from evateam_bot.core.summary import (
    SummaryOptions,
    build_summary,
    combined_health,
    month_ticks,
    timeline_bounds,
    timeline_epics,
    worst,
)

NOW = datetime(2026, 8, 5, 12, 0)


def _epic(id_, *, code=None, title="Эпик", status="in_progress", project="p1",
          project_name="Проект", start=None, end=None, hard=None):
    return Epic(
        id=id_,
        code=code or id_,
        title=title,
        status_code=status,
        status_name=status or "",
        status_category=StatusCategory.IN_PROGRESS,
        project_id=project,
        project_name=project_name,
        plan_start=start,
        plan_end=end,
        deadline=hard,
    )


def _task(id_, *, end=None, hard=None, assignee="Иванов",
          category=StatusCategory.IN_PROGRESS, epic="e1", priority=None, title="Задача"):
    return Task(
        id=id_,
        code=id_,
        title=title,
        status_name="В работе",
        status_category=category,
        plan_end=end,
        deadline=hard,
        assignee=assignee,
        epic_id=epic,
        priority=priority,
    )


def _portfolio(epics, tasks_by_epic=None, projects=None, orphans=None):
    return Portfolio(
        epics=epics,
        tasks_by_epic=tasks_by_epic or {},
        orphan_tasks=orphans or [],
        project_names=projects or {"p1": "Проект"},
    )


# --- светофор ------------------------------------------------------------------


def _health(soft=None, hard=None, risk_days=7):
    return combined_health(soft, hard, NOW, risk_days)


def test_hard_deadline_is_stricter_than_soft():
    """Ключевое правило: красный — только сорванный крайний срок."""
    late_hard = _health(hard=datetime(2026, 8, 4))
    assert late_hard == (Health.LATE, HealthReason.LATE_HARD)

    # Плановая дата прошла, но крайнего срока нет — это ещё не срыв обязательства.
    behind = _health(soft=datetime(2026, 7, 1))
    assert behind == (Health.RISK, HealthReason.BEHIND_PLAN)

    # План просрочен, крайний срок впереди — по-прежнему жёлтый.
    assert _health(soft=datetime(2026, 7, 1), hard=datetime(2026, 12, 1))[0] is Health.RISK

    # Крайний срок сорван — красный, даже если план ещё впереди.
    assert _health(soft=datetime(2027, 1, 1), hard=datetime(2026, 8, 4))[0] is Health.LATE


def test_health_thresholds_and_no_date():
    assert _health() == (Health.NO_DATE, HealthReason.NO_DATE)
    assert _health(soft=datetime(2026, 8, 5))[0] is Health.RISK  # сегодня — ещё не поздно
    assert _health(soft=datetime(2026, 8, 12)) == (Health.RISK, HealthReason.DUE_SOON)
    assert _health(soft=datetime(2026, 8, 13)) == (Health.OK, HealthReason.ON_TRACK)
    # Приближение крайнего срока тоже красит в жёлтый.
    assert _health(hard=datetime(2026, 8, 10))[1] is HealthReason.DUE_SOON


def test_worst_prefers_late_over_missing_date():
    assert worst([Health.NO_DATE, Health.LATE]) is Health.LATE
    assert worst([Health.NO_DATE, Health.OK]) is Health.OK
    assert worst([Health.RISK, Health.OK]) is Health.RISK
    assert worst([]) is Health.NO_DATE


# --- фильтр по статусам --------------------------------------------------------


def test_only_selected_status_codes_are_included():
    portfolio = _portfolio([
        _epic("e1", status="in_progress"),
        _epic("e2", status="open"),
        _epic("e3", status="pause"),
    ])
    summary = build_summary(portfolio, now=NOW, options=SummaryOptions(status_codes=("in_progress", "pause")))
    assert {e.epic.id for e in summary.all_epics} == {"e1", "e3"}
    assert summary.epics_total_scanned == 3


def test_status_code_matching_is_case_insensitive():
    portfolio = _portfolio([_epic("e1", status="IN_PROGRESS")])
    summary = build_summary(portfolio, now=NOW, options=SummaryOptions(status_codes=("in_progress",)))
    assert len(summary.all_epics) == 1


def test_epic_without_status_code_is_counted_but_excluded():
    portfolio = _portfolio([_epic("e1", status=None), _epic("e2", status="in_progress")])
    summary = build_summary(portfolio, now=NOW)
    assert summary.epics_unknown_status == 1
    assert {e.epic.id for e in summary.all_epics} == {"e2"}


def test_empty_status_codes_takes_everything():
    portfolio = _portfolio([_epic("e1", status="open"), _epic("e2", status="whatever")])
    summary = build_summary(portfolio, now=NOW, options=SummaryOptions(status_codes=()))
    assert len(summary.all_epics) == 2


# --- роллап и даты -------------------------------------------------------------


def test_overdue_task_makes_dateless_epic_red():
    """Пробел в дате эпика не должен маскировать сорванный срок его задачи."""
    portfolio = _portfolio(
        [_epic("e1")],
        {"e1": [_task("t1", hard=datetime(2026, 7, 1))]},
    )
    summary = build_summary(portfolio, now=NOW)
    epic = summary.all_epics[0]
    assert epic.health is Health.LATE
    assert epic.reason is HealthReason.LATE_HARD
    assert [t.id for t in epic.blockers] == ["t1"]


def test_task_behind_plan_is_amber_not_blocker():
    portfolio = _portfolio(
        [_epic("e1")],
        {"e1": [_task("t1", end=datetime(2026, 7, 1))]},
    )
    epic = build_summary(portfolio, now=NOW).all_epics[0]
    assert epic.health is Health.RISK
    assert epic.blockers == []
    assert [t.id for t in epic.behind_plan] == ["t1"]


def test_epic_hard_end_is_earliest_of_tasks():
    """Первый сорванный дедлайн внутри эпика — уже проблема эпика."""
    portfolio = _portfolio(
        [_epic("e1")],
        {"e1": [
            _task("later", hard=datetime(2026, 12, 1)),
            _task("sooner", hard=datetime(2026, 9, 1)),
        ]},
    )
    epic = build_summary(portfolio, now=NOW).all_epics[0]
    assert epic.hard_end == datetime(2026, 9, 1)


def test_everything_without_dates_stays_white():
    portfolio = _portfolio([_epic("e1")], {"e1": [_task("t1"), _task("t2")]})
    epic = build_summary(portfolio, now=NOW).all_epics[0]
    assert epic.health is Health.NO_DATE
    assert epic.tasks_without_date == 2
    assert epic.date_coverage == 0.0


def test_epic_dates_derived_from_tasks_when_missing():
    portfolio = _portfolio(
        [_epic("e1")],
        {"e1": [
            Task(id="t1", code="t1", title="a", status_name="", status_category=StatusCategory.IN_PROGRESS,
                 plan_start=datetime(2026, 9, 1), plan_end=datetime(2026, 9, 10), epic_id="e1"),
            Task(id="t2", code="t2", title="b", status_name="", status_category=StatusCategory.IN_PROGRESS,
                 plan_start=datetime(2026, 8, 20), plan_end=datetime(2026, 10, 5), epic_id="e1"),
        ]},
    )
    epic = build_summary(portfolio, now=NOW).all_epics[0]
    assert epic.dates_are_derived is True
    assert epic.start_date == datetime(2026, 8, 20)
    assert epic.end_date == datetime(2026, 10, 5)


def test_inverted_dates_do_not_produce_negative_interval():
    """Если в Ганте окончание раньше начала — не отдаём отрицательный интервал.

    Молча менять даты местами нельзя — это исказит план. Отбрасываем окончание,
    чтобы не отдать Google Timeline строку, которую он отвергнет.
    """
    portfolio = _portfolio(
        [_epic("e1", start=datetime(2026, 7, 20))],
        {"e1": [_task("t1", end=datetime(2026, 6, 5))]},
    )
    epic = build_summary(portfolio, now=NOW).all_epics[0]
    assert epic.start_date == datetime(2026, 7, 20)
    assert epic.end_date is None
    assert epic.open_ended is True


def test_own_epic_dates_win_over_tasks():
    portfolio = _portfolio(
        [_epic("e1", start=datetime(2026, 8, 1), end=datetime(2026, 8, 31))],
        {"e1": [_task("t1", end=datetime(2026, 12, 31))]},
    )
    epic = build_summary(portfolio, now=NOW).all_epics[0]
    assert epic.end_date == datetime(2026, 8, 31)
    assert epic.dates_are_derived is False


def test_idle_epic_is_flagged():
    summary = build_summary(_portfolio([_epic("e1")]), now=NOW)
    epic = summary.all_epics[0]
    assert epic.is_idle is True
    assert epic.total == 0
    assert summary.kpi.epics_idle == 1


def test_counts_and_gaps():
    portfolio = _portfolio(
        [_epic("e1")],
        {"e1": [
            _task("t1", end=datetime(2026, 9, 1)),
            _task("t2", assignee=None, category=StatusCategory.WAITING),
        ]},
    )
    epic = build_summary(portfolio, now=NOW).all_epics[0]
    assert (epic.in_progress, epic.in_review) == (1, 1)
    assert epic.tasks_without_assignee == 1
    assert epic.tasks_without_date == 1
    assert epic.date_coverage == 0.5


# --- группировка и сортировка --------------------------------------------------


def test_projects_sorted_with_problems_first():
    portfolio = _portfolio(
        [
            _epic("green", project="p1", project_name="Зелёный", end=datetime(2027, 1, 1)),
            _epic("red", project="p2", project_name="Красный", hard=datetime(2026, 1, 1)),
        ],
        projects={"p1": "Зелёный", "p2": "Красный"},
    )
    summary = build_summary(portfolio, now=NOW)
    assert [p.name for p in summary.projects] == ["Красный", "Зелёный"]
    assert summary.projects[0].health is Health.LATE
    assert summary.projects[0].late_epics == 1


def test_tasks_sorted_late_first():
    portfolio = _portfolio(
        [_epic("e1")],
        {"e1": [
            _task("ok", end=datetime(2027, 1, 1), title="ok"),
            _task("late", end=datetime(2026, 1, 1), title="late"),
            _task("none", title="none"),
        ]},
    )
    epic = build_summary(portfolio, now=NOW).all_epics[0]
    assert [t.id for t in epic.tasks] == ["late", "ok", "none"]


def test_project_name_falls_back_to_epic_then_placeholder():
    portfolio = Portfolio(
        epics=[_epic("e1", project="pX", project_name="Из эпика")],
        project_names={},
    )
    assert build_summary(portfolio, now=NOW).projects[0].name == "Из эпика"

    nameless = Portfolio(epics=[_epic("e1", project=None, project_name=None)], project_names={})
    assert build_summary(nameless, now=NOW).projects[0].name == "(без проекта)"


# --- сводные показатели --------------------------------------------------------


def test_kpi_and_attention():
    portfolio = _portfolio(
        [
            _epic("late", hard=datetime(2026, 1, 1)),
            _epic("risk", end=datetime(2026, 8, 8)),
            _epic("ok", end=datetime(2027, 1, 1)),
            _epic("nodate"),
        ],
        {"late": [_task("t1", end=datetime(2026, 9, 1))]},
    )
    summary = build_summary(portfolio, now=NOW)
    kpi = summary.kpi
    assert (kpi.epics, kpi.epics_late, kpi.epics_risk, kpi.epics_no_date) == (4, 1, 1, 1)
    assert kpi.tasks == 1
    assert kpi.date_coverage_pct == 100
    assert {e.epic.id for e in summary.attention} == {"late", "risk"}
    assert [t.id for _, t in summary.blockers] == []


def test_empty_portfolio_is_empty_summary():
    summary = build_summary(Portfolio(), now=NOW)
    assert summary.is_empty
    assert summary.projects == []
    assert summary.kpi.epics == 0


def test_orphan_tasks_hidden_unless_requested():
    orphans = [_task("o1", epic=None)]
    assert build_summary(_portfolio([], orphans=orphans), now=NOW).orphan_tasks == []
    with_orphans = build_summary(
        _portfolio([], orphans=orphans), now=NOW,
        options=SummaryOptions(include_orphan_tasks=True),
    )
    assert len(with_orphans.orphan_tasks) == 1


# --- таймлайн ------------------------------------------------------------------


def test_timeline_bounds_snap_to_month_edges():
    portfolio = _portfolio([_epic("e1", start=datetime(2026, 8, 10), end=datetime(2026, 10, 20))])
    start, end = timeline_bounds(build_summary(portfolio, now=NOW))
    assert start == date(2026, 8, 1)
    assert end == date(2026, 10, 31)


def test_timeline_bounds_fallback_without_any_dates():
    start, end = timeline_bounds(build_summary(_portfolio([_epic("e1")]), now=NOW))
    assert start == date(2026, 8, 1)
    assert end > start


def test_timeline_bounds_always_include_today():
    portfolio = _portfolio([_epic("e1", start=datetime(2025, 1, 5), end=datetime(2025, 2, 1))])
    start, end = timeline_bounds(build_summary(portfolio, now=NOW))
    assert start <= NOW.date() <= end


def test_open_ended_epic_is_flagged_and_placed_on_timeline():
    """Начало есть, планового окончания нет — полоса тянется до правого края."""
    portfolio = _portfolio([_epic("e1", start=datetime(2026, 7, 20))])
    summary = build_summary(portfolio, now=NOW)
    epic = summary.all_epics[0]

    assert epic.open_ended is True
    assert epic.start_date == datetime(2026, 7, 20)
    assert epic.end_date is None
    assert summary.kpi.epics_open_ended == 1
    # На карту он попадает — достаточно начала.
    assert [e.epic.id for e in timeline_epics(summary)] == ["e1"]


def test_epic_with_only_end_is_not_placed_on_timeline():
    portfolio = _portfolio([_epic("e1", end=datetime(2026, 9, 1))])
    summary = build_summary(portfolio, now=NOW)
    assert timeline_epics(summary) == []
    assert summary.all_epics[0].open_ended is False


def test_timeline_bounds_cover_today_for_open_ended():
    portfolio = _portfolio([_epic("e1", start=datetime(2026, 7, 20))])
    start, end = timeline_bounds(build_summary(portfolio, now=NOW))
    assert start == date(2026, 7, 1)
    assert end >= NOW.date()  # иначе открытую полосу негде нарисовать


def test_hard_deadline_alone_does_not_place_on_timeline():
    """Дорожная карта строится только по плановым датам."""
    portfolio = _portfolio([_epic("e1", hard=datetime(2026, 9, 1))])
    summary = build_summary(portfolio, now=NOW)
    assert timeline_epics(summary) == []
    assert summary.all_epics[0].hard_end == datetime(2026, 9, 1)


def test_month_ticks_within_range():
    ticks = month_ticks(date(2026, 8, 1), date(2026, 10, 31))
    assert [label for label, _ in ticks] == ["авг 26", "сен 26", "окт 26"]
    assert all(0 <= offset <= 100 for _, offset in ticks)
