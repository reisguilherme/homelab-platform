"""Containment fixtures; these do not prove USB power or hard-NFS recovery."""

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    assert path.exists(), f"missing implementation: {path.name}"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def supervisor():
    return load("storage_supervisor", ROOT / "scripts/storage_supervisor.py")


@pytest.fixture
def guest():
    return load("storage_guest", ROOT / "infrastructure/storage/guest-storage-probe.py")


class Backend:
    def __init__(self):
        self.pending = {}
        self.started = []
        self.next_pid = 100
        self.profile_ok = True
        self.launch_error = False

    def verify_profile(self):
        if not self.profile_ok:
            raise RuntimeError("profile-unavailable")

    def launch(self, role, args):
        self.started.append((role, args))
        if self.launch_error:
            raise RuntimeError("launch-ambiguous")
        self.next_pid += 1
        self.pending[self.next_pid] = None
        return self.next_pid

    def poll(self, role, pid):
        return self.pending[pid]


@pytest.fixture
def setup(supervisor):
    backend = Backend()
    clock = [100.0]
    saved = []
    state = supervisor.new_state("host-boot", "profile-digest")
    controller = supervisor.Controller(
        state,
        backend,
        lambda: clock[0],
        lambda: 1000 + clock[0],
        lambda: saved.append(json.loads(json.dumps(state))),
    )
    return controller, backend, clock, saved


def complete_probe(controller, backend, *, healthy=True, generation="a" * 64, nonce=None):
    pending = controller.state["probe"]
    backend.pending[pending["pid"]] = {
        "version": 1,
        "nonce": nonce or pending["nonce"],
        "healthy": healthy,
        "reason": "ok" if healthy else "identity",
        "generation": generation,
        "boot_id": "12345678-1234-1234-1234-123456789abc",
    }


def complete_lease(controller, backend):
    pending = controller.state["lease"]
    backend.pending[pending["pid"]] = {
        "version": 1,
        "written": True,
        "sequence": pending["sequence"],
        "generation": controller.state["generation"],
        "state": pending["state"],
    }


def test_initial_state_never_grants_ready_without_arm(setup):
    controller, backend, _, _ = setup
    controller.tick()
    assert controller.state["mode"] == "hold"
    assert all("lease-ready" not in args for _, args in backend.started)


def test_explicit_arm_requires_fresh_success_before_ready(setup):
    controller, backend, _, saved = setup
    controller.request("arm")
    controller.tick()
    assert controller.state["probe"]["pid"]
    assert not controller.state["lease"]
    complete_probe(controller, backend)
    controller.tick()
    assert controller.state["lease"]["state"] == "ready"
    assert saved and saved[0]["mode"] == "armed"


def test_probe_deadline_holds_without_spawning_second_probe(setup):
    controller, backend, clock, _ = setup
    controller.request("arm")
    controller.tick()
    first = controller.state["probe"]["pid"]
    clock[0] += 16
    controller.tick()
    controller.tick()
    assert controller.state["mode"] == "hold"
    assert controller.state["probe"]["pid"] == first
    assert len([1 for role, _ in backend.started if role == "core"]) == 1


def test_late_healthy_response_does_not_resume_incident(setup):
    controller, backend, clock, _ = setup
    controller.request("arm")
    controller.tick()
    clock[0] += 16
    controller.tick()
    complete_probe(controller, backend)
    controller.tick()
    assert controller.state["mode"] == "hold"
    assert all("lease-ready" not in args for _, args in backend.started)


@pytest.mark.parametrize("reason", ["unhealthy", "nonce", "generation"])
def test_untrusted_or_changed_probe_cannot_grant_lease(setup, reason):
    controller, backend, _, _ = setup
    controller.request("arm")
    controller.tick()
    if reason == "generation":
        controller.state["physical_generation"] = "b" * 64
    complete_probe(
        controller,
        backend,
        healthy=reason != "unhealthy",
        nonce="bad" if reason == "nonce" else None,
    )
    controller.tick()
    assert controller.state["mode"] == "hold"
    assert all("lease-ready" not in args for _, args in backend.started)


def test_launch_timeout_retains_unknown_execution_and_blocks_resume(setup):
    controller, backend, _, _ = setup
    controller.request("arm")
    backend.launch_error = True
    controller.tick()
    assert controller.state["mode"] == "hold"
    assert controller.state["probe"]["pid"] is None
    with pytest.raises(ValueError, match="pending"):
        controller.request("resume")
    controller.tick()
    assert len([1 for role, _ in backend.started if role == "core"]) == 1


def test_profile_unavailable_prevents_all_new_guest_commands(setup):
    controller, backend, _, _ = setup
    controller.request("arm")
    backend.profile_ok = False
    controller.tick()
    assert controller.state["mode"] == "hold"
    assert backend.started == []


def test_manual_hold_precedes_pending_success(setup):
    controller, backend, _, _ = setup
    controller.request("arm")
    controller.tick()
    controller.request("hold")
    complete_probe(controller, backend)
    controller.tick()
    assert controller.state["mode"] == "hold"
    assert all("lease-ready" not in args for _, args in backend.started)


def test_lease_failure_does_not_renew_previous_success(setup):
    controller, backend, _, _ = setup
    controller.request("arm")
    controller.tick()
    complete_probe(controller, backend)
    controller.tick()
    backend.pending[controller.state["lease"]["pid"]] = {"written": False}
    controller.tick()
    assert controller.state["mode"] == "hold"


