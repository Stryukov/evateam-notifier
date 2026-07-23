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
    # Прокси для доступа к api.telegram.org (корп-сеть). Пусто -> берём из
    # окружения (HTTPS_PROXY/HTTP_PROXY). "none" -> без прокси (прямое соединение).
    telegram_proxy: str = Field(default="")

    def resolve_telegram_proxy(self) -> str | None:
        raw = self.telegram_proxy.strip()
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

    # Хранилище
    db_path: str = Field(default="data/bot.db")

    def parsed_digest_time(self) -> tuple[int, int]:
        return _parse_hhmm(self.digest_time)

    def parsed_deadline_time(self) -> tuple[int, int]:
        return _parse_hhmm(self.deadline_check_time)


def _parse_hhmm(value: str) -> tuple[int, int]:
    hour_str, _, minute_str = value.partition(":")
    return int(hour_str), int(minute_str or 0)


@lru_cache
def get_settings() -> Settings:
    return Settings()
