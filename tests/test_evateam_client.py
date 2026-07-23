import httpx
import pytest
import respx

from evateam_bot.evateam.client import EvaTeamClient, EvaTeamError, _auth_headers


def test_auth_headers_modes():
    assert _auth_headers("t", "bearer") == {"Authorization": "Bearer t"}
    assert _auth_headers("t", "token") == {"Authorization": "Token t"}
    assert _auth_headers("t", "header:X-Auth-Token") == {"X-Auth-Token": "t"}
    assert _auth_headers("", "bearer") == {}


@respx.mock
async def test_call_returns_result_and_sends_jsonrpc():
    route = respx.post("https://eva.example.ru/pub/pub_api").mock(
        return_value=httpx.Response(200, json={"jsonrpc": "2.0", "result": {"ok": 1}})
    )
    async with EvaTeamClient("https://eva.example.ru/", "tok", "bearer") as client:
        result = await client.call("CmfTask.api_list", {"limit": 5})

    assert result == {"ok": 1}
    request = route.calls.last.request
    assert request.headers["Authorization"] == "Bearer tok"
    body = request.content.decode()
    assert '"method":"CmfTask.api_list"' in body
    assert '"callid"' in body


@respx.mock
async def test_call_raises_on_error():
    respx.post("https://eva.example.ru/pub/pub_api").mock(
        return_value=httpx.Response(
            200, json={"jsonrpc": "2.0", "error": {"code": -32601, "message": "no method"}}
        )
    )
    async with EvaTeamClient("https://eva.example.ru", "tok") as client:
        with pytest.raises(EvaTeamError) as exc:
            await client.call("Bad.method")
    assert exc.value.code == -32601