def test_lease_ack_received_after_deadline_stays_held(setup):
    controller, backend, clock, _ = setup
    controller.request("arm")
    controller.tick()
    complete_probe(controller, backend)
    controller.tick()
    complete_lease(controller, backend)
    clock[0] += 16
    controller.tick()
    assert controller.state["mode"] == "hold"
    assert controller.state["lease"]["state"] == "hold"


def test_repeated_arm_cannot_bypass_incident(setup):
    controller, _, _, _ = setup
    controller.request("arm")
    controller.request("hold")
    with pytest.raises(ValueError, match="resume"):
        controller.request("arm")


def test_ready_ack_then_next_probe_waits_minimum_interval(setup):
    controller, backend, clock, _ = setup
    controller.request("arm")
    controller.tick()
    complete_probe(controller, backend)
    controller.tick()
    complete_lease(controller, backend)
    controller.tick()
    count = len(backend.started)
    clock[0] += 5
    controller.tick()
    assert len(backend.started) == count
    clock[0] += 6
    controller.tick()
    assert controller.state["probe"]


def test_lease_format_and_expiry_are_bounded(guest):
    value = guest.lease_text("ready", "12345678-1234-1234-1234-123456789abc", "a" * 32, 120)
    assert value == (
        "version=1\nstate=ready\nboot_id=12345678-1234-1234-1234-123456789abc\n"
        f"generation={'a' * 32}\nexpires_uptime_seconds=120\n"
    )
    assert guest.lease_expiry("ready", 1020, 1000.0, 100.0) == 120
    with pytest.raises(ValueError):
        guest.lease_expiry("ready", 999, 1000.0, 100.0)
    with pytest.raises(ValueError):
        guest.lease_expiry("ready", 1046, 1000.0, 100.0)
    assert guest.lease_expiry("hold", 0, 1000.0, 100.0) == 0


def test_mount_validation_rejects_absent_rw_or_foreign_device(guest):
    line = "42 1 8:17 / /srv/external3 rw - ext4 /dev/sdb1 rw,errors=remount-ro\n"
    assert guest.mount_identity(line, "8:17") == "42"
    for bad in [
        "",
        line.replace("8:17", "8:33"),
        line.replace(" rw ", " ro "),
        line + line,
        line + "43 42 0:4 / /srv/external3/nested rw - tmpfs x rw\n",
    ]:
        with pytest.raises(ValueError):
            guest.mount_identity(bad, "8:17")


def test_lease_atomic_write_and_replay_refusal(guest, tmp_path, monkeypatch):
    # Publication/replay fixture lives below /tmp; production's root-only ancestry
    # is verified separately and cannot accept a temporary world-writable parent.
    monkeypatch.setattr(guest, "trusted", lambda path, **_: path.lstat())
    destination = tmp_path / "admission"
    destination.mkdir()
    journal = tmp_path / "lease-state.json"
    guest.publish_lease(
        destination,
        journal,
        "ready",
        "a" * 32,
        1,
        1020,
        "12345678-1234-1234-1234-123456789abc",
        1000,
        100,
    )
    before = (destination / "lease").read_bytes()
    with pytest.raises(ValueError, match="sequence"):
        guest.publish_lease(
            destination,
            journal,
            "ready",
            "a" * 32,
            1,
            1021,
            "12345678-1234-1234-1234-123456789abc",
            1000,
            100,
        )
    assert (destination / "lease").read_bytes() == before
    guest.publish_lease(
        destination,
        journal,
        "hold",
        "b" * 32,
        2,
        0,
        "12345678-1234-1234-1234-123456789abc",
        1000,
        100,
    )
    assert "state=hold" in (destination / "lease").read_text()


def test_guest_trust_refuses_world_writable_ancestor(guest, tmp_path):
    file = tmp_path / "private.json"
    file.write_text("{}")
    file.chmod(0o600)
    with pytest.raises(ValueError, match="unsafe-parent"):
        guest.trusted(file, private=True)


@pytest.fixture
def device_profile():
    return {
        "filesystem_uuid": "12345678-1234-1234-1234-123456789abc",
        "bridge_serial": "fixture-bridge",
        "partition_size_bytes": 9000,
        "disk_size_bytes": 10000,
    }


@pytest.fixture
def blocks(device_profile):
    return {
        "blockdevices": [
            {
                "path": "/dev/sdb",
                "type": "disk",
                "serial": "fixture-bridge",
                "size": 10000,
                "ro": False,
                "children": [
                    {
                        "path": "/dev/sdb1",
                        "type": "part",
                        "fstype": "ext4",
                        "uuid": device_profile["filesystem_uuid"],
                        "size": 9000,
                        "ro": False,
                        "maj:min": "8:17",
                    }
                ],
            }
        ]
    }


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "uuid", "serial", "size", "ro"])
def test_core_device_identity_is_fail_closed(guest, device_profile, blocks, mutation):
    disk = blocks["blockdevices"][0]
    part = disk["children"][0]
    if mutation == "missing":
        blocks["blockdevices"] = []
    elif mutation == "duplicate":
        disk["children"].append(dict(part))
    elif mutation == "uuid":
        part["uuid"] = "foreign"
    elif mutation == "serial":
        disk["serial"] = "foreign"
    elif mutation == "size":
        part["size"] = 8999
    else:
        part["ro"] = True
    with pytest.raises(ValueError):
        guest.select_device(blocks, device_profile)


