"""SQLite journal: commit intent before any upstream side effect."""

import hashlib
import json
import re
import secrets
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from .models import require, utc


def fingerprint(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


class OperationStore:
    def __init__(self, path, clock=time.time):
        self.clock = clock
        self.lock = threading.RLock()
        path = Path(path)
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=5, isolation_level=None, check_same_thread=False)
        path.chmod(0o600)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            PRAGMA journal_mode=WAL;
            PRAGMA synchronous=FULL;
            CREATE TABLE IF NOT EXISTS operations (
                id TEXT PRIMARY KEY, actor TEXT NOT NULL, key TEXT NOT NULL,
                signature TEXT NOT NULL, action TEXT NOT NULL, target INTEGER,
                parameters TEXT NOT NULL, state TEXT NOT NULL, node TEXT, upid TEXT,
                error_code TEXT, created REAL NOT NULL, updated REAL NOT NULL,
                UNIQUE(actor,key));
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY, operation_id TEXT, actor TEXT NOT NULL,
                action TEXT NOT NULL, target INTEGER, outcome TEXT NOT NULL, created REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS intents (
                id TEXT PRIMARY KEY, actor TEXT NOT NULL, target INTEGER NOT NULL,
                name TEXT NOT NULL, digest TEXT NOT NULL, expires REAL NOT NULL,
                consumed INTEGER NOT NULL);
        """)
        # An accepted record after process death may already have reached PVE. Never replay it.
        with self.transaction():
            self.db.execute(
                "UPDATE operations SET state='reconciling',updated=? WHERE state='accepted'",
                (clock(),),
            )

    @contextmanager
    def transaction(self):
        with self.lock:
            self.db.execute("BEGIN IMMEDIATE")
            try:
                yield
                self.db.execute("COMMIT")
            except BaseException:
                self.db.execute("ROLLBACK")
                raise

    def existing(self, actor, key, action, target, parameters):
        require(
            re.fullmatch(r"[A-Za-z0-9_.:-]{16,128}", key or "") is not None,
            "idempotency_required",
            "Informe Idempotency-Key de 16 a 128 caracteres.",
            422,
        )
        with self.lock:
            row = self.db.execute(
                "SELECT * FROM operations WHERE actor=? AND key=?", (actor, key)
            ).fetchone()
        if row:
            require(
                row["signature"] == fingerprint([action, target, parameters]),
                "idempotency_conflict",
                "Esta chave já identifica outra operação.",
            )
            return self.dto(row)
        return None

    def begin(self, actor, key, action, target, parameters, intent_id=None):
        with self.transaction():
            previous = self.existing(actor, key, action, target, parameters)
            if previous:
                return previous, False
            if intent_id:
                changed = self.db.execute(
                    "UPDATE intents SET consumed=1 WHERE id=? AND actor=? AND target=? "
                    "AND consumed=0 AND expires>?",
                    (intent_id, actor, target, self.clock()),
                ).rowcount
                require(changed == 1, "intent_expired", "Prévia consumida ou expirada; gere outra.")
            identifier, now = secrets.token_urlsafe(24), self.clock()
            self.db.execute(
                "INSERT INTO operations(id,actor,key,signature,action,target,parameters,"
                "state,created,updated) VALUES(?,?,?,?,?,?,?,'accepted',?,?)",
                (
                    identifier,
                    actor,
                    key,
                    fingerprint([action, target, parameters]),
                    action,
                    target,
                    json.dumps(parameters, sort_keys=True),
                    now,
                    now,
                ),
            )
            self.db.execute(
                "INSERT INTO events(operation_id,actor,action,target,outcome,created) "
                "VALUES(?,?,?,?,?,?)",
                (identifier, actor, action, target, "accepted", now),
            )
            row = self.db.execute("SELECT * FROM operations WHERE id=?", (identifier,)).fetchone()
            return self.dto(row), True

    def update(self, identifier, state, node=None, upid=None, target=None, error=None):
        require(state in {"submitted", "running", "succeeded", "failed", "reconciling"})
        with self.transaction():
            existing = self.db.execute(
                "SELECT * FROM operations WHERE id=?", (identifier,)
            ).fetchone()
            require(existing is not None, "not_found", "Operação não encontrada.", 404)
            if existing["state"] in ("succeeded", "failed"):
                return self.dto(existing)
            self.db.execute(
                "UPDATE operations SET state=?,node=COALESCE(?,node),upid=COALESCE(?,upid),"
                "target=COALESCE(?,target),error_code=?,updated=? WHERE id=?",
                (state, node, upid, target, error, self.clock(), identifier),
            )
            row = self.db.execute("SELECT * FROM operations WHERE id=?", (identifier,)).fetchone()
            self.db.execute(
                "INSERT INTO events(operation_id,actor,action,target,outcome,created) "
                "VALUES(?,?,?,?,?,?)",
                (identifier, row["actor"], row["action"], row["target"], state, self.clock()),
            )
            return self.dto(row)

    def get(self, identifier):
        with self.lock:
            row = self.db.execute("SELECT * FROM operations WHERE id=?", (identifier,)).fetchone()
        require(row is not None, "not_found", "Operação não encontrada.", 404)
        return dict(row)

    def pending(self):
        with self.lock:
            return [
                dict(r)
                for r in self.db.execute(
                    "SELECT * FROM operations WHERE "
                    "state IN ('accepted','submitted','running','reconciling')"
                ).fetchall()
            ]

    def preview(self, actor, target, name, digest):
        identifier, expiry = secrets.token_urlsafe(24), self.clock() + 300
        with self.transaction():
            self.db.execute("DELETE FROM intents WHERE expires<?", (self.clock(),))
            self.db.execute(
                "INSERT INTO intents VALUES(?,?,?,?,?,?,0)",
                (identifier, actor, target, name, digest, expiry),
            )
        return {"intentId": identifier, "expiresAt": utc(expiry)}

    def intent(self, identifier, actor, target):
        with self.lock:
            row = self.db.execute(
                "SELECT * FROM intents WHERE id=? AND actor=? AND target=? "
                "AND consumed=0 AND expires>?",
                (identifier, actor, target, self.clock()),
            ).fetchone()
        require(row is not None, "intent_expired", "Prévia consumida ou expirada; gere outra.")
        return dict(row)

    def events(self, actor, cursor=0, limit=50):
        with self.lock:
            rows = self.db.execute(
                "SELECT * FROM events WHERE actor=? ORDER BY id DESC LIMIT ? OFFSET ?",
                (actor, limit, cursor),
            ).fetchall()
        return [
            {
                "id": r["id"],
                "createdAt": utc(r["created"]),
                "actor": r["actor"],
                "action": r["action"],
                "target": r["target"],
                "outcome": r["outcome"],
                "operationId": r["operation_id"],
            }
            for r in rows
        ]

    @staticmethod
    def dto(row):
        value = {
            "operationId": row["id"],
            "state": row["state"],
            "action": row["action"],
            "target": row["target"],
            "createdAt": utc(row["created"]),
            "updatedAt": utc(row["updated"]),
        }
        if row["upid"]:
            value["task"] = {"node": row["node"], "upid": row["upid"]}
        if row["error_code"]:
            value["error"] = {
                "code": row["error_code"],
                "message": "Operação não concluída; confira o estado no Proxmox.",
            }
        return value
