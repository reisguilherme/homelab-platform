"""Synthetic core admission and crash fixtures; never access real storage."""

import copy
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BOOT = "12345678-1234-1234-1234-123456789abc"
UUID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
PROFILE = {
    "version": 1,
    "core_vmid": 101,
    "playback_vmid": 102,
    "core_name": "core",
    "playback_name": "playback",
    "usb_port": "1-2",
}


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def supervisor():
    return load("writer_supervisor", "scripts/storage_supervisor.py")


@pytest.fixture
def guest():
    return load("writer_guest", "infrastructure/storage/guest-storage-probe.py")


def migrated(supervisor):
    old = supervisor.new_state(BOOT, supervisor.profile_digest(PROFILE))
    old.update(sequence=1033, generation="a" * 32, ever_armed=True, hold_published=True)
    profile, state = supervisor.migration_candidate(PROFILE, old, BOOT)
    return old, profile, state


def test_explicit_migration_preserves_authority_history(supervisor):
    old, profile, state = migrated(supervisor)
    assert supervisor.validate_profile(profile) == {
        **PROFILE,
        "version": 2,
        "core_writer_enabled": True,
    }
    for key in (
        "sequence",
        "generation",
        "ever_armed",
        "host_boot_id",
        "probe",
        "lease",
        "physical_generation",
        "next_probe",
        "mode",
    ):
        assert state[key] == old[key]
    assert state["publication_round"] is None and state["hold_acks"] == []
    assert state["hold_published"] is False
    assert supervisor.validate_state(state, BOOT, supervisor.profile_digest(profile)) == state


@pytest.mark.parametrize("change", ["armed", "probe", "lease", "boot", "digest"])
def test_migration_never_discards_inflight_or_untrusted_state(supervisor, change):
    state = supervisor.new_state(BOOT, supervisor.profile_digest(PROFILE))
    if change == "armed":
        state["mode"] = "armed"
    elif change in {"probe", "lease"}:
        state[change] = {"pid": None}
    else:
        state["host_boot_id" if change == "boot" else "profile_digest"] = "different"
    original = copy.deepcopy(state)
    with pytest.raises(ValueError):
        supervisor.migration_candidate(PROFILE, state, BOOT)
    assert state == original


@pytest.mark.parametrize("crash_after", [1, 2, 3, 4])
def test_migration_crash_rolls_forward_exactly_without_reset(
    supervisor, tmp_path, monkeypatch, crash_after
):
    config, state_path, receipt = (tmp_path / name for name in ("config", "state", "receipt"))
    old, expected_profile, expected_state = migrated(supervisor)
    config.write_text(json.dumps(PROFILE))
    state_path.write_text(json.dumps(old))
    monkeypatch.setattr(supervisor, "trusted", lambda path, **_: path.lstat())
    atomic = supervisor.atomic_state
    writes = []

    def crash(path, value):
        atomic(path, value)
        writes.append(path)
        if len(writes) == crash_after:
            raise OSError("simulated-power-loss")

    monkeypatch.setattr(supervisor, "atomic_state", crash)
    with pytest.raises(OSError):
        supervisor.migrate_files(config, state_path, receipt, BOOT)
    assert writes[0] == receipt
    monkeypatch.setattr(supervisor, "atomic_state", atomic)
    supervisor.migrate_files(config, state_path, receipt, BOOT, complete=True)
    assert json.loads(config.read_text()) == expected_profile
    assert json.loads(state_path.read_text()) == expected_state
    assert json.loads(receipt.read_text())["phase"] == "committed"


def test_migration_receipt_cannot_overwrite_later_state(supervisor, tmp_path, monkeypatch):
    config, state_path, receipt = (tmp_path / name for name in ("config", "state", "receipt"))
    old, _, _ = migrated(supervisor)
    config.write_text(json.dumps(PROFILE))
    state_path.write_text(json.dumps(old))
    monkeypatch.setattr(supervisor, "trusted", lambda path, **_: path.lstat())
    supervisor.migrate_files(config, state_path, receipt, BOOT)
    state = json.loads(state_path.read_text())
    state["sequence"] += 4
    state_path.write_text(json.dumps(state))
    before = state_path.read_bytes()
    with pytest.raises(ValueError):
        supervisor.migrate_files(config, state_path, receipt, BOOT, complete=True)
    assert state_path.read_bytes() == before


