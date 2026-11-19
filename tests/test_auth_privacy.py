import base64
import json
import stat
import time
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest

from troetochie_mcp import server
from troetochie_mcp.auth import TokenCache
from troetochie_mcp.privacy import redact


COMPLETE = 'event: variant.done\ndata: {"index":0,"text":"Hello"}\n\nevent: done\ndata: {}\n\n'


@pytest.fixture
def transport(monkeypatch, tmp_path):
    calls = []
    def handle(request):
        calls.append(request)
        if request.url.path == "/v1/auth/device":
            return httpx.Response(200, json={"access_token": "token"})
        return httpx.Response(200, text=COMPLETE)
    factory = httpx.Client
    monkeypatch.setattr(server.httpx, "Client", lambda **kwargs: factory(transport=httpx.MockTransport(handle), **kwargs))
    monkeypatch.setattr(server, "TOKENS", TokenCache(tmp_path / "auth.json"))
    return calls


def test_twenty_generations_and_telemetry_use_one_authorization(transport):
    for _ in range(20):
        assert server.suggest_replies("Hello") == ["Hello"]
    assert sum(r.url.path == "/v1/auth/device" for r in transport) == 1
    assert sum(r.url.path == "/v1/suggest" for r in transport) == 20
    assert sum(r.url.path == "/v1/events" for r in transport) == 20


def test_default_does_not_read_local_history(monkeypatch, transport):
    monkeypatch.setattr(server, "search", lambda *args: pytest.fail("Local history must be opt-in"))
    server.suggest_replies("Hello")
    request = next(r for r in transport if r.url.path == "/v1/suggest")
    assert json.loads(request.content)["notes"] == []


def test_explicit_history_and_all_outbound_text_redact_secrets(monkeypatch, transport):
    monkeypatch.setattr(server, "search", lambda *args: ["notes api_key: note-secret"])
    server.suggest_replies("message password: short", draft="Bearer abcdefghijklmnop", use_recent_chats=True)
    request = next(r for r in transport if r.url.path == "/v1/suggest")
    body = json.loads(request.content)
    assert body["context"][0]["text"] == "message password: [скрыто]"
    assert body["draft"] == "Bearer [скрыто]"
    assert body["notes"] == ["notes api_key: [скрыто]"]
    for r in transport:
        if r.url.path == "/v1/events":
            assert all(value not in r.content.decode() for value in ["message", "notes", "short", "abcdefghijklmnop"])


def test_401_refreshes_and_retries_only_once(monkeypatch, tmp_path):
    paths = []
    def handle(request):
        paths.append(request.url.path)
        if request.url.path == "/v1/auth/device":
            return httpx.Response(200, json={"access_token": f"token-{len(paths)}"})
        return httpx.Response(401)
    monkeypatch.setattr(server, "TOKENS", TokenCache(tmp_path / "auth.json"))
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        assert server._post(client, "/v1/suggest", json={}).status_code == 401
    assert paths == ["/v1/auth/device", "/v1/suggest", "/v1/auth/device", "/v1/suggest"]


def test_cache_is_private_and_reused_after_restart(tmp_path):
    path = tmp_path / "auth.json"
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"access_token": "secret"}))) as client:
        assert TokenCache(path).get(client, "https://example.org", "device") == "secret"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    with httpx.Client(transport=httpx.MockTransport(lambda _: pytest.fail("Unexpected authorization"))) as client:
        assert TokenCache(path).get(client, "https://example.org", "device") == "secret"


@pytest.mark.parametrize("change", ["expired", "wrong_api", "wrong_device", "public", "oversized"])
def test_invalid_cache_is_not_reused(tmp_path, change):
    path = tmp_path / "auth.json"
    value = {"api": "https://example.org", "device": "device", "token": "old", "expires": time.time() + 600}
    if change == "expired": value["expires"] = time.time() - 1
    if change == "wrong_api": value["api"] = "https://other.example.org"
    if change == "wrong_device": value["device"] = "other-device"
    if change == "oversized": value["token"] = "x" * 20_000
    path.write_text(json.dumps(value)); path.chmod(0o644 if change == "public" else 0o600)
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"access_token": "new"}))) as client:
        assert TokenCache(path).get(client, "https://example.org", "device") == "new"


def test_concurrent_calls_share_single_authorization(tmp_path):
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(200, json={"access_token": "secret"})
    cache = TokenCache(tmp_path / "auth.json")
    with httpx.Client(transport=httpx.MockTransport(handle)) as client, ThreadPoolExecutor(max_workers=8) as pool:
        assert list(pool.map(lambda _: cache.get(client, "https://example.org", "device"), range(20))) == ["secret"] * 20
    assert len(calls) == 1


def test_expiry_hint_refreshes_before_expiration(monkeypatch, tmp_path):
    now = time.time()
    claim = base64.urlsafe_b64encode(json.dumps({"exp": now + 120}).encode()).decode().rstrip("=")
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(200, json={"access_token": f"header.{claim}.signature"})
    cache = TokenCache(tmp_path / "auth.json")
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        cache.get(client, "https://example.org", "device")
        monkeypatch.setattr("troetochie_mcp.auth.time.time", lambda: now + 61)
        cache.get(client, "https://example.org", "device")
    assert len(calls) == 2


def test_private_key_and_github_pat_are_redacted():
    assert redact("-----BEGIN PRIVATE KEY-----\nprivate material\n-----END PRIVATE KEY-----") == "[скрыто]"
    assert redact("github_pat_" + "a" * 50) == "[скрыто]"
