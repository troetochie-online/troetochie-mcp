"""MCP-сервер Троеточия для Claude и Codex.

Инструменты:
- search_recent_chats — найти в недавних чатах Claude Code и Codex то, что относится к вопросу;
- suggest_replies — три варианта ответа собеседнику с учётом найденного (через бэкенд Троеточия).
"""

import hashlib
import time
import json
import os
import uuid
from typing import List, Literal
from pathlib import Path

import httpx
from mcp.server.mcpserver import MCPServer

from troetochie_mcp.chats import search
from troetochie_mcp.brain import publish
from troetochie_mcp.auth import TokenCache
from troetochie_mcp.privacy import redact

API = os.environ.get("TROETOCHIE_API", "https://api.troetochie.online").rstrip("/")
Tone = Literal["confident", "calm", "short", "humor", "flirt", "work"]

mcp = MCPServer("troetochie")

# Сессия = один запуск MCP-сервера: Claude Code / Codex поднимает его на сессию работы
SESSION = "mcp-" + uuid.uuid4().hex[:16]
TOKENS = TokenCache(Path.home() / ".troetochie" / "mcp" / "auth.json")


def _track(tool: str, ok: bool, started: float, **props) -> None:
    """Вызов инструмента в аналитику: имя, успех, время, счётчики. Текст запроса не отправляем.
    Ошибка отправки не должна ломать сам инструмент."""
    try:
        with httpx.Client(timeout=3) as client:
            _post(client, "/v1/events",
                json={"session": SESSION, "events": [{"name": "mcp_tool_called", "ts": int(time.time() * 1000),
                      "props": {"tool": tool, "ok": ok, "ms": int((time.monotonic() - started) * 1000), **props}}]},
            )
    except Exception:
        pass


@mcp.tool()
def search_recent_chats(query: str, limit: int = 3) -> List[str]:
    """Ищет в чатах Claude Code и Codex за последние две недели обмены «вопрос → ответ»,
    похожие на query. Всё читается локально. Полезно, чтобы ответить собеседнику по существу."""
    started = time.monotonic()
    found = search(query, max(1, min(limit, 5)))
    _track("search_recent_chats", True, started, results=len(found))
    return found


def _token(client: httpx.Client) -> str:
    device = hashlib.sha256(("aikb-mcp:" + str(uuid.getnode())).encode()).hexdigest()
    return TOKENS.get(client, API, device)


def _post(client: httpx.Client, path: str, **kwargs) -> httpx.Response:
    token = _token(client)
    headers = {"Authorization": f"Bearer {token}", "X-Session-Id": SESSION}
    response = client.post(f"{API}{path}", headers=headers, **kwargs)
    if response.status_code == 401:
        response.close()
        device = hashlib.sha256(("aikb-mcp:" + str(uuid.getnode())).encode()).hexdigest()
        headers["Authorization"] = f"Bearer {TOKENS.get(client, API, device, rejected=token)}"
        response = client.post(f"{API}{path}", headers=headers, **kwargs)
    return response


@mcp.tool()
def suggest_replies(message: str, tone: Tone = "confident", draft: str = "", use_recent_chats: bool = False) -> List[str]:
    """Три варианта ответа через сервер Троеточия. Текст сообщения и черновика отправляется серверу.
    use_recent_chats=True дополнительно отправляет подходящие выдержки из локальных чатов
    помощников разработки. Включай это только по явному разрешению пользователя на передачу истории."""
    started = time.monotonic()
    notes = search(f"{message}\n{draft}") if use_recent_chats else []
    try:
        variants = _suggest(message, tone, draft, notes)
    except Exception:
        _track("suggest_replies", False, started, tone=tone)
        raise
    _track("suggest_replies", True, started, results=len(variants), tone=tone)
    return variants


def _suggest(message: str, tone: str, draft: str, notes: List[str]) -> List[str]:
    with httpx.Client(timeout=60) as client:
        r = _post(client, "/v1/suggest",
            json={
                "context": [{"role": "them", "text": redact(message)[:2000]}] if message.strip() else [],
                "draft": redact(draft)[:2000],
                "tone": tone,
                "target_app": "mcp",
                "notes": [redact(n)[:1500] for n in notes[:5]],
            },
        )
        r.raise_for_status()
    return _parse_variants(r.text)


def _parse_variants(stream: str) -> List[str]:
    """Only a terminal done event confirms a complete answer, even after variant.done."""
    variants, event = {}, ""
    for line in stream.splitlines():
        if line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("data:"):
            try:
                data = json.loads(line[5:])
            except ValueError as error:
                raise RuntimeError("Invalid generation stream") from error
            if event == "error":
                raise RuntimeError("Generation failed")
            if event == "variant.done":
                index = data.get("index") if isinstance(data, dict) else None
                text = data.get("text") if isinstance(data, dict) else None
                if type(index) is not int or not 0 <= index < 3 or not isinstance(text, str) or not text.strip():
                    raise RuntimeError("Invalid generation variant")
                variants[index] = text
            elif event == "done":
                if not variants:
                    raise RuntimeError("Generation returned no variants")
                return [variants[i] for i in sorted(variants)]
    raise RuntimeError("Generation stream ended before completion")


@mcp.tool()
def publish_support_brain(brain: dict) -> dict:
    """Teach Troetochie using the product knowledge in this conversation.
    Supply version=1, product, style, rules (up to 12 strings, 200 chars each),
    facts (up to 80 objects: topic <=100, text <=1000, source <=200 chars),
    examples (up to 20 objects: question <=300, answer <=500 chars).
    Only include verified facts with identifiable sources; do not invent missing details.
    Do not include credentials or customer personal data. Publishes locally on this Mac.
    The user must review and enable the package in Troetochie before it affects replies.
    """
    return publish(brain)


def main():
    mcp.run()


if __name__ == "__main__":
    main()
