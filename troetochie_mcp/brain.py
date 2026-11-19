"""Local handoff from an expert assistant. Publishing never activates knowledge."""
import json
import os
from pathlib import Path
import tempfile

MAX_BYTES = 128_000


def validate_brain(value: dict) -> dict:
    if not isinstance(value, dict) or type(value.get("version")) is not int or value["version"] != 1:
        raise ValueError("Expected support brain version 1")

    def text(v, limit):
        if not isinstance(v, str) or not v.strip() or len(v) > limit:
            raise ValueError(f"Expected non-empty text, at most {limit} characters")
        return v.strip()

    def rows(key, limit, parse):
        items = value.get(key, [])
        if not isinstance(items, list) or len(items) > limit:
            raise ValueError(f"Invalid {key}: at most {limit} entries")
        return [parse(item) for item in items]

    def fact(item):
        if not isinstance(item, dict):
            raise ValueError("Invalid fact")
        return {"topic": text(item.get("topic"), 100), "text": text(item.get("text"), 1000),
                "source": text(item.get("source"), 200)}

    def example(item):
        if not isinstance(item, dict):
            raise ValueError("Invalid example")
        return {"question": text(item.get("question"), 300), "answer": text(item.get("answer"), 500)}

    brain = {"version": 1, "product": text(value.get("product"), 100),
             "style": text(value.get("style"), 600),
             "rules": rows("rules", 12, lambda v: text(v, 200)),
             "facts": rows("facts", 80, fact), "examples": rows("examples", 20, example)}
    if not brain["facts"]:
        raise ValueError("At least one sourced product fact is required")
    if len(json.dumps(brain, ensure_ascii=False).encode()) > MAX_BYTES:
        raise ValueError("Support brain exceeds 128 KB")
    return brain


def publish(brain: dict, home: Path | None = None) -> dict:
    brain = validate_brain(brain)
    directory = (home or Path.home()) / ".troetochie" / "support-brain"
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix="pending-", suffix=".json", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(brain, stream, ensure_ascii=False)
        os.replace(temporary, directory / "pending.json")
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return {"status": "pending_review", "product": brain["product"], "facts": len(brain["facts"]),
            "next": "Open Troetochie settings → Знания продукта. Review and enable for a writing scenario."}