def writer_publication(guest, tmp_path, monkeypatch, **changes):
    monkeypatch.setattr(guest, "trusted", lambda path, **_: path.lstat())
    directory = tmp_path / "core-writer-admission"
    directory.mkdir(exist_ok=True)
    args = dict(
        directory=directory,
        journal=tmp_path / "core-writer-lease-state.json",
        profile={"version": 1, "role": "core", "filesystem_uuid": UUID},
        state="ready",
        generation="a" * 32,
        sequence=1034,
        not_after=1045,
        boot_id=BOOT,
        wall_time=1020,
        uptime=120,
        expected_boot=BOOT,
        filesystem_uuid=UUID,
        physical_generation="b" * 64,
        observed_uptime=100,
    )
    args.update(changes)
    return guest.publish_core_writer_lease(**args)


def test_writer_lease_is_distinct_and_capped_to_original_proof(guest, tmp_path, monkeypatch):
    ack = writer_publication(guest, tmp_path, monkeypatch, not_after=1060)
    text = (tmp_path / "core-writer-admission/lease").read_text()
    assert text == (
        f"version=2\nrole=core-writer\nstate=ready\nboot_id={BOOT}\n"
        f"filesystem_uuid={UUID}\ngeneration={'a' * 32}\n"
        f"physical_generation={'b' * 64}\nsequence=1034\n"
        "expires_uptime_seconds=145\n"
    )
    assert ack == dict(
        version=2,
        role="core-writer",
        written=True,
        sequence=1034,
        generation="a" * 32,
        state="ready",
        boot_id=BOOT,
        filesystem_uuid=UUID,
    )
    assert not (tmp_path / "admission").exists()
    before = (tmp_path / "core-writer-admission/lease").read_bytes()
    with pytest.raises(ValueError):
        writer_publication(guest, tmp_path, monkeypatch)
    assert (tmp_path / "core-writer-admission/lease").read_bytes() == before


@pytest.mark.parametrize(
    "changes",
    [
        {"expected_boot": UUID},
        {"filesystem_uuid": BOOT},
        {"observed_uptime": 75},
        {"observed_uptime": 121},
        {"observed_uptime": True},
        {"sequence": True},
        {"physical_generation": "none"},
        {"not_after": 1066},
        {"profile": {"version": 1, "role": "playback"}},
    ],
)
def test_writer_refuses_stale_wrong_boot_identity_and_role(guest, tmp_path, monkeypatch, changes):
    with pytest.raises(ValueError):
        writer_publication(guest, tmp_path, monkeypatch, **changes)
    assert not (tmp_path / "core-writer-admission/lease").exists()


class Backend:
    def __init__(self):
        self.pending, self.started, self.pid = {}, [], 100

    def verify_profile(self):
        pass

    def launch(self, role, args):
        self.pid += 1
        self.started.append((role, args))
        self.pending[self.pid] = None
        return self.pid

    def poll(self, role, pid):
        return self.pending[pid]


def controller_setup(supervisor):
    _, _, state = migrated(supervisor)
    clock, backend, saved = [100.0], Backend(), []
    controller = supervisor.WriterController(
        state,
        backend,
        lambda: clock[0],
        lambda: 1000 + clock[0],
        lambda: saved.append(copy.deepcopy(state)),
    )
    return controller, backend, clock, saved


def proof(controller, backend):
    record = controller.state["probe"]
    backend.pending[record["pid"]] = dict(
        version=2,
        nonce=record["nonce"],
        healthy=True,
        reason="ok",
        generation="b" * 64,
        boot_id=BOOT,
        filesystem_uuid=UUID,
        observed_uptime_seconds=100,
    )


def ack(controller, backend):
    record = controller.state["lease"]
    result = dict(
        version=1,
        written=True,
        sequence=record["sequence"],
        generation=record["generation"],
        state=record["state"],
    )
    if record["recipient"] == "core-writer":
        result.update(version=2, role="core-writer", boot_id=BOOT, filesystem_uuid=UUID)
    backend.pending[record["pid"]] = result


