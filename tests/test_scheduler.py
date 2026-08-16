"""Расписание рассылок и устойчивость планировщика ко сну машины."""

import logging
from datetime import datetime, timedelta

from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from evateam_bot.config import Settings
from evateam_bot.scheduler.runner import (
    HEARTBEAT_SECONDS,
    build_scheduler,
    make_heartbeat,
)


class FakeService:
    async def send_daily_digests(self):  # pragma: no cover
        return 0

    async def send_deadline_reminders(self, now=None):  # pragma: no cover
        return 0

    async def send_evening_reminders(self, now=None):  # pragma: no cover
        return 0


def _scheduler(**overrides):
    settings = Settings(
        timezone="Asia/Kamchatka",
        digest_time="08:00",
        deadline_check_time="08:30",
        evening_check_time="16:00",
        **overrides,
    )
    return build_scheduler(FakeService(), settings)


def _job(scheduler, job_id):
    job = scheduler.get_job(job_id)
    assert job is not None, f"задание {job_id} не зарегистрировано"
    return job


def _cron_field(trigger, name):
    return str(next(f for f in trigger.fields if f.name == name))


# --- состав расписания ---------------------------------------------------------


def test_all_jobs_registered():
    scheduler = _scheduler()
    for job_id in ("morning_digest", "deadline_check", "evening_check", "heartbeat"):
        _job(scheduler, job_id)


def test_times_come_from_settings():
    scheduler = _scheduler()
    trigger = _job(scheduler, "morning_digest").trigger
    assert isinstance(trigger, CronTrigger)
    assert _cron_field(trigger, "hour") == "8"
    assert _cron_field(trigger, "minute") == "0"
    assert str(trigger.timezone) == "Asia/Kamchatka"


def test_weekdays_only_by_default():
    """По выходным рассылки не нужны."""
    scheduler = _scheduler()
    for job_id in ("morning_digest", "deadline_check", "evening_check"):
        assert _cron_field(_job(scheduler, job_id).trigger, "day_of_week") == "mon-fri"


def test_schedule_days_configurable():
    scheduler = _scheduler(schedule_days="mon-sun")
    assert _cron_field(_job(scheduler, "morning_digest").trigger, "day_of_week") == "mon-sun"


# --- пульс ---------------------------------------------------------------------


def test_heartbeat_keeps_timers_short():
    """Длинный call_later не переживает сон машины — держим такт коротким."""
    job = _job(_scheduler(), "heartbeat")
    assert isinstance(job.trigger, IntervalTrigger)
    assert job.trigger.interval.total_seconds() == HEARTBEAT_SECONDS
    assert HEARTBEAT_SECONDS <= 300


def test_heartbeat_does_not_warn_about_its_own_lateness():
    """Иначе после каждого пробуждения лог завалит предупреждениями APScheduler."""
    job = _job(_scheduler(), "heartbeat")
    assert job.misfire_grace_time is None
    assert job.coalesce is True


def test_working_jobs_do_not_catch_up():
    """Решено не досылать: «план дня», пришедший вечером, только путает."""
    scheduler = _scheduler()
    for job_id in ("morning_digest", "deadline_check", "evening_check"):
        assert _job(scheduler, job_id).misfire_grace_time == 1


async def test_heartbeat_warns_after_a_time_gap(caplog):
    moments = iter([
        datetime(2026, 8, 17, 1, 0),
        datetime(2026, 8, 17, 1, 1),  # обычный такт
        datetime(2026, 8, 17, 8, 30),  # машина спала 7.5 часов
    ])
    heartbeat = make_heartbeat(now=lambda: next(moments))

    with caplog.at_level(logging.WARNING):
        await heartbeat()  # первый такт — сравнивать не с чем
        await heartbeat()
        assert caplog.records == []
        await heartbeat()

    assert len(caplog.records) == 1
    assert "машина спала" in caplog.records[0].getMessage()
    assert "449 мин" in caplog.records[0].getMessage()


async def test_heartbeat_silent_on_small_drift(caplog):
    start = datetime(2026, 8, 17, 8, 0)
    moments = iter([start, start + timedelta(seconds=HEARTBEAT_SECONDS + 5)])
    heartbeat = make_heartbeat(now=lambda: next(moments))

    with caplog.at_level(logging.WARNING):
        await heartbeat()
        await heartbeat()

    assert caplog.records == []
