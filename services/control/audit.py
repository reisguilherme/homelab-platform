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
from time import monotonic

from .models import require, utc, validate_audit_retention

MAINTENANCE_BATCH_SIZE = 500
MAINTENANCE_LOCK_TIMEOUT_SECONDS = 5
MAINTENANCE_SQL_BUDGET_SECONDS = 2
MAINTENANCE_BUSY_TIMEOUT_MS = 100


def fingerprint(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


class OperationStore:
    def __init__(self, path, clock=time.time):
        self.clock = clock
        self.lock = threading.RLock()
        self._maintenance_lock = threading.Lock()
        self._maintenance = {
            "lastAttemptAt": None,
            "lastSuccessAt": None,
            "lastOutcome": "not_run",
            "eventsDeleted": 0,
            "intentsDeleted": 0,
            "failures": 0,
        }
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
            CREATE INDEX IF NOT EXISTS events_created ON events(created,id);
            CREATE INDEX IF NOT EXISTS intents_expires ON intents(expires,id);
        """)
        # An accepted record after process death may already have reached PVE. Never replay it.
        with self.transaction():
            self.db.execute(
                "UPDATE operations SET state='reconciling',updated=? WHERE state='accepted'",
                (clock(),),
            )

    @contextmanager
    def transaction(self, *, progress=None):
        with self.lock:
            if progress is not None:
                self.db.set_progress_handler(progress, 1000)
            try:
                self.db.execute("BEGIN IMMEDIATE")
                try:
                    yield
                    self.db.execute("COMMIT")
                except BaseException:
                    # Rollback must not be interrupted by the maintenance deadline.
                    if progress is not None:
                        self.db.set_progress_handler(None, 0)
                    # SQLITE_INTERRUPT may already have rolled back the transaction.
                    if self.db.in_transaction:
                        self.db.execute("ROLLBACK")
                    raise
            finally:
                if progress is not None:
                    self.db.set_progress_handler(None, 0)

    def maintain(self, retention_days=90, *, cancel=None):
        """Prune one bounded batch without releasing operations or idempotency keys."""
        validate_audit_retention(retention_days)
        now = self.clock()
        with self._maintenance_lock:
            self._maintenance.update(lastAttemptAt=utc(now), eventsDeleted=0, intentsDeleted=0)
        try:
            events, intents = self._prune(retention_days, now, cancel)
        except Exception:
            with self._maintenance_lock:
                self._maintenance["lastOutcome"] = "failed"
                self._maintenance["failures"] += 1
            raise
        with self._maintenance_lock:
            self._maintenance.update(
                lastOutcome="succeeded",
                lastSuccessAt=utc(self.clock()),
                eventsDeleted=events,
                intentsDeleted=intents,
            )
            return dict(self._maintenance)

    def _prune(self, retention_days, now, cancel):
        lock_deadline = monotonic() + MAINTENANCE_LOCK_TIMEOUT_SECONDS
        while True:
            if cancel is not None and cancel.is_set():
                raise InterruptedError("journal maintenance cancelled")
            remaining = lock_deadline - monotonic()
            if remaining <= 0:
                raise TimeoutError("journal maintenance lock budget exceeded")
            if self.lock.acquire(timeout=min(0.05, remaining)):
                break
        try:
            sql_deadline = monotonic() + MAINTENANCE_SQL_BUDGET_SECONDS

            def interrupted():
                return (cancel is not None and cancel.is_set()) or monotonic() >= sql_deadline

            busy_timeout = self.db.execute("PRAGMA busy_timeout").fetchone()[0]
            try:
                # A busy handler does not invoke the SQLite progress callback.
                self.db.execute(f"PRAGMA busy_timeout={MAINTENANCE_BUSY_TIMEOUT_MS}")
                with self.transaction(progress=interrupted):
                    if interrupted():
                        raise InterruptedError("journal maintenance stopped")
                    events = self.db.execute(
                        "DELETE FROM events WHERE id IN ("
                        "SELECT e.id FROM events e JOIN operations o ON o.id=e.operation_id "
                        "WHERE e.created<? AND o.state IN ('succeeded','failed') "
                        "ORDER BY e.created,e.id LIMIT ?)",
                        (now - retention_days * 86400, MAINTENANCE_BATCH_SIZE),
                    ).rowcount
                    intents = self.db.execute(
                        "DELETE FROM intents WHERE id IN ("
                        "SELECT id FROM intents WHERE expires<=? ORDER BY expires,id LIMIT ?)",
                        (now, MAINTENANCE_BATCH_SIZE - events),
                    ).rowcount
                    # Small statements may finish before the next progress callback.
                    if interrupted():
                        raise InterruptedError("journal maintenance stopped")
                return events, intents
            finally:
                self.db.execute(f"PRAGMA busy_timeout={busy_timeout}")
        finally:
            self.lock.release()

    def maintenance_status(self):
        """Process-local counters only: no actors, keys, parameters or database errors."""
        with self._maintenance_lock:
            return dict(self._maintenance)

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
