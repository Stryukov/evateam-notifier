"""Конфигурация приложения (читается из окружения/.env)."""

from __future__ import annotations

import os
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # EvaTeam
    evateam_base_url: str = Field(default="https://evateam.example.ru")
    evateam_token: str = Field(default="")
    # bearer | token | header:<HeaderName>
    evateam_auth_mode: str = Field(default="bearer")
    # Проверка TLS: "true" | "false" | путь к CA-бандлу (.pem) для корп. сети
    evateam_verify_ssl: str = Field(default="true")
    # admin_mode: сервис-аккаунт (в группе Admins) видит задачи всех сотрудников
    evateam_admin_mode: bool = Field(default=True)

    # Telegram
    telegram_bot_token: str = Field(default="")

    # Прокси для исходящих запросов (Telegram и EvaTeam) в корп-сети.
    #   ""     -> взять из окружения (HTTPS_PROXY/HTTP_PROXY)
    #   "none" -> без прокси (прямое соединение)
    #   <url>  -> явный адрес, напр. http://proxy.example.local:1080
    proxy_url: str = Field(default="")

    def resolve_proxy(self) -> str | None:
        """Вернуть URL прокси или None (прямое соединение)."""
        raw = self.proxy_url.strip()
        if raw.lower() == "none":
            return None
        if raw:
            return raw
        for key in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy"):
            value = os.environ.get(key)
            if value:
                return value
        return None

    # Расписание
    timezone: str = Field(default="Europe/Moscow")
    digest_time: str = Field(default="09:00")
    deadline_check_time: str = Field(default="09:30")
    # Вечернее напоминание: закрыть выполненное, подвинуть сроки.
    evening_check_time: str = Field(default="16:00")

    # Хранилище
    db_path: str = Field(default="data/bot.db")

    # Сводка по проектам (/summary).
    # Коды статусов эпиков (CmfStatus.code), которые попадают в отчёт.
    # Строкой, а не list[str]: pydantic-settings разбирает сложные типы из окружения
    # как JSON, и "in_progress,in_review" упал бы с JSONDecodeError.
    summary_epic_status_codes: str = Field(default="in_progress,in_review,pause")
    # Коды статусов задач внутри эпика. Отдельно от эпиков: расширяя фильтр эпиков
    # (напр. добавив `open`), не хочется тянуть в отчёт весь бэклог задач.
    summary_task_status_codes: str = Field(default="in_progress,in_review,pause")
    # Горизонт «под угрозой»: плановый конец в пределах N дней -> 🟡.
    summary_risk_days: int = Field(default=7)
    # Куда складывать сгенерированные HTML/CSV/JSON.
    summary_output_dir: str = Field(default="data/reports")

    def parsed_digest_time(self) -> tuple[int, int]:
        return _parse_hhmm(self.digest_time)

    def parsed_deadline_time(self) -> tuple[int, int]:
        return _parse_hhmm(self.deadline_check_time)

    def parsed_evening_time(self) -> tuple[int, int]:
        return _parse_hhmm(self.evening_check_time)

    def parsed_epic_status_codes(self) -> tuple[str, ...]:
        return _parse_csv_list(self.summary_epic_status_codes)

    def parsed_task_status_codes(self) -> tuple[str, ...]:
        return _parse_csv_list(self.summary_task_status_codes)


def _parse_hhmm(value: str) -> tuple[int, int]:
    hour_str, _, minute_str = value.partition(":")
    return int(hour_str), int(minute_str or 0)


def _parse_csv_list(value: str) -> tuple[str, ...]:
    """"a, B ,c" -> ("a", "b", "c")."""
    return tuple(part.strip().lower() for part in value.split(",") if part.strip())


@lru_cache
def get_settings() -> Settings:
    return Settings()
