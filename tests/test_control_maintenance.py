"""Bounded journal pruning never releases durable intent or unresolved evidence."""

import asyncio
import sqlite3
import time
from dataclasses import replace
from threading import Event

import httpx
import pytest
from fastapi.testclient import TestClient
from test_control_api import DIGEST, ORIGIN, PVE

import services.control.app as control_app
from services.control.audit import OperationStore
from services.control.auth import COOKIE
from services.control.models import ControlError, Settings
from services.control.proxmox import ProxmoxClient

DAY = 86400
NOW = 200 * DAY


@pytest.fixture
def store(tmp_path):
    value = OperationStore(tmp_path / "journal.sqlite", clock=lambda: NOW)
    yield value
    value.db.close()


def operation(store, state, key="maintenance-fixture-key", age_days=91):
    store.clock = lambda: NOW - age_days * DAY
    value, _ = store.begin("private-actor@pve", key, "power", 900, {"private": "value"})
    if state != "accepted":
        store.update(value["operationId"], state)
    store.clock = lambda: NOW
    return value["operationId"]


def test_prunes_only_events_strictly_older_than_retention_for_terminal_operations(store):
    old = [operation(store, state, f"old-{state}-fixture-key") for state in ("succeeded", "failed")]
    boundary = operation(store, "succeeded", "at-cutoff-fixture-key", age_days=90)
    recent = operation(store, "failed", "recent-fixture-key", age_days=89)
    assert store.maintain()["eventsDeleted"] == 4
    assert {row[0] for row in store.db.execute("SELECT DISTINCT operation_id FROM events")} == {
        boundary,
        recent,
    }
    assert all(store.get(identifier)["state"] in ("succeeded", "failed") for identifier in old)
    assert store.maintain()["eventsDeleted"] == 0


@pytest.mark.parametrize("state", ["accepted", "submitted", "running", "reconciling"])
def test_preserves_every_unresolved_operation_and_event(store, state):
    identifier = operation(store, state, age_days=4000)
    before = [tuple(row) for row in store.db.execute("SELECT * FROM events")]
    store.maintain()
    assert store.get(identifier)["state"] == state
    assert [tuple(row) for row in store.db.execute("SELECT * FROM events")] == before


def test_preserves_orphan_events_without_terminal_operation_proof(store):
    store.db.executemany(
        "INSERT INTO events(operation_id,actor,action,outcome,created) VALUES(?,?,?,?,?)",
        [(identifier, "actor", "power", "accepted", 1) for identifier in (None, "missing")],
    )
    store.maintain()
    assert store.db.execute("SELECT count(*) FROM events").fetchone()[0] == 2


def test_pruning_preserves_all_operations_and_permanent_idempotency_keys(store):
    identifier = operation(store, "succeeded")
    original = dict(store.get(identifier))
    store.maintain()
    previous, created = store.begin(
        "private-actor@pve", "maintenance-fixture-key", "power", 900, {"private": "value"}
    )
    assert not created and previous["operationId"] == identifier
    assert store.get(identifier) == original
    with pytest.raises(ControlError, match="idempotency_conflict"):
        store.begin("private-actor@pve", "maintenance-fixture-key", "power", 901, {})


def test_total_run_budget_is_500_rows_and_valid_preview_remains_usable(store):
    identifier = operation(store, "succeeded")
    store.db.executemany(
        "INSERT INTO events(operation_id,actor,action,outcome,created) VALUES(?,?,?,?,?)",
        [(identifier, "actor", "power", "running", 1)] * 497,
    )
    valid = store.preview("actor", 900, "fixture", "a" * 40)
    store.db.executemany(
        "INSERT INTO intents VALUES(?,?,?,?,?,?,0)",
        [(f"expired-{index}", "actor", 900, "fixture", "a" * 40, NOW) for index in range(3)],
    )
    first = store.maintain()
    assert first["eventsDeleted"] == 499 and first["intentsDeleted"] == 1
    assert store.db.execute("SELECT count(*) FROM intents").fetchone()[0] == 3
    assert store.intent(valid["intentId"], "actor", 900)["name"] == "fixture"
    second = store.maintain()
    assert second["eventsDeleted"] == 0 and second["intentsDeleted"] == 2
    third = store.maintain()
    assert third["eventsDeleted"] == third["intentsDeleted"] == 0
    _, created = store.begin(
        "actor", "delete-valid-preview-key", "delete", 900, {}, intent_id=valid["intentId"]
    )
    assert created


