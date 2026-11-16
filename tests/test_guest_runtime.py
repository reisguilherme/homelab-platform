"""Runtime helper tested against fixtures, never production mounts or Docker."""

import importlib.util
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "guest_runtime", Path(__file__).parents[1] / "scripts/guest_runtime.py"
)
helper = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(helper)


def container(status="running"):
    return {
        "Id": "a" * 64,
        "Name": "/fixture-app",
        "Config": {
            "Image": "fixture:1",
            "Env": ["SECRET=never-output"],
            "Labels": {
                "com.docker.compose.project": "fixture",
                "com.docker.compose.service": "app",
            },
        },
        "State": {"Status": status, "StartedAt": "2026-01-01", "Pid": 0},
        "RestartCount": 0,
    }


def test_duplicate_label_is_not_actionable():
    spec = {"id": "app", "label": "App", "project": "fixture", "service": "app"}
    result = helper.describe(spec, [container(), container()])
    assert result["actions"] == [] and result["state"] == "unknown"


def test_snapshot_excludes_credentials_and_protected_service_actions():
    spec = {
        "id": "app",
        "label": "App",
        "project": "fixture",
        "service": "app",
        "protected": "Canal de controle",
    }
    result = helper.describe(spec, [container()])
    assert "Env" not in str(result) and "never-output" not in str(result)
    assert result["actions"] == []


def test_revision_changes_on_container_replacement():
    spec = {"id": "app", "label": "App", "project": "fixture", "service": "app"}
    first = container()
    second = container()
    second["Id"] = "b" * 64
    assert helper.describe(spec, [first])["revision"] != helper.describe(spec, [second])["revision"]


def test_mount_identity_and_mode_are_required(monkeypatch):
    monkeypatch.setattr(
        helper,
        "run",
        lambda *args, **kwargs: (
            '{"filesystems":[{"target":"/media","fstype":"ext4","uuid":"wrong","options":"rw"}]}'
        ),
    )
    with pytest.raises(helper.Refused, match="storage_unavailable"):
        helper.check_mounts(
            {"mounts": [{"path": "/media", "filesystem": "ext4", "uuid": "expected", "mode": "ro"}]}
        )


def test_action_rejects_stale_revision_before_docker(monkeypatch):
    spec = {"id": "app", "label": "App", "project": "fixture", "service": "app"}
    monkeypatch.setattr(helper, "inspect", lambda: [container()])
    calls = []
    monkeypatch.setattr(helper, "run", lambda args, **kwargs: calls.append(args))
    with pytest.raises(helper.Refused, match="state_changed"):
        helper.action({"services": [spec]}, "restart", "app", "f" * 64)
    assert not calls


def test_start_checks_storage_stop_does_not(monkeypatch):
    spec = {"id": "app", "label": "App", "project": "fixture", "service": "app"}
    current = container()
    monkeypatch.setattr(helper, "inspect", lambda: [current])
    checks = []
    monkeypatch.setattr(helper, "check_mounts", lambda *args: checks.append(True))

    def run(args, **kwargs):
        current["State"]["Status"] = "exited"

    monkeypatch.setattr(helper, "run", run)
    revision = helper.describe(spec, [current])["revision"]
    assert helper.action({"services": [spec]}, "stop", "app", revision)["ok"]
    assert checks == []


def start_fixture(monkeypatch, *, health=None, native=None):
    spec = {"id": "app", "label": "App", "project": "fixture", "service": "app"}
    if native is not None:
        spec["nativeCommand"] = native
    current = container("exited")
    current["State"]["Pid"] = 123
    revision = helper.describe(spec, [current])["revision"]
    monkeypatch.setattr(helper, "working_memory", lambda _pid: None)
    monkeypatch.setattr(helper, "inspect", lambda: [current])
    monkeypatch.setattr(helper, "check_mounts", lambda _config: None)
    clock = [0]
    monkeypatch.setattr(helper.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(
        helper.time, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds)
    )

    def run(_args, **_kwargs):
        current["State"]["Status"] = "running"
        if health:
            current["State"]["Health"] = {"Status": health}

    monkeypatch.setattr(helper, "run", run)
    return spec, current, revision, clock


def test_start_does_not_report_unhealthy_container_as_success(monkeypatch):
    spec, _current, revision, _clock = start_fixture(monkeypatch, health="unhealthy")
    with pytest.raises(helper.Refused, match="action_failed"):
        helper.action({"services": [spec]}, "start", "app", revision)


def test_start_waits_for_existing_healthcheck(monkeypatch):
    spec, current, revision, clock = start_fixture(monkeypatch, health="starting")

    def inspect():
        if clock[0] >= 5:
            current["State"]["Health"] = {"Status": "healthy"}
        return [current]

    monkeypatch.setattr(helper, "inspect", inspect)
    result = helper.action({"services": [spec]}, "start", "app", revision)
    assert result["readiness"] == "healthcheck"
    assert clock[0] >= 5


def test_start_health_timeout_remains_unconfirmed(monkeypatch):
    spec, _current, revision, clock = start_fixture(monkeypatch, health="starting")
    with pytest.raises(helper.Refused, match="readiness_unconfirmed"):
        helper.action({"services": [spec]}, "start", "app", revision)
    assert clock[0] >= 40


def test_guard_without_native_child_is_not_started_application(monkeypatch):
    spec, _current, revision, _clock = start_fixture(monkeypatch, native=["/app/service"])
    monkeypatch.setattr(Path, "read_text", lambda _path: "")
    with pytest.raises(helper.Refused, match="readiness_unconfirmed"):
        helper.action({"services": [spec]}, "start", "app", revision)


def test_native_child_must_match_exact_command_and_is_only_process_proof(monkeypatch):
    spec, _current, revision, _clock = start_fixture(monkeypatch, native=["/app/service", "--run"])
    monkeypatch.setattr(Path, "read_text", lambda _path: "456")
    monkeypatch.setattr(Path, "read_bytes", lambda _path: b"/app/service\x00--run\x00")
    result = helper.action({"services": [spec]}, "start", "app", revision)
    assert result["readiness"] == "process_only"


def test_different_native_child_does_not_confirm_application(monkeypatch):
    spec, _current, revision, _clock = start_fixture(monkeypatch, native=["/app/service", "--run"])
    monkeypatch.setattr(Path, "read_text", lambda _path: "456")
    monkeypatch.setattr(Path, "read_bytes", lambda _path: b"/app/service\x00--guard-only\x00")
    with pytest.raises(helper.Refused, match="readiness_unconfirmed"):
        helper.action({"services": [spec]}, "start", "app", revision)


def test_unchecked_container_reports_only_running_process(monkeypatch):
    spec, _current, revision, _clock = start_fixture(monkeypatch)
    result = helper.action({"services": [spec]}, "start", "app", revision)
    assert result == {"ok": True, "service": "app", "state": "running", "readiness": "process_only"}