def test_core_selects_exact_registered_partition(guest, device_profile, blocks):
    part, disk = guest.select_device(blocks, device_profile)
    assert part["path"] == "/dev/sdb1" and disk["path"] == "/dev/sdb"


def test_direct_read_has_no_cached_fallback(guest, tmp_path, monkeypatch):
    file = tmp_path / "health.bin"
    file.write_bytes(b"a" * 65536)
    monkeypatch.setattr(guest, "trusted", lambda path: path.stat())
    calls = []

    def opened(path, flags):
        calls.append(flags)
        raise OSError("unsupported-direct-io")

    monkeypatch.setattr(guest.os, "open", opened)
    with pytest.raises(OSError, match="unsupported-direct-io"):
        guest.direct_hash(file, file.stat().st_dev)
    expected_flags = (
        guest.os.O_RDONLY | guest.os.O_NOFOLLOW | guest.os.O_DIRECT | guest.os.O_NOATIME
    )
    assert calls == [expected_flags]


def test_direct_read_hashes_exact_64k(guest, tmp_path, monkeypatch):
    import hashlib

    file = tmp_path / "health.bin"
    file.write_bytes(bytes(range(256)) * 256)
    monkeypatch.setattr(guest, "trusted", lambda path: path.stat())
    expected = hashlib.sha256(file.read_bytes()).hexdigest()
    assert guest.direct_hash(file, file.stat().st_dev) == expected


@pytest.fixture
def pve_profile():
    return {
        "version": 1,
        "core_vmid": 120,
        "playback_vmid": 121,
        "core_name": "core",
        "playback_name": "playback",
        "usb_port": "2-1",
    }


@pytest.mark.parametrize("change", ["name", "port", "lock"])
def test_vm_configuration_mismatch_prevents_commands(supervisor, pve_profile, change):
    backend = supervisor.QgaBackend(pve_profile)

    def command(args):
        if args[1] == "120":
            return "name: core\nusb0: host=2-1,usb3=1\n".replace(
                {"name": "core", "port": "2-1", "lock": "name:"}[change],
                {"name": "foreign", "port": "2-2", "lock": "lock: backup\nname:"}[change],
            )
        return "name: playback\n"

    backend.run = command
    with pytest.raises(ValueError):
        backend.verify_profile()


def test_qga_exec_is_asynchronous_with_fixed_guest_helper(supervisor, pve_profile):
    backend = supervisor.QgaBackend(pve_profile)
    called = []
    backend.run = lambda args: called.append(args) or '{"pid": 321}'
    assert backend.launch("core", ["probe", "--nonce", "a" * 32]) == 321
    assert called == [
        [
            "guest",
            "exec",
            "120",
            "--synchronous",
            "0",
            "--",
            "/usr/bin/python3",
            "-B",
            supervisor.GUEST_HELPER,
            "probe",
            "--nonce",
            "a" * 32,
        ]
    ]


def test_qga_waiting_or_failed_output_cannot_be_healthy(supervisor, pve_profile):
    backend = supervisor.QgaBackend(pve_profile)
    backend.run = lambda _: '{"exited": false}'
    assert backend.poll("core", 123) is None
    backend.run = lambda _: '{"exited": true, "exitcode": 1}'
    assert backend.poll("core", 123) == {"failed": True}


@pytest.mark.parametrize("exited", [False, 0])
def test_qga_running_bool_and_integer_keep_guest_pid_pending(supervisor, pve_profile, exited):
    backend = supervisor.QgaBackend(pve_profile)
    backend.run = lambda _: json.dumps({"exited": exited})
    assert backend.poll("core", 123) is None


@pytest.mark.parametrize("exited", [True, 1])
def test_qga_exited_bool_and_integer_decode_result(supervisor, pve_profile, exited):
    backend = supervisor.QgaBackend(pve_profile)
    backend.run = lambda _: json.dumps(
        {"exited": exited, "exitcode": 0, "out-data": '{"healthy":true}'}
    )
    assert backend.poll("core", 123) == {"healthy": True}


def test_core_inventory_requests_explicit_lsblk_tree(guest, monkeypatch):
    called = []
    monkeypatch.setattr(guest, "run_json", lambda args: called.append(args) or {"blockdevices": []})
    assert guest.block_inventory() == {"blockdevices": []}
    assert "--tree" in called[0]


def test_smart_identity_uses_only_explicit_profile_transport(guest, monkeypatch):
    called = []
    monkeypatch.setattr(
        guest, "run_json", lambda args: called.append(args) or {"serial_number": "X"}
    )
    assert guest.smart_identity("/dev/sdb", "sat,12") == {"serial_number": "X"}
    assert called == [["/usr/sbin/smartctl", "--device", "sat,12", "--info", "--json", "/dev/sdb"]]
    with pytest.raises(ValueError):
        guest.smart_identity("/dev/sdb", "auto")
    assert len(called) == 1


@pytest.mark.parametrize("exited", [None, "0", "1", 1.0, 2])
def test_ambiguous_qga_status_never_proves_process_exited(supervisor, pve_profile, exited):
    backend = supervisor.QgaBackend(pve_profile)
    backend.run = lambda _: json.dumps({"exited": exited})
    with pytest.raises(ValueError, match="ambiguous"):
        backend.poll("core", 123)