def test_event_backlog_drains_in_bounded_batches(store):
    identifier = operation(store, "failed")
    store.db.executemany(
        "INSERT INTO events(operation_id,actor,action,outcome,created) VALUES(?,?,?,?,?)",
        [(identifier, "actor", "power", "running", 1)] * 500,
    )
    assert store.maintain()["eventsDeleted"] == 500
    assert store.db.execute("SELECT count(*) FROM events").fetchone()[0] == 2
    assert store.maintain()["eventsDeleted"] == 2
    assert store.maintain()["eventsDeleted"] == 0
    assert store.get(identifier)["state"] == "failed"


def test_failure_rolls_back_pruning_and_leaves_journal_durability_required(store):
    operation(store, "succeeded")
    store.db.execute("INSERT INTO intents VALUES('expired','actor',900,'vm','digest',1,0)")
    store.db.executescript("""
        CREATE TRIGGER fail_intent_cleanup BEFORE DELETE ON intents
        BEGIN SELECT RAISE(ABORT, 'synthetic-private-database-detail'); END;
    """)
    with pytest.raises(sqlite3.IntegrityError):
        store.maintain()
    assert store.db.execute("SELECT count(*) FROM events").fetchone()[0] == 2
    assert store.db.execute("SELECT count(*) FROM intents").fetchone()[0] == 1
    summary = store.maintenance_status()
    assert summary["lastOutcome"] == "failed" and summary["failures"] == 1
    assert summary["eventsDeleted"] == summary["intentsDeleted"] == 0
    assert "synthetic-private-database-detail" not in str(summary)
    store.db.execute("PRAGMA query_only=ON")
    with pytest.raises(sqlite3.OperationalError):
        store.begin("actor", "still-needs-durable-journal", "power", 900, {})
    store.db.execute("PRAGMA query_only=OFF")
    store.db.execute("DROP TRIGGER fail_intent_cleanup")
    assert store.maintain()["eventsDeleted"] == 2
    assert store.maintenance_status()["lastOutcome"] == "succeeded"


def settings(tmp_path, **kwargs):
    return Settings(
        origin="https://control.test",
        pve_url="https://proxmox.test",
        allowed_nodes=("fixture",),
        db_path=tmp_path / "journal.sqlite",
        **kwargs,
    )


@pytest.mark.parametrize("days", [0, -1, 3651, True, 1.5, "90"])
def test_invalid_retention_rejected_before_maintenance(tmp_path, store, days):
    with pytest.raises(ValueError, match="retention"):
        settings(tmp_path, audit_retention_days=days)
    with pytest.raises(ValueError, match="retention"):
        store.maintain(retention_days=days)


@pytest.mark.parametrize("days", [1, 3650])
def test_valid_retention_limits_are_used_by_maintenance(tmp_path, store, days):
    config = settings(tmp_path, audit_retention_days=days)
    operation(store, "succeeded", age_days=days + 1)
    assert store.maintain(config.audit_retention_days)["eventsDeleted"] == 2


def test_environment_configures_retention(tmp_path, monkeypatch):
    for name, value in {
        "PLATFORM_ORIGIN": "https://control.test",
        "PVE_URL": "https://proxmox.test",
        "PVE_CA_PEM": "synthetic",
        "CONTROL_ALLOWED_NODES": "fixture",
        "CONTROL_DB_PATH": str(tmp_path / "env.sqlite"),
        "CONTROL_AUDIT_RETENTION_DAYS": "180",
    }.items():
        monkeypatch.setenv(name, value)
    assert Settings.from_env().audit_retention_days == 180
    monkeypatch.setenv("CONTROL_AUDIT_RETENTION_DAYS", "0")
    with pytest.raises(ValueError, match="retention"):
        Settings.from_env()


