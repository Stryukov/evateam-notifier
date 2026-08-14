"""Сборка приложения: конфиг → клиент → репозиторий → транспорты → сервис."""

from __future__ import annotations

from dataclasses import dataclass

from .config import Settings, get_settings
from .core.summary import SummaryOptions
from .evateam.client import EvaTeamClient
from .evateam.portfolio import EvaTeamPortfolio
from .evateam.tasks import EvaTeamTasks
from .service import BotService
from .storage.repository import UserRepository
from .storage.db import make_session_factory
from .transports.base import BotTransport, TransportName
from .transports.telegram import TelegramTransport


@dataclass
class App:
    settings: Settings
    client: EvaTeamClient
    service: BotService
    transports: dict[TransportName, BotTransport]

    @classmethod
    def build(cls, settings: Settings | None = None) -> "App":
        settings = settings or get_settings()
        proxy = settings.resolve_proxy()

        client = EvaTeamClient(
            settings.evateam_base_url,
            settings.evateam_token,
            settings.evateam_auth_mode,
            admin_mode=settings.evateam_admin_mode,
            verify=settings.evateam_verify_ssl,
            proxy=proxy,
        )
        tasks_api = EvaTeamTasks(client, base_url=settings.evateam_base_url)
        portfolio_api = EvaTeamPortfolio(client, base_url=settings.evateam_base_url)

        session_factory = make_session_factory(settings.db_path)
        repo = UserRepository(session_factory)

        # Регистрация транспортов. Добавить MAX — просто ещё одна запись здесь.
        transports: dict[TransportName, BotTransport] = {}
        if settings.telegram_bot_token:
            tg = TelegramTransport(settings.telegram_bot_token, proxy=proxy)
            transports[tg.name] = tg

        service = BotService(
            transports=transports,
            tasks_api=tasks_api,
            repo=repo,
            portfolio_api=portfolio_api,
            summary_options=SummaryOptions(
                status_codes=settings.parsed_epic_status_codes(),
                task_status_codes=settings.parsed_task_status_codes(),
                risk_days=settings.summary_risk_days,
            ),
            report_dir=settings.summary_output_dir,
        )
        return cls(settings=settings, client=client, service=service, transports=transports)

    async def aclose(self) -> None:
        for transport in self.transports.values():
            await transport.aclose()
        await self.client.aclose()
