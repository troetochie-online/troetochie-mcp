"""Поиск по недавним чатам Claude Code и Codex. Та же логика, что в desktop/src-tauri/src/chats.rs."""

import json
import re
import time
from pathlib import Path
from typing import Iterator, List, Optional, Set, Tuple

from troetochie_mcp.privacy import redact

MAX_AGE_S = 14 * 24 * 3600
MAX_FILES = 80
MAX_FILE_BYTES = 30 * 1024 * 1024
SNIPPET_CHARS = 700

STOP = {
    "это", "этот", "чтобы", "когда", "какой", "какая", "какие", "может", "можно", "нужно", "будет", "есть", "тебя",
    "меня", "просто", "только", "очень", "сейчас", "тоже", "вообще", "that", "this", "with", "what", "have", "from",
    "your", "there", "about", "would", "could",
}
MARKER = re.compile(r'"type":\s*"(user|assistant|response_item)"')


def stems(text: str) -> Set[str]:
    """Грубый стемминг: нижний регистр и первые 5 букв."""
    return {w[:5] for w in re.findall(r"\w+", text.lower()) if len(w) >= 4 and w not in STOP}


def _text_of(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            i["text"] for i in content if isinstance(i, dict) and i.get("type") in ("text", "input_text", "output_text")
            and isinstance(i.get("text"), str)
        )
    return ""


def parse_line(line: str) -> Optional[Tuple[bool, str]]:
    """(это пользователь?, текст) или None для служебных строк."""
    if not MARKER.search(line) or '"tool_result"' in line:
        return None
    try:
        v = json.loads(line)
    except ValueError:
        return None
    if not isinstance(v, dict):
        return None
    kind = v.get("type")
    if kind in ("user", "assistant") and not v.get("isMeta") and not v.get("isSidechain"):
        msg = v.get("message") or {}
    elif kind == "response_item" and isinstance(v.get("payload"), dict) and v["payload"].get("type") == "message":
        msg = v["payload"]
    else:
        return None
    if not isinstance(msg, dict):
        return None
    role = msg.get("role")
    if role not in ("user", "assistant"):
        return None
    text = _text_of(msg.get("content")).strip()
    if not text or text.startswith("<"):
        return None
    return role == "user", text


def recent_files(home: Path) -> List[Path]:
    now = time.time()
    files = []
    for root in (home / ".claude" / "projects", home / ".codex" / "sessions"):
        if not root.is_dir():
            continue
        for p in root.rglob("*.jsonl"):
            try:
                st = p.stat()
            except OSError:
                continue
            if now - st.st_mtime < MAX_AGE_S and st.st_size <= MAX_FILE_BYTES:
                files.append((st.st_mtime, p))
    files.sort(reverse=True)
    return [p for _, p in files[:MAX_FILES]]


def _clip(s: str, n: int) -> str:
    s = " ".join(s.split())
    return s if len(s) <= n else s[:n] + "…"


def exchanges(path: Path) -> Iterator[Tuple[Set[str], str]]:
    try:
        with path.open(encoding="utf-8", errors="ignore") as f:
            turns = [t for t in map(parse_line, f) if t]
    except OSError:
        return
    for i, (is_user, text) in enumerate(turns):
        if not is_user:
            continue
        answer = []
        for u, t in turns[i + 1 :]:
            if u:
                break
            answer.append(t)
        if answer:
            a = "\n".join(answer)
            yield stems(text + "\n" + a), f"Вопрос: {_clip(redact(text), 200)} → Ответ: {_clip(redact(a), SNIPPET_CHARS)}"


def search(query: str, limit: int = 3, home: Optional[Path] = None) -> List[str]:
    q = stems(query)
    if not q:
        return []
    need = 1 if len(q) <= 2 else 2
    hits = []
    for path in recent_files(home or Path.home()):
        for st, snippet in exchanges(path):
            score = len(q & st)
            if score >= need:
                hits.append((score, snippet))
    hits.sort(key=lambda h: -h[0])  # устойчиво: при равном счёте выигрывает более свежий файл
    out, seen = [], set()
    for _, s in hits:
        if s not in seen:
            seen.add(s)
            out.append(s)
        if len(out) == limit:
            break
    return out