def test_authenticated_summary_has_only_sanitized_statistics_and_limits(tmp_path, store):
    operation(store, "succeeded")
    app = control_app.create_app(settings(tmp_path), proxmox=object(), audit=store)
    with TestClient(app, base_url="https://control.test") as client:
        assert client.get("/api/v1/audit/maintenance").status_code == 401
        key, _ = app.state.sessions.accept(
            {
                "username": "reader@pve",
                "ticket": f"PVE:reader@pve:{int(time.time()):08X}::synthetic-ticket",
                "CSRFPreventionToken": "csrf",
            }
        )
        client.cookies.set(COOKIE, key)
        store.maintain()
        response = client.get("/api/v1/audit/maintenance")
        assert response.status_code == 200
        summary = response.json()
        assert summary["retentionDays"] == 90
        assert summary["intervalSeconds"] == 3600 and summary["batchSize"] == 500
        assert set(summary) == {
            "retentionDays",
            "intervalSeconds",
            "batchSize",
            "lastAttemptAt",
            "lastSuccessAt",
            "lastOutcome",
            "eventsDeleted",
            "intentsDeleted",
            "failures",
        }
        assert "private" not in response.text and "synthetic" not in response.text


async def wait_until(predicate):
    async with asyncio.timeout(5):
        while not predicate():
            await asyncio.sleep(0.005)


def test_lifecycle_runs_periodically_on_same_store_and_stops_at_shutdown(
    tmp_path, store, monkeypatch
):
    monkeypatch.setattr(control_app, "MAINTENANCE_INTERVAL_SECONDS", 0.01)
    config = replace(settings(tmp_path), audit_retention_days=1)
    accepted = operation(store, "accepted")
    operation(store, "succeeded", "first-periodic-fixture", age_days=2)
    app = control_app.create_app(config, proxmox=object(), audit=store)

    async def scenario():
        async with app.router.lifespan_context(app):
            await wait_until(lambda: len(store.events("private-actor@pve")) == 1)
            assert store.get(accepted)["state"] == "accepted"
            operation(store, "succeeded", "second-periodic-fixture", age_days=2)
            await wait_until(lambda: len(store.events("private-actor@pve")) == 1)
        operation(store, "succeeded", "after-shutdown-fixture", age_days=2)
        await asyncio.sleep(0.05)
        assert len(store.events("private-actor@pve")) == 3

    asyncio.run(scenario())


def test_lifecycle_retries_failure_without_bypassing_durable_mutations(
    tmp_path, store, monkeypatch, caplog
):
    monkeypatch.setattr(control_app, "MAINTENANCE_INTERVAL_SECONDS", 0.01)
    config = replace(settings(tmp_path), allowed_nodes=("pve01",))
    pve = PVE()
    adapter = ProxmoxClient(config, transport=httpx.MockTransport(pve))
    store.db.execute("PRAGMA query_only=ON")
    app = control_app.create_app(config, proxmox=adapter, audit=store)
    with TestClient(app, base_url=ORIGIN) as client:
        asyncio.run(wait_until(lambda: store.maintenance_status()["lastOutcome"] == "failed"))
        login = client.post(
            "/api/v1/session",
            headers={"Origin": ORIGIN},
            json={"username": "operator@pve", "password": "synthetic-only"},
        )
        response = client.post(
            "/api/v1/vms/900/actions",
            headers={
                "Origin": ORIGIN,
                "X-CSRF-Token": login.json()["csrfToken"],
                "Idempotency-Key": "maintenance-failure-key",
            },
            json={"action": "start", "expectedDigest": DIGEST},
        )
        assert response.status_code == 503 and not pve.mutations
        store.db.execute("PRAGMA query_only=OFF")
        asyncio.run(wait_until(lambda: store.maintenance_status()["lastOutcome"] == "succeeded"))
    assert "maintenance failed" in caplog.text.lower()


def test_shutdown_waits_for_running_transaction_to_finish(tmp_path, store):
    operation(store, "succeeded")
    started, release = Event(), Event()

    def hold_cleanup():
        started.set()
        assert release.wait(5)
        return 0

    store.db.create_function("hold_cleanup", 0, hold_cleanup)
    store.db.executescript("""
        CREATE TRIGGER hold_cleanup BEFORE DELETE ON events
        BEGIN SELECT hold_cleanup(); END;
    """)
    app = control_app.create_app(settings(tmp_path), proxmox=object(), audit=store)

    async def scenario():
        lifespan = app.router.lifespan_context(app)
        await lifespan.__aenter__()
        try:
            assert await asyncio.to_thread(started.wait, 5)
            shutdown = asyncio.create_task(lifespan.__aexit__(None, None, None))
            await asyncio.sleep(0.02)
            assert not shutdown.done()
        finally:
            release.set()
        await shutdown
        assert store.db.execute("SELECT count(*) FROM events").fetchone()[0] == 0
        assert not store.db.in_transaction

    asyncio.run(scenario())