def test_state_refuses_other_host_boot_and_profile(supervisor):
    state = supervisor.new_state("one", "profile")
    assert supervisor.validate_state(state, "one", "profile") is state
    with pytest.raises(ValueError):
        supervisor.validate_state(state, "two", "profile")
    with pytest.raises(ValueError):
        supervisor.validate_state(state, "one", "changed")


@pytest.mark.parametrize("mutation", ["extra", "negative-time", "future-command", "bad-sequence"])
def test_state_refuses_malformed_pending_record(supervisor, mutation):
    state = supervisor.new_state("one", "profile")
    record = {"pid": 123, "nonce": "a" * 32, "started": 10.0, "generation": state["generation"]}
    state["probe"] = record
    if mutation == "extra":
        record["command"] = "unsafe"
    elif mutation == "negative-time":
        record["started"] = -1
    elif mutation == "future-command":
        record["nonce"] = "not-a-nonce"
    else:
        state["sequence"] = True
    with pytest.raises(ValueError):
        supervisor.validate_state(state, "one", "profile")


def test_explicit_resume_cannot_discard_already_armed_observation(setup):
    controller, _, _, _ = setup
    controller.request("arm")
    with pytest.raises(ValueError, match="already-armed"):
        controller.request("resume")


def test_recreated_controller_keeps_pending_pid_and_never_duplicates_probe(supervisor, setup):
    controller, backend, clock, _ = setup
    controller.request("arm")
    controller.tick()
    saved = json.loads(json.dumps(controller.state))
    pid = saved["probe"]["pid"]
    recreated = supervisor.Controller(saved, backend, lambda: clock[0], lambda: 1000, lambda: None)
    recreated.tick()
    assert saved["probe"]["pid"] == pid
    assert len([1 for role, _ in backend.started if role == "core"]) == 1


def test_ready_ack_after_manual_hold_does_not_rearm_or_restore_generation(setup):
    controller, backend, _, _ = setup
    controller.request("arm")
    controller.tick()
    complete_probe(controller, backend)
    controller.tick()
    old = dict(controller.state["lease"])
    controller.request("hold")
    generation = controller.state["generation"]
    backend.pending[old["pid"]] = {
        "version": 1,
        "written": True,
        "sequence": old["sequence"],
        "generation": old["generation"],
        "state": "ready",
    }
    controller.tick()
    assert controller.state["mode"] == "hold"
    assert controller.state["generation"] == generation != old["generation"]
    assert controller.state["lease"]["state"] == "hold"


def test_watch_cadence_and_cron_gap_keep_healthy_lease_within_deadlines(setup):
    controller, backend, clock, _ = setup
    controller.request("arm")
    last_expiry = None
    seen = 0
    for second in range(180):
        clock[0] = 100 + second
        if second % 60 < 50 and second % 2 == 0:
            if controller.state["probe"]:
                complete_probe(controller, backend)
            if controller.state["lease"]:
                complete_lease(controller, backend)
            controller.tick()
            for _, args in backend.started[seen:]:
                if args[0] == "lease-ready":
                    last_expiry = int(args[args.index("--not-after") + 1])
            seen = len(backend.started)
        assert controller.state["mode"] == "armed"
        if last_expiry is not None:
            assert 1000 + clock[0] < last_expiry


def simulate_qm_cadence(supervisor, window_seconds):
    """Advance host time during every CLI call, including before PID polling."""
    clock = [0.0]
    records = {}
    events = []

    class TimedBackend(Backend):
        def verify_profile(self):
            clock[0] += 3.0  # Two independent qm config processes, 1.5 s each.

        def launch(self, role, args):
            pid = super().launch(role, args)
            started = clock[0]
            clock[0] += 1.5
            if role == "core":
                value = {
                    "version": 1,
                    "nonce": args[-1],
                    "healthy": True,
                    "reason": "ok",
                    "generation": "a" * 64,
                    "boot_id": "12345678-1234-1234-1234-123456789abc",
                }
            else:
                value = {
                    "version": 1,
                    "written": True,
                    "sequence": int(args[args.index("--sequence") + 1]),
                    "generation": args[args.index("--generation") + 1],
                    "state": args[0].removeprefix("lease-"),
                }
            records[pid] = (clock[0] + 0.5, value)
            events.append(("launch", role, started))
            return pid

        def poll(self, role, pid):
            clock[0] += 1.5
            ready_at, result = records[pid]
            events.append(("poll", role, clock[0]))
            return result if clock[0] >= ready_at else None

    state = supervisor.new_state("boot", "profile")
    controller = supervisor.Controller(
        state,
        TimedBackend(),
        lambda: clock[0],
        lambda: 1000 + clock[0],
        lambda: None,
    )
    controller.request("arm")
    for minute in range(6):
        clock[0] = max(clock[0], minute * 60)
        until = clock[0] + window_seconds
        while True:
            controller.tick()
            if state["mode"] == "hold" or clock[0] + 2 >= until:
                break
            clock[0] += 2
        if state["mode"] == "hold":
            break
    return state, events


def test_old_fifty_second_window_can_timeout_completed_probe(supervisor):
    state, events = simulate_qm_cadence(supervisor, 50)
    assert state["mode"] == "hold" and state["reason"] == "probe-timeout"
    assert ("launch", "core", 106.5) in events
    assert ("poll", "core", 124.5) in events


