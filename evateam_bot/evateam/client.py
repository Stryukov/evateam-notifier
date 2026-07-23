"""Тонкий асинхронный JSON-RPC клиент EvaTeam (протокол jsonrpc 2.2).

Эндпоинт: POST {base}/api/   (с завершающим слэшем; Authorization: Bearer <token>)
Тело:     {"jsonrpc":"2.2","callid":"<uuid>","method":"Class.method",
           "kwargs":{"filter":[...],"fields":[...],"order_by":[...]},
           "flags":{"admin_mode":true}}
Ответ:    {"jsonrpc":"2.0","result":...} | {..."error":{"code","message"}}

filter: список условий [["field","op",value], ...] (И-логика).
        Операторы: == != < > <= >= LIKE ("%текст%") EXISTS.
        Связи: одиночная — ["responsible.id","==",id]; множественная — ["executors.id","==",id].
"""

from __future__ import annotations

import ssl
import uuid
from typing import Any

import httpx

# Значения EVATEAM_VERIFY_SSL, включающие проверку по системному хранилищу ОС
# (Windows/macOS/Linux) — в нём уже есть корпоративные CA (прокси, Kaspersky и т.п.).
_SYSTEM_STORE_ALIASES = {"system", "os", "truststore", "winstore"}


def _build_verify(value: bool | str):
    """Вернуть значение для httpx `verify`: bool, путь к CA или ssl.SSLContext."""
    if isinstance(value, str) and value.strip().lower() in _SYSTEM_STORE_ALIASES:
        import truststore

        return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    return _parse_verify(value)


class EvaTeamError(RuntimeError):
    """Ошибка, вернувшаяся в поле `error` JSON-RPC ответа."""

    def __init__(self, code: int | None, message: str, data: Any = None) -> None:
        super().__init__(f"EvaTeam API error {code}: {message}")
        self.code = code
        self.message = message
        self.data = data


def _parse_verify(value: bool | str) -> bool | str:
    """Интерпретировать настройку проверки TLS.

    True / False — включить/выключить проверку; строка-путь — использовать как CA-бандл.
    """
    if isinstance(value, bool):
        return value
    text = value.strip()
    low = text.lower()
    if low in {"true", "1", "yes", "on", ""}:
        return True
    if low in {"false", "0", "no", "off"}:
        return False
    return text  # путь к CA-бандлу (.pem)


def _auth_headers(token: str, auth_mode: str) -> dict[str, str]:
    """Собрать заголовок аутентификации по режиму из настроек.

    Точный режим для вашего инстанса подтверждается через evateam/smoke.py.
    """
    if not token:
        return {}
    mode = auth_mode.strip().lower()
    if mode == "bearer":
        return {"Authorization": f"Bearer {token}"}
    if mode == "token":
        return {"Authorization": f"Token {token}"}
    if mode.startswith("header:"):
        header_name = auth_mode.split(":", 1)[1].strip() or "X-Auth-Token"
        return {header_name: token}
    # По умолчанию — Bearer.
    return {"Authorization": f"Bearer {token}"}


class EvaTeamClient:
    def __init__(
        self,
        base_url: str,
        token: str,
        auth_mode: str = "bearer",
        *,
        admin_mode: bool = True,
        timeout: float = 30.0,
        verify: bool | str = True,
        proxy: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        # Аутентифицированный JSON-RPC эндпоинт EvaTeam — {base}/api/ (со слэшем).
        self._url = f"{base_url.rstrip('/')}/api/"
        self._headers = {
            "Content-Type": "application/json",
            **_auth_headers(token, auth_mode),
        }
        # admin_mode позволяет сервис-аккаунту (из группы Admins) видеть чужие объекты.
        self._default_flags: dict[str, Any] = {"admin_mode": True} if admin_mode else {}
        self._owns_client = client is None
        # trust_env=False -> прокси управляется только параметром `proxy` (из .env),
        # без неявного чтения системных HTTPS_PROXY/HTTP_PROXY.
        self._client = client or httpx.AsyncClient(
            timeout=timeout,
            verify=_build_verify(verify),
            proxy=proxy,
            trust_env=False,
        )

    async def call(
        self,
        method: str,
        *,
        kwargs: dict[str, Any] | None = None,
        args: Any = None,
        flags: dict[str, Any] | None = None,
    ) -> Any:
        """Вызвать метод EvaTeam (JSON-RPC 2.2) и вернуть содержимое `result`.

        `kwargs` — словарь запроса: filter / fields / order_by (см. evateam/tasks.py).
        """
        payload: dict[str, Any] = {
            "jsonrpc": "2.2",
            "callid": str(uuid.uuid4()),
            "method": method,
        }
        if args is not None:
            payload["args"] = args
        if kwargs is not None:
            payload["kwargs"] = kwargs
        effective_flags = self._default_flags if flags is None else flags
        if effective_flags:
            payload["flags"] = effective_flags
        response = await self._client.post(self._url, json=payload, headers=self._headers)
        response.raise_for_status()
        data = response.json()
        if isinstance(data, dict) and data.get("error"):
            err = data["error"]
            raise EvaTeamError(
                code=err.get("code"),
                message=err.get("message", "unknown"),
                data=err.get("data"),
            )
        return data.get("result") if isinstance(data, dict) else data

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> EvaTeamClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()