def test_two_serial_ready_publications_share_proof_deadline(supervisor):
    controller, backend, clock, saved = controller_setup(supervisor)
    controller.request("resume")
    controller.tick()
    assert backend.started[-1][1][0] == "probe-core-writer"
    clock[0] += 5
    proof(controller, backend)
    controller.tick()
    first = copy.deepcopy(controller.state["lease"])
    assert first["recipient"] == "playback" and first["sequence"] == 1034
    ack(controller, backend)
    clock[0] += 5
    controller.tick()
    second = controller.state["lease"]
    assert second["recipient"] == "core-writer" and second["sequence"] == 1035
    ready = [args for _, args in backend.started if "lease-ready" in args[0]]
    assert [a[a.index("--not-after") + 1] for a in ready] == ["1145", "1145"]
    ack(controller, backend)
    controller.tick()
    assert controller.state["publication_round"] is None
    assert controller.state["reason"] == "healthy-leases-published"
    assert all(s["sequence"] >= 1033 for s in saved)


def test_hold_between_recipients_prevents_writer_ready_and_preserves_hold_progress(supervisor):
    controller, backend, _, _ = controller_setup(supervisor)
    controller.request("resume")
    controller.tick()
    proof(controller, backend)
    controller.tick()
    ack(controller, backend)
    controller.request("hold")
    controller.tick()
    assert controller.state["lease"]["recipient"] == "core-writer"
    assert controller.state["lease"]["state"] == "hold"
    ack(controller, backend)
    controller.tick()
    assert controller.state["hold_acks"] == ["core-writer"]
    controller.request("hold")
    ack(controller, backend)
    controller.tick()
    assert controller.state["hold_published"] is True
    assert not any(a[0] == "core-writer-lease-ready" for _, a in backend.started)


def test_ambiguous_writer_publication_stays_fenced_without_new_probe(supervisor):
    controller, backend, clock, _ = controller_setup(supervisor)
    controller.request("resume")
    controller.tick()
    proof(controller, backend)
    controller.tick()
    ack(controller, backend)
    controller.tick()
    pending = copy.deepcopy(controller.state["lease"])
    clock[0] += 16
    controller.tick()
    controller.tick()
    assert controller.state["mode"] == "hold" and controller.state["lease"] == pending
    assert len([a for _, a in backend.started if a[0] == "probe-core-writer"]) == 1
    with pytest.raises(ValueError):
        controller.request("resume")


@pytest.fixture
def writer_files(guest, tmp_path, monkeypatch):
    storage, proc = tmp_path / "storage", tmp_path / "proc"
    storage.mkdir()
    (storage / "core-writer-admission").mkdir()
    (proc / "sys/kernel/random").mkdir(parents=True)
    (proc / "sys/kernel/random/boot_id").write_text(BOOT)
    (proc / "uptime").write_text("120.0 200.0\n")
    monkeypatch.setattr(guest, "STATE", storage)
    monkeypatch.setattr(guest, "PROC", proc)
    monkeypatch.setattr(guest, "trusted", lambda path, **_: path.lstat())
    monkeypatch.setattr(guest.os, "geteuid", lambda: 0)
    monkeypatch.setattr(
        guest, "read_profile", lambda: dict(version=1, role="core", filesystem_uuid=UUID)
    )
    return storage, proc


def test_core_cli_publishes_distinct_lease_without_media_read(
    guest, writer_files, monkeypatch, capsys
):
    import sys

    storage, _ = writer_files
    monkeypatch.setattr(guest.time, "time", lambda: 1020)
    monkeypatch.setattr(guest, "core_probe", lambda *_: pytest.fail("publication probed media"))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "helper",
            "core-writer-lease-ready",
            "--generation",
            "a" * 32,
            "--sequence",
            "1034",
            "--not-after",
            "1045",
            "--expected-boot",
            BOOT,
            "--filesystem-uuid",
            UUID,
            "--physical-generation",
            "b" * 64,
            "--observed-uptime",
            "100",
        ],
    )
    assert guest.main() == 0
    assert json.loads(capsys.readouterr().out)["role"] == "core-writer"
    assert (storage / "core-writer-admission/lease").exists()
    assert not (storage / "admission").exists()


def test_new_probe_preserves_v1_result_and_captures_uptime_before_io(
    guest, writer_files, monkeypatch, capsys
):
    import sys

    _, proc = writer_files
    original = dict(
        version=1, nonce="a" * 32, healthy=True, reason="ok", generation="b" * 64, boot_id=BOOT
    )

    def probe(*_):
        (proc / "uptime").write_text("125.0 200.0\n")
        return original.copy()

    monkeypatch.setattr(guest, "core_probe", probe)
    monkeypatch.setattr(sys, "argv", ["helper", "probe-core-writer", "--nonce", "a" * 32])
    assert guest.main() == 0
    result = json.loads(capsys.readouterr().out)
    assert result == {
        **original,
        "version": 2,
        "filesystem_uuid": UUID,
        "observed_uptime_seconds": 120,
    }