def test_default_watch_window_survives_realistic_cli_costs(supervisor, monkeypatch):
    class CapturedDefault(Exception):
        pass

    def capture_default(parser, *args, **kwargs):
        raise CapturedDefault(parser.get_default("seconds"))

    monkeypatch.setattr(supervisor.argparse.ArgumentParser, "parse_args", capture_default)
    with pytest.raises(CapturedDefault) as captured:
        supervisor.main()
    state, _ = simulate_qm_cadence(supervisor, captured.value.args[0])
    assert state["mode"] == "armed" and state["reason"] == "healthy-lease-published"
    assert supervisor.PROBE_DEADLINE == supervisor.LEASE_DEADLINE == 15
    assert supervisor.LEASE_TTL == 45


def test_cli_accepts_explicit_fifty_eight_second_window(supervisor, monkeypatch, capsys):
    import sys

    monkeypatch.setattr(sys, "argv", ["storage_supervisor.py", "status", "--seconds", "58"])
    monkeypatch.setattr(supervisor, "one", lambda _: {"mode": "hold"})
    assert supervisor.main() == 0
    assert json.loads(capsys.readouterr().out) == {"mode": "hold"}


@pytest.mark.parametrize("action", ["arm", "resume", "hold"])
def test_manual_busy_is_retryable_failure_not_applied_success(
    supervisor, monkeypatch, capsys, action
):
    import sys

    monkeypatch.setattr(sys, "argv", ["storage_supervisor.py", action])
    monkeypatch.setattr(supervisor, "one", lambda _: {"mode": "busy"})
    assert supervisor.main() == 75
    assert json.loads(capsys.readouterr().out) == {"mode": "busy"}


def test_status_busy_remains_normal_observation(supervisor, monkeypatch, capsys):
    import sys

    monkeypatch.setattr(sys, "argv", ["storage_supervisor.py", "status"])
    monkeypatch.setattr(supervisor, "one", lambda _: {"mode": "busy"})
    assert supervisor.main() == 0
    assert json.loads(capsys.readouterr().out) == {"mode": "busy"}


@pytest.mark.parametrize("payload", ["", "{", "null", "[]", "1", None, 7, "x" * 16385])
def test_exited_malformed_output_is_terminal_failure(supervisor, pve_profile, payload):
    backend = supervisor.QgaBackend(pve_profile)
    backend.run = lambda _: json.dumps({"exited": 1, "exitcode": 0, "out-data": payload})
    assert backend.poll("playback", 123) == {"failed": True}


def test_stale_lease_ack_clears_and_persists_completion_before_next_tick(setup):
    controller, backend, _, saved = setup
    controller.request("arm")
    controller.tick()
    complete_probe(controller, backend)
    controller.tick()
    pending = dict(controller.state["lease"])
    complete_lease(controller, backend)
    controller.request("hold")
    saved.clear()
    controller.poll_lease()
    assert controller.state["lease"] is None
    assert len(saved) == 1
    assert saved[0]["lease"] is None and saved[0]["mode"] == "hold"
    assert saved[0]["reason"] == "lease-completed-stale"
    assert saved[0]["generation"] != pending["generation"]


def test_invalid_terminal_lease_never_persists_cleared_lease_while_armed(setup):
    controller, backend, _, saved = setup
    controller.request("arm")
    controller.tick()
    complete_probe(controller, backend)
    controller.tick()
    backend.pending[controller.state["lease"]["pid"]] = {"failed": True}
    saved.clear()
    controller.poll_lease()
    assert len(saved) == 1
    assert saved[0]["lease"] is None
    assert saved[0]["mode"] == "hold" and saved[0]["reason"] == "lease-rejected"


@pytest.fixture
def reconciliation_files(guest, tmp_path, monkeypatch):
    storage = tmp_path / "storage"
    storage.mkdir()
    admission = storage / "admission"
    admission.mkdir()
    (storage / "lease.lock").touch(mode=0o600)
    (storage / "lease-state.json").write_text('{"version":1,"sequence":7}')
    (admission / "lease").write_text(
        "version=1\nstate=ready\nboot_id=12345678-1234-1234-1234-123456789abc\n"
        f"generation={'a' * 32}\nexpires_uptime_seconds=120\n"
    )
    proc = tmp_path / "proc"
    (proc / "sys/kernel/random").mkdir(parents=True)
    (proc / "sys/kernel/random/boot_id").write_text("12345678-1234-1234-1234-123456789abc\n")
    (proc / "uptime").write_text("121.25 1000.0\n")
    monkeypatch.setattr(guest, "STATE", storage)
    monkeypatch.setattr(guest, "PROC", proc, raising=False)
    # Temporary ancestry cannot pass root-only trust; no-follow opens and bounds remain real.
    monkeypatch.setattr(guest, "trusted", lambda path, **_: path.lstat())
    return storage, proc


def test_guest_reconciliation_proves_expired_publication_without_writes(
    guest, reconciliation_files
):
    import hashlib

    storage, _ = reconciliation_files
    files = [storage / "lease-state.json", storage / "admission/lease", storage / "lease.lock"]
    before = {path: path.read_bytes() for path in files}
    proof = guest.reconcile_lease({"version": 1, "role": "playback"}, 123, 7, "a" * 32, "ready")
    assert proof == {
        "version": 1,
        "reconciled": True,
        "pid": 123,
        "sequence": 7,
        "generation": "a" * 32,
        "state": "ready",
        "boot_id": "12345678-1234-1234-1234-123456789abc",
        "expires_uptime_seconds": 120,
        "observed_uptime_seconds": 121,
        "lease_sha256": hashlib.sha256(before[storage / "admission/lease"]).hexdigest(),
        "journal_sha256": hashlib.sha256(before[storage / "lease-state.json"]).hexdigest(),
    }
    assert {path: path.read_bytes() for path in files} == before


