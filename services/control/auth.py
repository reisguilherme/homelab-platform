"""Opaque local sessions. Passwords, PVE tickets and challenges never reach SQLite."""

import json
import re
import secrets
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from urllib.parse import unquote

from .models import ControlError, require, utc

COOKIE = "__Host-homelab-session"


@dataclass(repr=False)
class Session:
    user: str
    ticket: str = field(repr=False)
    upstream_csrf: str = field(repr=False)
    csrf: str = field(repr=False)
    expires: float
    last_seen: float


class SessionStore:
    def __init__(self, clock=time.time):
        self.clock = clock
        self.sessions = {}
        self.challenges = {}
        self.attempts = defaultdict(deque)
        self.lock = threading.RLock()

    def rate_limit(self, key):
        with self.lock:
            now = self.clock()
            self.attempts = defaultdict(
                deque,
                {
                    k: deque(t for t in v if t > now - 60)
                    for k, v in self.attempts.items()
                    if v and v[-1] > now - 60
                },
            )
            attempts = self.attempts[key]
            require(
                len(attempts) < 5 and len(self.attempts) < 2000,
                "rate_limit",
                "Muitas tentativas; aguarde um minuto.",
                429,
            )
            attempts.append(now)

    def accept(self, result):
        with self.lock:
            now = self.clock()
            self.sessions = {
                k: v
                for k, v in self.sessions.items()
                if now < v.expires and now - v.last_seen < 1800
            }
            self.challenges = {k: v for k, v in self.challenges.items() if v["expires"] > now}
            token, user = result.get("ticket", ""), result.get("username", "")
            if result.get("NeedTFA") or "!tfa!" in token:
                match = re.match(r"^PVE:!tfa!([^:]+):", token)
                try:
                    info = json.loads(unquote(match[1])) if match else {}
                except (ValueError, TypeError):
                    info = {}
                require(
                    info.get("totp") is True,
                    "tfa_unsupported",
                    "Use TOTP ou o console Proxmox para este método de autenticação.",
                    409,
                )
                require(len(self.challenges) < 1000, "busy", "Tente novamente mais tarde.", 503)
                challenge = secrets.token_urlsafe(32)
                self.challenges[challenge] = {"ticket": token, "user": user, "expires": now + 300}
                return None, {
                    "authenticated": False,
                    "challenge": {"kind": "totp", "id": challenge, "expiresAt": utc(now + 300)},
                }
            timestamp = re.match(r"^PVE:[^:]+:([0-9a-fA-F]+)::", token)
            require(
                timestamp is not None and bool(user) and bool(result.get("CSRFPreventionToken")),
                "authentication",
                "Autenticação incompleta.",
                401,
            )
            expiry = min(now + 7200, int(timestamp[1], 16) + 7200)
            require(expiry > now, "authentication", "Ticket expirado.", 401)
            require(len(self.sessions) < 1000, "busy", "Tente novamente mais tarde.", 503)
            key = secrets.token_urlsafe(32)
            session = Session(
                user, token, result["CSRFPreventionToken"], secrets.token_urlsafe(32), expiry, now
            )
            self.sessions[key] = session
            return key, self.dto(session)

    def challenge(self, key):
        with self.lock:
            result = self.challenges.pop(key, None)
            require(
                result is not None and result["expires"] > self.clock(),
                "challenge_expired",
                "Desafio expirado; entre novamente.",
                401,
            )
            return result

    def get(self, key):
        with self.lock:
            session = self.sessions.get(key)
            now = self.clock()
            if session is None or session.expires <= now or now - session.last_seen >= 1800:
                self.sessions.pop(key, None)
                raise ControlError(401, "session_required", "Entre novamente para continuar.")
            session.last_seen = now
            return session

    def drop(self, key):
        with self.lock:
            self.sessions.pop(key, None)

    @staticmethod
    def dto(session):
        return {
            "authenticated": True,
            "user": session.user,
            "csrfToken": session.csrf,
            "expiresAt": utc(session.expires),
        }


def check_origin(request, origin):
    require(request.headers.get("origin") == origin, "origin_denied", "Origem não permitida.", 403)
    require(
        request.headers.get("sec-fetch-site", "same-origin") in ("same-origin", "none"),
        "origin_denied",
        "Origem não permitida.",
        403,
    )
    if request.method != "DELETE" or request.headers.get("content-length", "0") != "0":
        require(
            request.headers.get("content-type", "").split(";")[0] == "application/json",
            "json_required",
            "Envie JSON.",
            422,
        )


def check_csrf(request, session):
    supplied = request.headers.get("x-csrf-token", "")
    require(
        secrets.compare_digest(supplied, session.csrf), "csrf_denied", "Atualize a sessão.", 403
    )