@pytest.mark.parametrize(
    "mutation",
    [
        None,
        "live-pid",
        "wrong-journal",
        "not-expired",
        "boot",
        "uuid",
        "physical",
        "symlink",
        "busy",
        "playback",
    ],
)
def test_writer_reconciliation_is_readonly_exact_and_role_bound(
    guest, writer_files, monkeypatch, mutation
):
    storage, proc = writer_files
    profile = dict(version=1, role="core", filesystem_uuid=UUID)
    guest.publish_core_writer_lease(
        storage / "core-writer-admission",
        storage / "core-writer-lease-state.json",
        profile,
        "ready",
        "a" * 32,
        1034,
        1045,
        BOOT,
        1020,
        120,
        BOOT,
        UUID,
        "b" * 64,
        100,
    )
    (storage / "core-writer-lease.lock").touch(mode=0o600)
    (proc / "uptime").write_text("146.0 200.0\n")
    lease = storage / "core-writer-admission/lease"
    held = None
    if mutation == "live-pid":
        (proc / "123").mkdir()
    elif mutation == "wrong-journal":
        (storage / "core-writer-lease-state.json").write_text(
            '{"version":2,"role":"core-writer","sequence":1035}'
        )
    elif mutation == "not-expired":
        (proc / "uptime").write_text("144.0 200.0\n")
    elif mutation == "boot":
        (proc / "sys/kernel/random/boot_id").write_text(UUID)
    elif mutation == "uuid":
        lease.write_text(
            lease.read_text().replace(f"filesystem_uuid={UUID}", f"filesystem_uuid={BOOT}")
        )
    elif mutation == "physical":
        lease.write_text(lease.read_text().replace("b" * 64, "c" * 64))
    elif mutation == "symlink":
        lease.rename(lease.with_name("other"))
        lease.symlink_to(lease.with_name("other"))
    elif mutation == "busy":
        held = (storage / "core-writer-lease.lock").open()
        guest.fcntl.flock(held, guest.fcntl.LOCK_EX | guest.fcntl.LOCK_NB)
    elif mutation == "playback":
        profile = dict(version=1, role="playback")
    before = {str(p): p.read_bytes() for p in storage.rglob("*") if p.is_file()}
    try:
        if mutation:
            with pytest.raises((OSError, ValueError)):
                guest.reconcile_core_writer_lease(
                    profile, 123, 1034, "a" * 32, "ready", BOOT, UUID, "b" * 64
                )
        else:
            result = guest.reconcile_core_writer_lease(
                profile, 123, 1034, "a" * 32, "ready", BOOT, UUID, "b" * 64
            )
            assert result["role"] == "core-writer" and result["sequence"] == 1034
            assert result["physical_generation"] == "b" * 64
    finally:
        if held:
            held.close()
    assert {str(p): p.read_bytes() for p in storage.rglob("*") if p.is_file()} == before


def test_realistic_cli_costs_keep_two_recipients_fresh_across_cron(supervisor):
    _, _, state = migrated(supervisor)
    clock, events, deadlines = [0.0], [], {}

    class TimedBackend(Backend):
        def verify_profile(self):
            clock[0] += 3

        def launch(self, role, args):
            pid = super().launch(role, args)
            started = clock[0]
            clock[0] += 1.5
            if args[0] == "probe-core-writer":
                value = dict(
                    version=2,
                    nonce=args[-1],
                    healthy=True,
                    reason="ok",
                    generation="b" * 64,
                    boot_id=BOOT,
                    filesystem_uuid=UUID,
                    observed_uptime_seconds=int(started),
                )
            else:
                value = dict(
                    version=1,
                    written=True,
                    sequence=int(args[args.index("--sequence") + 1]),
                    generation=args[args.index("--generation") + 1],
                    state=args[0].split("-")[-1],
                )
                if role == "core":
                    value.update(version=2, role="core-writer", boot_id=BOOT, filesystem_uuid=UUID)
                if value["state"] == "ready":
                    if role in deadlines:
                        assert clock[0] < deadlines[role], (role, clock[0], deadlines[role])
                    deadlines[role] = int(args[args.index("--not-after") + 1]) - 1000
            self.pending[pid] = value
            events.append((args[0], started))
            return pid

        def poll(self, role, pid):
            clock[0] += 1.5
            return self.pending[pid]

    backend = TimedBackend()
    controller = supervisor.WriterController(
        state, backend, lambda: clock[0], lambda: 1000 + clock[0], lambda: None
    )
    controller.request("resume")
    for minute in range(30):
        clock[0] = max(clock[0], minute * 60)
        until = clock[0] + 58
        while True:
            controller.tick()
            assert state["mode"] == "armed", (state["reason"], clock[0], events[-5:])
            assert all(clock[0] < expiry for expiry in deadlines.values())
            supervisor.validate_state(state, BOOT, state["profile_digest"])
            if clock[0] + 2 >= until:
                break
            clock[0] += 2
    assert len(events) > 100 and set(deadlines) == {"core", "playback"}


