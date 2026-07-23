import httpx
import pytest
import respx

from evateam_bot.evateam.client import (
    EvaTeamClient,
    EvaTeamError,
    _auth_headers,
    _parse_verify,
)


def test_parse_verify():
    assert _parse_verify(True) is True
    assert _parse_verify(False) is False
    assert _parse_verify("true") is True
    assert _parse_verify("false") is False
    assert _parse_verify("C:\\certs\\ca.pem") == "C:\\certs\\ca.pem"


def test_auth_headers_modes():
    assert _auth_headers("t", "bearer") == {"Authorization": "Bearer t"}
    assert _auth_headers("t", "token") == {"Authorization": "Token t"}
    assert _auth_headers("t", "header:X-Auth-Token") == {"X-Auth-Token": "t"}
    assert _auth_headers("", "bearer") == {}


@respx.mock
async def test_call_returns_result_and_sends_jsonrpc():
    route = respx.post("https://eva.example.ru/api/").mock(
        return_value=httpx.Response(200, json={"jsonrpc": "2.0", "result": [{"ok": 1}]})
    )
    async with EvaTeamClient("https://eva.example.ru/", "tok", "bearer") as client:
        result = await client.call(
            "CmfTask.list", kwargs={"filter": [["code", "==", "X-1"]]}
        )

    assert result == [{"ok": 1}]
    request = route.calls.last.request
    assert request.headers["Authorization"] == "Bearer tok"
    body = request.content.decode()
    assert '"method":"CmfTask.list"' in body
    assert '"jsonrpc":"2.2"' in body
    assert '"callid"' in body
    # admin_mode по умолчанию включён
    assert '"admin_mode":true' in body
    assert '"filter"' in body


@respx.mock
async def test_admin_mode_can_be_disabled():
    route = respx.post("https://eva.example.ru/api/").mock(
        return_value=httpx.Response(200, json={"jsonrpc": "2.0", "result": []})
    )
    async with EvaTeamClient(
        "https://eva.example.ru", "tok", "bearer", admin_mode=False
    ) as client:
        await client.call("CmfTask.list")
    assert "admin_mode" not in route.calls.last.request.content.decode()


@respx.mock
async def test_call_raises_on_error():
    respx.post("https://eva.example.ru/api/").mock(
        return_value=httpx.Response(
            200, json={"jsonrpc": "2.0", "error": {"code": -32601, "message": "no method"}}
        )
    )
    async with EvaTeamClient("https://eva.example.ru", "tok") as client:
        with pytest.raises(EvaTeamError) as exc:
            await client.call("Bad.method")
    assert exc.value.code == -32601
