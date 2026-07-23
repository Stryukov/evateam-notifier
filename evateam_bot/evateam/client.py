"""Тонкий асинхронный JSON-RPC 2.0 клиент EvaTeam.

Эндпоинт: POST {base}/pub/pub_api?m=<Class>.<method>
Тело:     {"jsonrpc":"2.0","method":"Class.method","params":{...},"callid":"<uuid>"}
Ответ:    {"jsonrpc":"2.0","result":...} | {"jsonrpc":"2.0","error":{"code","message"}}
"""

from __future__ import annotations

import uuid
from typing import Any

import httpx


class EvaTeamError(RuntimeError):
    """Ошибка, вернувшаяся в поле `error` JSON-RPC ответа."""

    def __init__(self, code: int | None, message: str, data: Any = None) -> None:
        super().__init__(f"EvaTeam API error {code}: {message}")
        self.code = code
        self.message = message
        self.data = data


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
        timeout: float = 30.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._headers = {
            "Content-Type": "application/json",
            **_auth_headers(token, auth_mode),
        }
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(timeout=timeout)

    async def call(self, method: str, params: dict[str, Any] | None = None) -> Any:
        """Вызвать метод EvaTeam и вернуть содержимое `result`."""
        url = f"{self._base_url}/pub/pub_api?m={method}"
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params or {},
            "callid": str(uuid.uuid4()),
            "id": str(uuid.uuid4()),
        }
        response = await self._client.post(url, json=payload, headers=self._headers)
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