@pytest.mark.parametrize("corrupt", ["role", "bool", "boot", "uuid", "stale"])
def test_writer_terminal_ack_is_classified_atomically(supervisor, corrupt):
    controller, backend, _, saved = controller_setup(supervisor)
    controller.request("resume")
    controller.tick()
    proof(controller, backend)
    controller.tick()
    ack(controller, backend)
    controller.tick()
    ack(controller, backend)
    value = backend.pending[controller.state["lease"]["pid"]]
    if corrupt == "stale":
        controller.request("hold")
    else:
        key, bad = {
            "role": ("role", "playback"),
            "bool": ("version", True),
            "boot": ("boot_id", UUID),
            "uuid": ("filesystem_uuid", BOOT),
        }[corrupt]
        value[key] = bad
    saved.clear()
    controller.poll_lease()
    assert len(saved) == 1
    assert saved[0]["mode"] == "hold" and saved[0]["lease"] is None
    assert saved[0]["publication_round"] is None


def test_writer_qga_reconciliation_routes_to_core(supervisor):
    controller, backend, _, _ = controller_setup(supervisor)
    controller.request("resume")
    controller.tick()
    proof(controller, backend)
    controller.tick()
    ack(controller, backend)
    controller.tick()
    qga = supervisor.QgaBackend({**PROFILE, "version": 2, "core_writer_enabled": True})
    calls = []
    qga.run = lambda args: calls.append(args) or '{"exited":1,"exitcode":1}'
    qga.reconcile_lease(controller.state["lease"])
    assert calls[0][2] == str(PROFILE["core_vmid"])
    assert "reconcile-core-writer-lease" in calls[0] and "--expected-boot" in calls[0]


def cli_files(supervisor, tmp_path, monkeypatch):
    config, directory = tmp_path / "config", tmp_path / "state-directory"
    directory.mkdir()
    config.write_text(json.dumps(PROFILE))
    boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    state = supervisor.new_state(boot, supervisor.profile_digest(PROFILE))
    state.update(sequence=1033, ever_armed=True, generation="a" * 32)
    (directory / "state.json").write_text(json.dumps(state))
    monkeypatch.setattr(supervisor, "CONFIG", config)
    monkeypatch.setattr(supervisor, "DIRECTORY", directory)
    monkeypatch.setattr(supervisor, "trusted", lambda path, **_: path.lstat())
    monkeypatch.setattr(supervisor.os, "geteuid", lambda: 0)
    backend = Backend()
    monkeypatch.setattr(supervisor, "QgaBackend", lambda _: backend)
    return config, directory, boot, backend


def test_enable_cli_is_inert_and_leaves_current_history_held(supervisor, tmp_path, monkeypatch):
    config, directory, _, backend = cli_files(supervisor, tmp_path, monkeypatch)
    result = supervisor.one("enable-core-writer")
    state = json.loads((directory / "state.json").read_text())
    assert result["mode"] == "hold" and backend.started == []
    assert state["sequence"] == 1033 and state["generation"] == "a" * 32
    assert json.loads(config.read_text())["core_writer_enabled"] is True
    assert supervisor.one("status")["mode"] == "hold"