@pytest.mark.parametrize(
    "mutation",
    [
        "live-pid",
        "journal-sequence",
        "journal-duplicate",
        "journal-scalar",
        "lease-active",
        "wrong-boot",
        "wrong-generation",
        "wrong-state",
        "lease-duplicate",
        "lease-malformed",
        "lease-oversize",
        "journal-oversize",
        "lease-symlink",
        "journal-symlink",
        "lock-symlink",
        "boot-malformed",
        "uptime-malformed",
        "missing-lease",
        "missing-journal",
        "missing-lock",
    ],
)
def test_guest_reconciliation_refuses_incomplete_or_foreign_proof(
    guest, reconciliation_files, mutation
):
    storage, proc = reconciliation_files
    lease = storage / "admission/lease"
    journal = storage / "lease-state.json"
    if mutation == "live-pid":
        (proc / "123").mkdir()
    elif mutation == "journal-sequence":
        journal.write_text('{"version":1,"sequence":8}')
    elif mutation == "journal-duplicate":
        journal.write_text('{"version":1,"sequence":7,"sequence":7}')
    elif mutation == "journal-scalar":
        journal.write_text("null")
    elif mutation == "lease-active":
        lease.write_text(lease.read_text().replace("=120", "=122"))
    elif mutation == "wrong-boot":
        lease.write_text(lease.read_text().replace("12345678-", "87654321-"))
    elif mutation == "wrong-generation":
        lease.write_text(lease.read_text().replace("a" * 32, "b" * 32))
    elif mutation == "wrong-state":
        lease.write_text(lease.read_text().replace("state=ready", "state=hold"))
    elif mutation == "lease-duplicate":
        lease.write_text(lease.read_text() + "state=ready\n")
    elif mutation == "lease-malformed":
        lease.write_text(lease.read_text().replace("=120", "=nan"))
    elif mutation.endswith("oversize"):
        (lease if mutation.startswith("lease") else journal).write_text("x" * 4097)
    elif mutation.endswith("symlink"):
        target = {
            "lease-symlink": lease,
            "journal-symlink": journal,
            "lock-symlink": storage / "lease.lock",
        }[mutation]
        other = target.with_name(target.name + ".other")
        target.rename(other)
        target.symlink_to(other)
    elif mutation == "boot-malformed":
        (proc / "sys/kernel/random/boot_id").write_text("unknown")
    elif mutation == "uptime-malformed":
        (proc / "uptime").write_text("nan 0")
    else:
        {
            "missing-lease": lease,
            "missing-journal": journal,
            "missing-lock": storage / "lease.lock",
        }[mutation].unlink()
    with pytest.raises((OSError, ValueError)):
        guest.reconcile_lease({"version": 1, "role": "playback"}, 123, 7, "a" * 32, "ready")


def test_guest_reconciliation_refuses_busy_lease_lock(guest, reconciliation_files):
    storage, _ = reconciliation_files
    with (storage / "lease.lock").open() as lock:
        guest.fcntl.flock(lock, guest.fcntl.LOCK_EX | guest.fcntl.LOCK_NB)
        with pytest.raises(BlockingIOError):
            guest.reconcile_lease({"version": 1, "role": "playback"}, 123, 7, "a" * 32, "ready")


def test_guest_reconciliation_accepts_hold_zero_expiry(guest, reconciliation_files):
    storage, _ = reconciliation_files
    lease = storage / "admission/lease"
    lease.write_text(lease.read_text().replace("state=ready", "state=hold").replace("=120", "=0"))
    assert (
        guest.reconcile_lease({"version": 1, "role": "playback"}, 123, 7, "a" * 32, "hold")[
            "expires_uptime_seconds"
        ]
        == 0
    )


@pytest.fixture
def reconcile_setup(setup):
    controller, backend, clock, saved = setup
    controller.state.update(sequence=7, generation="b" * 32, reason="operation-failed")
    controller.state["lease"] = {
        "pid": 123,
        "sequence": 7,
        "generation": "a" * 32,
        "state": "ready",
        "started": 80.0,
    }
    proof = {
        "version": 1,
        "reconciled": True,
        "pid": 123,
        "sequence": 7,
        "generation": "a" * 32,
        "state": "ready",
        "boot_id": "12345678-1234-1234-1234-123456789abc",
        "expires_uptime_seconds": 120,
        "observed_uptime_seconds": 121,
        "lease_sha256": "c" * 64,
        "journal_sha256": "d" * 64,
    }
    backend.reconcile_lease = lambda record: dict(proof)
    receipts = []
    return controller, backend, clock, saved, proof, receipts


