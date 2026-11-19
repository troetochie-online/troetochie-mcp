"""One bounded device token cache, shared by generation and telemetry."""

import base64
import json
import os
from pathlib import Path
import stat
import tempfile
import threading
import time

import httpx

from troetochie_mcp import __version__

MAX_TOKEN_AGE = 24 * 60 * 60
MAX_CACHE_BYTES = 16_384


class TokenCache:
    def __init__(self, path: Path):
        self.path = path
        self.lock = threading.Lock()
        self.cached = None

    def _load(self):
        try:
            # A cache is optional. Do not read a linked or publicly readable credential.
            fd = os.open(self.path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
            with os.fdopen(fd, "r", encoding="utf-8") as stream:
                info = os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or info.st_size > MAX_CACHE_BYTES:
                    return None
                if hasattr(os, "getuid") and info.st_uid != os.getuid():
                    return None
                return json.load(stream)
        except (OSError, ValueError):
            return None

    def _save(self, value):
        temporary = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            fd, temporary = tempfile.mkstemp(prefix="auth-", dir=self.path.parent)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(value, stream)
            os.replace(temporary, self.path)
        except OSError:
            # Read-only homes still work with the in-memory cache.
            pass
        finally:
            if temporary is not None and os.path.exists(temporary):
                os.unlink(temporary)

    def get(self, client: httpx.Client, api: str, device: str, rejected: str | None = None) -> str:
        with self.lock:
            now = time.time()
            value = self.cached or self._load()
            if (isinstance(value, dict) and value.get("api") == api and value.get("device") == device
                    and isinstance(value.get("token"), str) and value["token"] and value["token"] != rejected
                    and isinstance(value.get("expires"), (int, float))
                    and now < value["expires"] <= now + MAX_TOKEN_AGE):
                self.cached = value
                return value["token"]
            self.cached = None
            response = client.post(f"{api}/v1/auth/device", json={"device_id_hash": device, "app_version": f"mcp-{__version__}"})
            response.raise_for_status()
            token = response.json().get("access_token")
            if not isinstance(token, str) or not token or len(token) > 8192:
                raise RuntimeError("Invalid device authorization response")
            expires = now + MAX_TOKEN_AGE
            try:
                encoded = token.split(".")[1]
                claim = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
                # This is only a cache expiry hint, never authorization validation.
                expiry = claim.get("exp")
                if type(expiry) in (int, float):
                    expires = min(expires, expiry - 60)
            except (IndexError, ValueError, AttributeError):
                pass
            self.cached = {"api": api, "device": device, "token": token, "expires": expires}
            self._save(self.cached)
            return token