@pytest.mark.parametrize(
    "change", ["missing-receipt", "old-profile", "missing-state", "sequence-rewind"]
)
def test_v2_runtime_requires_committed_migration_and_preserved_history(
    supervisor, tmp_path, monkeypatch, change
):
    config, directory, _, backend = cli_files(supervisor, tmp_path, monkeypatch)
    supervisor.one("enable-core-writer")
    state_path = directory / "state.json"
    if change == "missing-receipt":
        (directory / "core-writer-migration.json").unlink()
    elif change == "old-profile":
        receipt = json.loads((directory / "core-writer-migration.json").read_text())
        config.write_text(json.dumps(receipt["old_profile"]))
        state_path.write_text(json.dumps(receipt["old_state"]))
    elif change == "missing-state":
        state_path.unlink()
    else:
        state = json.loads(state_path.read_text())
        state["sequence"] = 1
        state_path.write_text(json.dumps(state))
    with pytest.raises(ValueError):
        supervisor.one("tick")
    assert backend.started == []


def test_prepared_migration_blocks_tick_but_has_readonly_status(supervisor, tmp_path, monkeypatch):
    config, directory, boot, backend = cli_files(supervisor, tmp_path, monkeypatch)
    atomic = supervisor.atomic_state

    def stop_after_receipt(path, value):
        atomic(path, value)
        raise OSError("crash")

    monkeypatch.setattr(supervisor, "atomic_state", stop_after_receipt)
    with pytest.raises(OSError):
        supervisor.one("enable-core-writer")
    before = {p.name: p.read_bytes() for p in directory.iterdir()}
    assert supervisor.one("status") == {"mode": "hold", "reason": "migration-pending"}
    with pytest.raises(ValueError):
        supervisor.one("tick")
    assert before == {p.name: p.read_bytes() for p in directory.iterdir()}
    assert backend.started == []
    monkeypatch.setattr(supervisor, "atomic_state", atomic)
    assert supervisor.one("complete-core-writer-migration")["mode"] == "hold"


@pytest.mark.parametrize("elapsed,drift", [(40, 0), (5, 10), (5, -10)])
def test_expired_or_clock_shifted_proof_does_not_publish_writer(supervisor, elapsed, drift):
    controller, backend, clock, _ = controller_setup(supervisor)
    controller.request("resume")
    controller.tick()
    proof(controller, backend)
    controller.tick()
    ack(controller, backend)
    controller.poll_lease()
    clock[0] += elapsed
    if elapsed == 40:
        clock[0] += 6
    controller.wall_clock = lambda: 1000 + clock[0] + drift
    controller.tick()
    assert controller.state["mode"] == "hold"
    assert not any(args[0] == "core-writer-lease-ready" for _, args in backend.started)


def test_restart_after_first_ack_uses_remaining_recipient_without_new_proof(supervisor):
    controller, backend, clock, saved = controller_setup(supervisor)
    controller.request("resume")
    controller.tick()
    proof(controller, backend)
    controller.tick()
    ack(controller, backend)
    controller.poll_lease()
    restored = copy.deepcopy(saved[-1])
    supervisor.validate_state(restored, BOOT, restored["profile_digest"])
    recreated = supervisor.WriterController(
        restored, backend, lambda: clock[0], lambda: 1000 + clock[0], lambda: None
    )
    recreated.tick()
    assert restored["lease"]["recipient"] == "core-writer"
    assert len([args for _, args in backend.started if args[0] == "probe-core-writer"]) == 1


def test_unknown_core_probe_pid_stays_fenced_across_restart(supervisor):
    controller, backend, clock, saved = controller_setup(supervisor)
    controller.request("resume")

    def ambiguous(role, args):
        backend.started.append((role, args))
        raise RuntimeError("lost-pid")

    backend.launch = ambiguous
    controller.tick()
    state = copy.deepcopy(saved[-1])
    assert state["probe"]["pid"] is None and state["mode"] == "hold"
    recreated = supervisor.WriterController(
        state, backend, lambda: clock[0], lambda: 1000 + clock[0], lambda: None
    )
    clock[0] += 100
    recreated.tick()
    recreated.tick()
    assert len([args for _, args in backend.started if args[0] == "probe-core-writer"]) == 1
    with pytest.raises(ValueError):
        recreated.request("resume")


def test_failed_resume_does_not_mutate_hold_ack_history(supervisor):
    controller, backend, _, _ = controller_setup(supervisor)
    controller.tick()
    ack(controller, backend)
    controller.tick()
    before = copy.deepcopy(controller.state)
    assert before["hold_acks"] == ["core-writer"] and before["lease"]
    with pytest.raises(ValueError):
        controller.request("resume")
    assert controller.state == before


