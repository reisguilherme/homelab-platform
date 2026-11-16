"""Guest actions are bounded, authorized, journaled and never replayed blindly."""

import json
from types import SimpleNamespace

import pytest

from services.control.audit import OperationStore
from services.control.models import ControlError
from services.control.runtime import Runtime, ServiceAction


class FakePVE:
    def __init__(self):
        self.calls = []
        self.denied = False
        self.uncertain = False
        self.output = {"ok": True}

    def require_permissions(self, *args):
        if self.denied:
            raise ControlError(403, "denied", "denied")

    def _request(self, method, path, session, **kwargs):
        self.calls.append((method, path, kwargs))
        if method == "POST":
            if self.uncertain:
                raise ControlError(503, "unknown", "unknown")
            return {"pid": 42}
        return {"exited": True, "exitcode": 0, "out-data": json.dumps(self.output)}


@pytest.fixture
def runtime(tmp_path):
    import threading

    pve = FakePVE()
    governance = SimpleNamespace(
        pve=pve,
        store=OperationStore(tmp_path / "audit.db"),
        mutation_lock=threading.RLock(),
        locate=lambda _s, _id: {"node": "fixture", "status": "running"},
    )
    return Runtime(governance), pve, SimpleNamespace(user="operator@pve")


def test_action_journal_and_no_replay(runtime):
    service, pve, session = runtime
    request = ServiceAction(action="restart", revision="a" * 64)
    operation = service.act(session, "idempotency-key-0001", 900, "grafana", request)
    assert len(pve.calls) == 1
    assert pve.calls[0][2]["data"]["command"][:2] == [
        "/usr/bin/python3",
        "/usr/local/libexec/homelab-runtime.py",
    ]
    service.act(session, "idempotency-key-0001", 900, "grafana", request)
    assert len(pve.calls) == 1
    assert service.operation(session, operation["operationId"])["state"] == "succeeded"


def test_lost_submission_is_not_replayed(runtime):
    service, pve, session = runtime
    pve.uncertain = True
    request = ServiceAction(action="stop", revision="a" * 64)
    result = service.act(session, "idempotency-key-0002", 900, "grafana", request)
    assert result["state"] == "reconciling"
    service.act(session, "idempotency-key-0002", 900, "grafana", request)
    assert len(pve.calls) == 1


def test_permission_revocation_blocks_read_and_mutation(runtime):
    service, pve, session = runtime
    pve.denied = True
    with pytest.raises(ControlError):
        service.list(session, 900)
    with pytest.raises(ControlError):
        service.act(
            session,
            "idempotency-key-0003",
            900,
            "grafana",
            ServiceAction(action="start", revision="a" * 64),
        )
    assert pve.calls == []


def test_cross_user_operation_denied_and_helper_failure_not_success(runtime):
    service, pve, session = runtime
    result = service.act(
        session,
        "idempotency-key-0004",
        900,
        "grafana",
        ServiceAction(action="start", revision="a" * 64),
    )
    with pytest.raises(ControlError):
        service.operation(SimpleNamespace(user="other@pve"), result["operationId"])
    pve.output = {"ok": False, "error": "storage_unavailable"}
    assert service.operation(session, result["operationId"])["state"] == "failed"


def test_service_id_never_becomes_command(runtime):
    service, pve, session = runtime
    with pytest.raises(ControlError):
        service.act(
            session,
            "idempotency-key-0005",
            900,
            "../../bin/sh",
            ServiceAction(action="start", revision="a" * 64),
        )
    assert not pve.calls


@pytest.mark.parametrize(
    "reply",
    [
        {"exited": True, "exitcode": 1, "out-data": ""},
        {"exited": True, "exitcode": 0, "out-data": "not-json"},
        {"exited": True, "exitcode": 0, "out-data": '{"ok":true}', "out-truncated": True},
    ],
)
def test_unreadable_finished_helper_is_journaled_without_resubmission(runtime, reply):
    service, pve, session = runtime
    request = ServiceAction(action="restart", revision="a" * 64)
    result = service.act(session, "idempotency-key-unknown", 900, "grafana", request)
    service.status = lambda *_args: reply
    observed = service.operation(session, result["operationId"])
    assert observed["state"] == "reconciling"
    assert observed["error"]["code"] == "result_unconfirmed"
    service.act(session, "idempotency-key-unknown", 900, "grafana", request)
    assert len(pve.calls) == 1


def test_native_readiness_timeout_is_uncertain_and_never_replayed(runtime):
    service, pve, session = runtime
    request = ServiceAction(action="restart", revision="a" * 64)
    result = service.act(session, "idempotency-key-readiness", 900, "grafana", request)
    pve.output = {"ok": False, "error": "readiness_unconfirmed"}
    observed = service.operation(session, result["operationId"])
    assert observed["state"] == "reconciling"
    assert observed["error"]["code"] == "result_unconfirmed"
    service.act(session, "idempotency-key-readiness", 900, "grafana", request)
    assert sum(method == "POST" for method, _path, _kwargs in pve.calls) == 1
