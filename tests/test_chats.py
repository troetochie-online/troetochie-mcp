import json

from troetochie_mcp.chats import parse_line, search
import pytest


def test_finds_exchange_in_claude_and_codex_logs(tmp_path):
    claude = tmp_path / ".claude/projects/p"
    codex = tmp_path / ".codex/sessions/2026/10/01"
    claude.mkdir(parents=True)
    codex.mkdir(parents=True)
    (claude / "a.jsonl").write_text(
        json.dumps({"type": "user", "message": {"role": "user", "content": "Когда релиз мобильного приложения?"}}, ensure_ascii=False)
        + "\n"
        + json.dumps({"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "Релиз перенесли на пятницу."}]}}, ensure_ascii=False)
        + "\n"
    )
    (codex / "b.jsonl").write_text(
        json.dumps({"type": "response_item", "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "Почини миграции базы"}]}}, ensure_ascii=False)
        + "\n"
        + json.dumps({"type": "response_item", "payload": {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "Миграции базы исправлены."}]}}, ensure_ascii=False)
        + "\n"
    )
    hits = search("А релиз приложения когда будет?", home=tmp_path)
    assert len(hits) == 1 and "пятницу" in hits[0]
    assert "исправлены" in search("миграции базы", home=tmp_path)[0]
    assert search("погода", home=tmp_path) == []


@pytest.mark.parametrize("value", [
    [{"type": "user"}], {"type": "user", "message": "invalid"},
    {"type": "response_item", "payload": "invalid"},
    {"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": 123}]}},
])
def test_malformed_chat_entries_are_skipped(value):
    assert parse_line(json.dumps(value)) is None


def test_secrets_are_removed_before_clipping_chat_excerpts(tmp_path):
    root = tmp_path / ".claude/projects/p"
    root.mkdir(parents=True)
    messages = [
        {"type": "user", "message": {"role": "user", "content": "Ключ проекта api_key: secret-value"}},
        {"type": "assistant", "message": {"role": "assistant", "content": "Ключ проекта обновлен github_pat_" + "a" * 50}},
    ]
    (root / "a.jsonl").write_text("\n".join(json.dumps(m) for m in messages))
    hits = search("ключ проекта", home=tmp_path)
    assert len(hits) == 1
    assert "secret-value" not in hits[0] and "github_pat_" not in hits[0]
    assert hits[0].count("[скрыто]") == 2