def test_writer_reconciliation_receipt_precedes_atomic_clear(supervisor, guest, writer_files):
    controller, backend, _, saved = controller_setup(supervisor)
    controller.request("resume")
    controller.tick()
    proof(controller, backend)
    controller.tick()
    ack(controller, backend)
    controller.tick()
    pending = copy.deepcopy(controller.state["lease"])
    storage, proc = writer_files
    guest.publish_core_writer_lease(
        storage / "core-writer-admission",
        storage / "core-writer-lease-state.json",
        dict(version=1, role="core", filesystem_uuid=UUID),
        "ready",
        pending["generation"],
        pending["sequence"],
        1045,
        BOOT,
        1020,
        120,
        BOOT,
        UUID,
        "b" * 64,
        100,
    )
    (storage / "core-writer-lease.lock").touch(mode=0o600)
    (proc / "uptime").write_text("146.0 200.0\n")
    reconciled = guest.reconcile_core_writer_lease(
        dict(version=1, role="core", filesystem_uuid=UUID),
        pending["pid"],
        pending["sequence"],
        pending["generation"],
        "ready",
        BOOT,
        UUID,
        "b" * 64,
    )
    backend.reconcile_lease = lambda _: reconciled
    controller.request("hold")
    saved.clear()
    receipts = []

    def record(value):
        assert controller.state["lease"] == pending
        receipts.append(value)

    controller.reconcile_lease(record)
    assert len(receipts) == len(saved) == 1
    assert saved[0]["lease"] is None and saved[0]["mode"] == "hold"
    supervisor.validate_state(saved[0], BOOT, saved[0]["profile_digest"])
    controller.tick()
    assert controller.state["lease"]["sequence"] > pending["sequence"]
    assert controller.state["lease"]["recipient"] == "core-writer"


def test_writer_journal_survives_failed_lease_replace_and_refuses_replay(
    guest, tmp_path, monkeypatch
):
    original = guest.atomic

    def fail_lease(path, data, mode):
        if path.name == "lease":
            raise OSError("simulated-rename-failure")
        original(path, data, mode)

    monkeypatch.setattr(guest, "atomic", fail_lease)
    with pytest.raises(OSError):
        writer_publication(guest, tmp_path, monkeypatch)
    journal = json.loads((tmp_path / "core-writer-lease-state.json").read_text())
    assert journal["sequence"] == 1034
    assert not (tmp_path / "core-writer-admission/lease").exists()
    monkeypatch.setattr(guest, "atomic", original)
    with pytest.raises(ValueError, match="sequence"):
        writer_publication(guest, tmp_path, monkeypatch)


def test_unknown_writer_pid_is_never_republished_or_reconciled_automatically(supervisor):
    controller, backend, clock, _ = controller_setup(supervisor)
    controller.request("resume")
    controller.tick()
    proof(controller, backend)
    controller.tick()
    ack(controller, backend)

    def ambiguous(role, args):
        backend.started.append((role, args))
        raise RuntimeError("lost-writer-pid")

    backend.launch = ambiguous
    controller.tick()
    assert controller.state["mode"] == "hold"
    assert controller.state["lease"]["pid"] is None
    clock[0] += 100
    controller.tick()
    controller.tick()
    assert len([a for _, a in backend.started if a[0] == "core-writer-lease-ready"]) == 1
    with pytest.raises(ValueError):
        controller.reconcile_lease(lambda _: pytest.fail("unknown PID reconciled"))


@pytest.mark.parametrize(
    "field,value",
    [
        ("role", "playback"),
        ("boot_id", UUID),
        ("filesystem_uuid", BOOT),
        ("physical_generation", "c" * 64),
        ("sequence", True),
    ],
)
def test_supervisor_refuses_foreign_writer_reconciliation_proof(supervisor, field, value):
    controller, backend, _, _ = controller_setup(supervisor)
    controller.request("resume")
    controller.tick()
    proof(controller, backend)
    controller.tick()
    ack(controller, backend)
    controller.tick()
    record = controller.state["lease"]
    result = dict(
        version=2,
        role="core-writer",
        reconciled=True,
        pid=record["pid"],
        sequence=record["sequence"],
        generation=record["generation"],
        state="ready",
        boot_id=BOOT,
        filesystem_uuid=UUID,
        physical_generation="b" * 64,
        expires_uptime_seconds=145,
        observed_uptime_seconds=146,
        lease_sha256="c" * 64,
        journal_sha256="d" * 64,
    )
    result[field] = value
    with pytest.raises(ValueError):
        supervisor.validate_reconciliation_proof(result, record)
