"""Local accounts — stored on this laptop only, never synced anywhere.

Passwords: PBKDF2-HMAC-SHA256, 200k iterations, per-user random salt (stdlib only).
Sessions : random 256-bit tokens in an HttpOnly, SameSite=Strict cookie; persisted to
           disk (hashed) so a restart doesn't log everyone out.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import threading
import time
from pathlib import Path

ITERATIONS = 200_000
SESSION_TTL_S = 30 * 24 * 3600
USERNAME_RE = re.compile(r"^[a-z0-9_.-]{3,32}$")


class AuthError(Exception):
    pass


def _hash_pw(password: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt, ITERATIONS).hex()


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class AuthStore:
    def __init__(self, data_dir: str | Path):
        self.dir = Path(data_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.users_path = self.dir / "users.json"
        self.sessions_path = self.dir / "auth_sessions.json"
        self._lock = threading.Lock()
        self.users: dict = self._read(self.users_path)
        self.sessions: dict = self._read(self.sessions_path)

    @staticmethod
    def _read(p: Path) -> dict:
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def _save(self):
        self.users_path.write_text(json.dumps(self.users, indent=2), encoding="utf-8")
        self.sessions_path.write_text(json.dumps(self.sessions), encoding="utf-8")

    # ---------------------------------------------------------------- accounts
    def register(self, username: str, password: str, name: str = "") -> dict:
        username = (username or "").strip().lower()
        if not USERNAME_RE.match(username):
            raise AuthError("Username: 3–32 chars, letters, numbers, . _ -")
        if len(password or "") < 6:
            raise AuthError("Password must be at least 6 characters")
        with self._lock:
            if username in self.users:
                raise AuthError("That username is taken")
            salt = secrets.token_bytes(16)
            self.users[username] = {
                "name": (name or username).strip()[:60],
                "salt": salt.hex(),
                "hash": _hash_pw(password, salt),
                "created": time.time(),
                "prefs": {"target": "hin_Deva"},
            }
            self._save()
        return self.public(username)

    def verify(self, username: str, password: str) -> dict:
        username = (username or "").strip().lower()
        u = self.users.get(username)
        # Hash anyway when the user doesn't exist so timing doesn't leak which usernames exist.
        salt = bytes.fromhex(u["salt"]) if u else b"\0" * 16
        ok = hmac.compare_digest(_hash_pw(password or "", salt), u["hash"] if u else "0" * 64)
        if not (u and ok):
            raise AuthError("Wrong username or password")
        return self.public(username)

    def public(self, username: str) -> dict:
        u = self.users[username]
        return {"username": username, "name": u["name"], "prefs": u.get("prefs", {})}

    def set_pref(self, username: str, key: str, value):
        with self._lock:
            self.users[username].setdefault("prefs", {})[key] = value
            self._save()

    # ---------------------------------------------------------------- sessions
    def create_session(self, username: str) -> str:
        token = secrets.token_urlsafe(32)
        with self._lock:
            now = time.time()
            self.sessions = {k: v for k, v in self.sessions.items() if v["exp"] > now}
            self.sessions[_hash_token(token)] = {"user": username, "exp": now + SESSION_TTL_S}
            self._save()
        return token

    def user_for(self, token: str | None) -> str | None:
        if not token:
            return None
        s = self.sessions.get(_hash_token(token))
        if not s or s["exp"] < time.time() or s["user"] not in self.users:
            return None
        return s["user"]

    def revoke(self, token: str | None):
        if token:
            with self._lock:
                self.sessions.pop(_hash_token(token), None)
                self._save()
