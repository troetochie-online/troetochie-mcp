"""Remove common credentials before text leaves a local chat log or this process."""

import re

PATTERNS = [
    (re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----.*?-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----", re.S), "[скрыто]"),
    (re.compile(r"\b(Bearer\s+)[A-Za-z0-9._~+/-]{12,}=*", re.I), r"\1[скрыто]"),
    (re.compile(r"(api[_ -]?key|access[_ -]?token|secret|password|пароль|токен)(\s*[:=]\s*)\S+", re.I), r"\1\2[скрыто]"),
    (re.compile(r"([?&](?:access_)?(?:token|key|secret|signature)=)[^&\s]+", re.I), r"\1[скрыто]"),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{16,}"), "[скрыто]"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}|\bgithub_pat_[A-Za-z0-9_]{20,}"), "[скрыто]"),
]


def redact(text: str) -> str:
    for pattern, replacement in PATTERNS:
        text = pattern.sub(replacement, text)
    return text
