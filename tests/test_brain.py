import json
import stat
import pytest
from troetochie_mcp.brain import publish, validate_brain


def package():
    return {"version": 1, "product": "Продукт", "style": "Коротко, на вы", "rules": ["Не обещай сроки"],
            "facts": [{"topic": "Поэтапное подключение команды", "text": "Можно подключать сотрудников постепенно", "source": "Документация / команда"}], "examples": []}


def test_publish_is_private_pending_and_atomic(tmp_path):
    result = publish(package(), tmp_path)
    target = tmp_path / ".troetochie/support-brain/pending.json"
    assert result["status"] == "pending_review"
    assert json.loads(target.read_text()) == package()
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    changed = {**package(), "product": "Обновление"}
    publish(changed, tmp_path)
    assert json.loads(target.read_text())["product"] == "Обновление"
    assert list(target.parent.iterdir()) == [target]


@pytest.mark.parametrize("change", [{"version": True}, {"version": 2}, {"facts": []}, {"rules": ["x"] * 13},
                                    {"style": "x" * 601}, {"facts": [{"topic": "a", "text": "b", "source": ""}]}])
def test_invalid_package_never_replaces_pending(tmp_path, change):
    publish(package(), tmp_path)
    target = tmp_path / ".troetochie/support-brain/pending.json"
    before = target.read_bytes()
    with pytest.raises(ValueError):
        publish({**package(), **change}, tmp_path)
    assert target.read_bytes() == before


def test_unknown_fields_are_not_carried_into_desktop():
    assert "secret" not in validate_brain({**package(), "secret": "ignored"})