def test_reconcile_records_receipt_before_clear_and_next_tick_only_publishes_hold(reconcile_setup):
    controller, backend, _, saved, proof, receipts = reconcile_setup
    pending = dict(controller.state["lease"])

    def audit(receipt):
        assert controller.state["lease"] == pending
        receipts.append(receipt)

    controller.reconcile_lease(audit)
    assert len(receipts) == 1 and receipts[0]["pending_lease"] == pending
    assert receipts[0]["proof"] == proof
    assert saved[-1]["lease"] is None
    assert saved[-1]["mode"] == "hold" and saved[-1]["reason"] == "lease-reconciled"
    assert backend.started == []
    controller.tick()
    assert controller.state["mode"] == "hold"
    assert controller.state["lease"]["sequence"] == 8
    assert backend.started == [
        ("playback", ["lease-hold", "--generation", "b" * 32, "--sequence", "8"])
    ]


@pytest.mark.parametrize("mutation", ["armed", "probe", "missing-pid", "zero-pid", "no-lease"])
def test_reconcile_preconditions_preserve_pending_and_never_launch(reconcile_setup, mutation):
    controller, backend, _, _, _, receipts = reconcile_setup
    if mutation == "armed":
        controller.state["mode"] = "armed"
    elif mutation == "probe":
        controller.state["probe"] = {
            "pid": 99,
            "nonce": "a" * 32,
            "started": 1,
            "generation": "a" * 32,
        }
        backend.pending[99] = None
    elif mutation == "no-lease":
        controller.state["lease"] = None
    else:
        controller.state["lease"]["pid"] = None if mutation == "missing-pid" else 0
    pending = json.loads(json.dumps(controller.state))
    with pytest.raises(ValueError):
        controller.reconcile_lease(receipts.append)
    assert controller.state == pending
    assert receipts == [] and backend.started == []


@pytest.mark.parametrize(
    "field,value",
    [
        ("pid", 124),
        ("pid", True),
        ("sequence", 8),
        ("generation", "b" * 32),
        ("state", "hold"),
        ("boot_id", "unknown"),
        ("reconciled", 1),
        ("version", True),
        ("expires_uptime_seconds", 122),
        ("observed_uptime_seconds", True),
        ("lease_sha256", "x" * 64),
        ("journal_sha256", None),
        ("extra", "unexpected"),
    ],
)
def test_reconcile_rejects_malformed_or_mismatched_response(reconcile_setup, field, value):
    controller, backend, _, saved, proof, receipts = reconcile_setup
    proof[field] = value
    pending = dict(controller.state["lease"])
    with pytest.raises(ValueError):
        controller.reconcile_lease(receipts.append)
    assert controller.state["lease"] == pending and controller.state["mode"] == "hold"
    assert saved[-1]["reason"] == "lease-reconciliation-refused"
    assert receipts == [] and backend.started == []


@pytest.mark.parametrize("failure", ["transport", "pending", "receipt"])
def test_reconcile_failure_never_discards_pending(reconcile_setup, failure):
    controller, backend, _, _, _, receipts = reconcile_setup
    pending = dict(controller.state["lease"])

    def unavailable(*_):
        raise OSError("private diagnostic not for persisted reason")

    audit = unavailable if failure == "receipt" else receipts.append
    if failure == "transport":
        backend.reconcile_lease = unavailable
    elif failure == "pending":
        backend.reconcile_lease = lambda _: None
    with pytest.raises((OSError, ValueError)):
        controller.reconcile_lease(audit)
    assert controller.state["lease"] == pending and controller.state["mode"] == "hold"
    assert receipts == [] and backend.started == []


def test_qga_reconciliation_uses_fixed_bounded_read_only_command(supervisor, pve_profile):
    backend = supervisor.QgaBackend(pve_profile)
    called = []
    backend.run = lambda args: called.append(args) or '{"exited":0}'
    record = {"pid": 123, "sequence": 7, "generation": "a" * 32, "state": "ready"}
    assert backend.reconcile_lease(record) is None
    assert called == [
        [
            "guest",
            "exec",
            "121",
            "--synchronous",
            "1",
            "--timeout",
            "5",
            "--",
            "/usr/bin/python3",
            "-B",
            supervisor.GUEST_HELPER,
            "reconcile-lease",
            "--pid",
            "123",
            "--sequence",
            "7",
            "--generation",
            "a" * 32,
            "--state",
            "ready",
        ]
    ]


@pytest.mark.parametrize(
    "field,value",
    [
        ("pid", None),
        ("pid", -1),
        ("pid", True),
        ("sequence", "7;echo bad"),
        ("generation", "a;echo bad"),
        ("state", "probe"),
    ],
)
def test_qga_reconciliation_rejects_untrusted_arguments(supervisor, pve_profile, field, value):
    backend = supervisor.QgaBackend(pve_profile)
    called = []
    backend.run = lambda args: called.append(args) or "{}"
    record = {"pid": 123, "sequence": 7, "generation": "a" * 32, "state": "ready"}
    record[field] = value
    with pytest.raises(ValueError):
        backend.reconcile_lease(record)
    assert called == []


