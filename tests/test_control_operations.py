"""Durability and uncertain outcomes must not produce duplicate VM mutations."""

import sqlite3

import pytest

from services.control.audit import OperationStore
from services.control.models import ControlError


def test_late_poll_cannot_regress_terminal_operation(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    store = OperationStore(tmp_path / "state.sqlite")
    operation, _ = store.begin("person@pve", "concurrent-poll-key", "power", 900, {})
    identifier = operation["operationId"]
    store.update(identifier, "submitted")
    late_read, complete = Event(), Event()

    def delayed_running_poll():
        assert store.get(identifier)["state"] == "submitted"
        late_read.set()
        assert complete.wait(5)
        return store.update(identifier, "running")

    with ThreadPoolExecutor(max_workers=1) as pool:
        late = pool.submit(delayed_running_poll)
        assert late_read.wait(5)
        store.update(identifier, "succeeded")
        complete.set()
        assert late.result()["state"] == "succeeded"
    assert not store.pending()


def test_intention_survives_restart_and_same_key_cannot_change_target(tmp_path):
    path = tmp_path / "state.sqlite"
    store = OperationStore(path)
    first, created = store.begin(
        "person@pve", "one-operation-key", "create", None, {"name": "vm-a"}
    )
    assert created and first["state"] == "accepted"
    store.update(first["operationId"], "reconciling")
    again = OperationStore(path)
    previous, created = again.begin(
        "person@pve", "one-operation-key", "create", None, {"name": "vm-a"}
    )
    assert not created and previous["operationId"] == first["operationId"]
    assert previous["state"] == "reconciling"
    with pytest.raises(ControlError) as error:
        again.begin("person@pve", "one-operation-key", "create", None, {"name": "vm-b"})
    assert error.value.status == 409
    connection = sqlite3.connect(path)
    assert connection.execute("SELECT count(*) FROM operations").fetchone()[0] == 1


def test_delete_intent_consumption_is_atomic_with_operation(tmp_path):
    store = OperationStore(tmp_path / "state.sqlite")
    intent = store.preview("person@pve", 900, "test-vm", "a" * 40)
    assert store.intent(intent["intentId"], "person@pve", 900)["digest"] == "a" * 40
    store.begin(
        "person@pve",
        "delete-one-operation",
        "delete",
        900,
        {"intentId": intent["intentId"]},
        intent_id=intent["intentId"],
    )
    with pytest.raises(ControlError):
        store.begin(
            "person@pve",
            "delete-two-operation",
            "delete",
            900,
            {"intentId": intent["intentId"]},
            intent_id=intent["intentId"],
        )