def test_reconcile_cli_saves_atomic_receipt_without_ticking(
    supervisor, pve_profile, reconcile_setup, tmp_path, monkeypatch
):
    import hashlib

    controller, backend, _, _, _, _ = reconcile_setup
    state = controller.state
    state["host_boot_id"] = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    state["profile_digest"] = hashlib.sha256(
        json.dumps(pve_profile, sort_keys=True).encode()
    ).hexdigest()
    config = tmp_path / "profile.json"
    config.write_text(json.dumps(pve_profile))
    (tmp_path / "state.json").write_text(json.dumps(state))
    monkeypatch.setattr(supervisor, "DIRECTORY", tmp_path)
    monkeypatch.setattr(supervisor, "CONFIG", config)
    monkeypatch.setattr(supervisor.os, "geteuid", lambda: 0)
    monkeypatch.setattr(supervisor, "trusted", lambda path, **_: path.lstat())
    monkeypatch.setattr(supervisor, "QgaBackend", lambda _: backend)
    writes = []
    original = supervisor.atomic_state

    def record_write(path, value):
        original(path, value)
        writes.append(path.name)

    monkeypatch.setattr(supervisor, "atomic_state", record_write)
    result = supervisor.one("reconcile-lease")
    assert result["mode"] == "hold" and result["pending_lease"] is False
    assert writes == ["lease-reconciliation.json", "state.json"]
    receipt_path = tmp_path / "lease-reconciliation.json"
    receipt = json.loads(receipt_path.read_text())
    assert receipt["pending_lease"] == state["lease"]
    assert receipt_path.stat().st_mode & 0o777 == 0o600
    assert backend.started == []


def test_reconcile_cli_busy_is_not_success(supervisor, monkeypatch, capsys):
    import sys

    monkeypatch.setattr(sys, "argv", ["storage_supervisor.py", "reconcile-lease"])
    monkeypatch.setattr(supervisor, "one", lambda _: {"mode": "busy"})
    assert supervisor.main() == 75
    assert json.loads(capsys.readouterr().out) == {"mode": "busy"}


def test_guest_reconciliation_cli_rejects_core_profile(guest, reconciliation_files, monkeypatch):
    import sys

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "guest-storage-probe.py",
            "reconcile-lease",
            "--pid",
            "123",
            "--sequence",
            "7",
            "--generation",
            "a" * 32,
            "--state",
            "ready",
        ],
    )
    monkeypatch.setattr(guest.os, "geteuid", lambda: 0)
    monkeypatch.setattr(guest, "read_profile", lambda: {"version": 1, "role": "core"})
    assert guest.main() == 1


def test_guest_reconciliation_cli_returns_proof(guest, reconciliation_files, monkeypatch, capsys):
    import sys

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "guest-storage-probe.py",
            "reconcile-lease",
            "--pid",
            "123",
            "--sequence",
            "7",
            "--generation",
            "a" * 32,
            "--state",
            "ready",
        ],
    )
    monkeypatch.setattr(guest.os, "geteuid", lambda: 0)
    monkeypatch.setattr(guest, "read_profile", lambda: {"version": 1, "role": "playback"})
    assert guest.main() == 0
    assert json.loads(capsys.readouterr().out)["reconciled"] is True


def test_reconcile_cannot_clear_indefinitely_pending_core_probe(reconcile_setup):
    controller, backend, clock, _, _, receipts = reconcile_setup
    controller.state["probe"] = {"pid": 99, "nonce": "a" * 32, "started": 1, "generation": "a" * 32}
    backend.pending[99] = backend.pending[123] = None
    with pytest.raises(ValueError):
        controller.reconcile_lease(receipts.append)
    for _ in range(20):
        clock[0] += 60
        controller.tick()
    with pytest.raises(ValueError, match="pending"):
        controller.request("resume")
    assert controller.state["probe"]["pid"] == 99
    assert controller.state["lease"]["pid"] == 123
    assert controller.state["mode"] == "hold"
    assert receipts == [] and backend.started == []


@pytest.mark.parametrize("field", ["version", "sequence"])
def test_terminal_lease_boolean_numbers_are_rejected_atomically(setup, field):
    controller, backend, _, saved = setup
    controller.request("arm")
    controller.tick()
    complete_probe(controller, backend)
    controller.tick()
    complete_lease(controller, backend)
    backend.pending[controller.state["lease"]["pid"]][field] = True
    saved.clear()
    controller.poll_lease()
    assert len(saved) == 1
    assert saved[0]["lease"] is None
    assert saved[0]["mode"] == "hold" and saved[0]["reason"] == "lease-rejected"


@pytest.mark.parametrize("outer", ["{", '{"exited":"1"}', '{"error":"missing-pid"}'])
def test_ambiguous_outer_reply_keeps_core_probe_fenced(supervisor, pve_profile, setup, outer):
    controller, backend, clock, _ = setup
    controller.request("arm")
    controller.tick()
    pending = dict(controller.state["probe"])
    qga = supervisor.QgaBackend(pve_profile)
    qga.run = lambda _: outer
    backend.poll = qga.poll
    for _ in range(3):
        clock[0] += 20
        controller.tick()
    assert controller.state["mode"] == "hold" and controller.state["probe"] == pending
    assert len(backend.started) == 1


def test_malformed_exited_core_reply_clears_only_completed_probe(supervisor, pve_profile, setup):
    controller, backend, _, saved = setup
    controller.request("arm")
    controller.tick()
    qga = supervisor.QgaBackend(pve_profile)
    qga.run = lambda _: '{"exited":1,"exitcode":0,"out-data":"{"}'
    backend.poll = qga.poll
    controller.tick()
    assert controller.state["probe"] is None and controller.state["mode"] == "hold"
    assert controller.state["lease"]["state"] == "hold"
    assert len([role for role, _ in backend.started if role == "core"]) == 1
    assert saved[-1]["mode"] == "hold"
