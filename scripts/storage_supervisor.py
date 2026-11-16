#!/usr/bin/env python3
"""QGA storage containment. No remount, repair, passthrough change or app start."""

from __future__ import annotations

import argparse
import copy
import fcntl
import hashlib
import json
import math
import os
import re
import resource
import stat
import subprocess
import tempfile
import time
import uuid
from pathlib import Path

CONFIG = Path("/etc/homelab-storage-supervisor.json")
DIRECTORY = Path("/var/lib/homelab-storage-supervisor")
GUEST_HELPER = "/usr/local/lib/homelab-storage/guest-storage-probe.py"
PROBE_DEADLINE = 15
LEASE_DEADLINE = 15
PROBE_INTERVAL = 10
LEASE_TTL = 45
UUID_PATTERN = r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}"


def new_state(boot_id, profile_digest):
    return {
        "version": 1,
        "host_boot_id": boot_id,
        "profile_digest": profile_digest,
        "mode": "hold",
        "reason": "unarmed",
        "ever_armed": False,
        "generation": uuid.uuid4().hex,
        "sequence": 0,
        "probe": None,
        "lease": None,
        "physical_generation": None,
        "next_probe": 0,
        "hold_published": False,
    }


class Controller:
    def __init__(self, state, backend, clock, wall_clock, persist):
        self.state, self.backend = state, backend
        self.clock, self.wall_clock, self.persist = clock, wall_clock, persist

    def hold(self, reason):
        if self.state["mode"] != "hold":
            self.state["generation"] = uuid.uuid4().hex
            self.state["hold_published"] = False
        self.state.update(mode="hold", reason=reason)
        self.persist()

    def request(self, action):
        if action == "hold":
            self.hold("operator-hold")
            return
        if action == "arm" and self.state["ever_armed"]:
            raise ValueError("use-explicit-resume")
        if action == "resume" and self.state["mode"] != "hold":
            raise ValueError("already-armed")
        if self.state["probe"] or self.state["lease"]:
            raise ValueError("pending-execution")
        if action not in {"arm", "resume"}:
            raise ValueError("invalid-action")
        self.state.update(
            mode="armed",
            reason="awaiting-fresh-proof",
            ever_armed=True,
            generation=uuid.uuid4().hex,
            physical_generation=None,
            next_probe=0,
            hold_published=False,
        )
        self.persist()

    def reconcile_lease(self, receipt):
        if self.state["mode"] != "hold" or self.state["probe"] is not None:
            raise ValueError("lease-reconciliation-precondition")
        validate_reconciliation_record(self.state["lease"])
        record = dict(self.state["lease"])
        try:
            self.backend.verify_profile()
            proof = self.backend.reconcile_lease(record)
            validate_reconciliation_proof(proof, record)
            if (
                self.state["lease"] != record
                or self.state["mode"] != "hold"
                or self.state["probe"] is not None
            ):
                raise ValueError("lease-reconciliation-changed")
            # This durable receipt must precede the durable removal of the pending record.
            receipt(
                {
                    "version": 1,
                    "reason": "lease-reconciled",
                    "host_boot_id": self.state["host_boot_id"],
                    "profile_digest": self.state["profile_digest"],
                    "observed_unix_seconds": int(self.wall_clock()),
                    "pending_lease": record,
                    "proof": proof,
                }
            )
        except (OSError, ValueError, RuntimeError, KeyError, TypeError, subprocess.SubprocessError):
            self.hold("lease-reconciliation-refused")
            raise ValueError("lease-reconciliation-refused") from None
        self.state.update(lease=None, reason="lease-reconciled", hold_published=False)
        if self.state["version"] == 2:
            self.state["hold_acks"] = []
        self.persist()

    def launch_probe(self):
        record = {
            "pid": None,
            "nonce": uuid.uuid4().hex,
            "started": self.clock(),
            "generation": self.state["generation"],
        }
        self.state["probe"] = record
        self.persist()  # A crash/timeout can leave a real guest process without a returned PID.
        record["pid"] = self.backend.launch("core", ["probe", "--nonce", record["nonce"]])
        self.persist()

    def launch_lease(self, state):
        self.state["sequence"] += 1
        record = {
            "pid": None,
            "sequence": self.state["sequence"],
            "state": state,
            "generation": self.state["generation"],
            "started": self.clock(),
        }
        self.state["lease"] = record
        self.persist()
        args = [
            f"lease-{state}",
            "--generation",
            record["generation"],
            "--sequence",
            str(record["sequence"]),
        ]
        if state == "ready":
            args += ["--not-after", str(int(self.wall_clock()) + LEASE_TTL)]
        record["pid"] = self.backend.launch("playback", args)
        self.persist()

    def poll_lease(self):
        record = self.state["lease"]
        if record is None:
            return
        if record["pid"] is None:
            self.hold("lease-launch-ambiguous")
            return
        result = self.backend.poll("playback", record["pid"])
        expired = self.clock() - record["started"] > LEASE_DEADLINE
        if result is None:
            if expired:
                self.hold("lease-timeout")
            return
        self.state["lease"] = None
        expected = {
            "version": 1,
            "written": True,
            "sequence": record["sequence"],
            "generation": record["generation"],
            "state": record["state"],
        }
        if (
            result != expected
            or type(result["version"]) is not int
            or type(result["sequence"]) is not int
            or result["written"] is not True
        ):
            self.hold("lease-rejected")
        elif expired:
            self.hold("lease-timeout")
        elif record["generation"] != self.state["generation"]:
            self.state["reason"] = "lease-completed-stale"
            self.persist()
        elif record["state"] == "hold":
            self.state["hold_published"] = True
            self.state["reason"] = "lease-hold-published"
            self.persist()
        else:
            self.state["reason"] = "healthy-lease-published"
            self.persist()

    def poll_probe(self):
        record = self.state["probe"]
        if record is None:
            return False
        if record["pid"] is None:
            self.hold("probe-launch-ambiguous")
            return False
        result = self.backend.poll("core", record["pid"])
        expired = self.clock() - record["started"] > PROBE_DEADLINE
        if expired:
            self.hold("probe-timeout")
        if result is None:
            return False
        self.state["probe"] = None
        self.persist()
        if expired or self.state["mode"] != "armed":
            return False
        if (
            not isinstance(result, dict)
            or set(result) != {"version", "nonce", "healthy", "reason", "generation", "boot_id"}
            or result["version"] != 1
            or result["healthy"] is not True
            or result["reason"] != "ok"
            or result["nonce"] != record["nonce"]
            or not re.fullmatch(r"[0-9a-f]{64}", str(result["generation"]))
            or not re.fullmatch(
                r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", str(result["boot_id"])
            )
            or record["generation"] != self.state["generation"]
        ):
            self.hold("probe-rejected")
            return False
        prior = self.state["physical_generation"]
        if prior is not None and prior != result["generation"]:
            self.hold("physical-generation-changed")
            return False
        self.state["physical_generation"] = result["generation"]
        self.state["next_probe"] = self.clock() + PROBE_INTERVAL
        self.persist()
        return True

    def tick(self):
        try:
            self.backend.verify_profile()
        except (OSError, RuntimeError, ValueError, subprocess.SubprocessError):
            self.hold("profile-unavailable")
            return
        try:
            self.poll_lease()
            fresh = self.poll_probe()
            if self.state["mode"] == "hold":
                if self.state["lease"] is None and not self.state["hold_published"]:
                    self.launch_lease("hold")
                return
            if fresh:
                if self.state["lease"] is not None:
                    self.hold("publication-overlap")
                    return
                self.launch_lease("ready")
            elif (
                self.state["probe"] is None
                and self.state["lease"] is None
                and self.clock() >= self.state["next_probe"]
            ):
                self.launch_probe()
        except (OSError, RuntimeError, ValueError, KeyError, subprocess.SubprocessError):
            self.hold("operation-failed")


class WriterController(Controller):
    """Opt-in serial recipients; the legacy controller remains playback-only."""

    def hold(self, reason):
        if self.state["mode"] != "hold":
            self.state["hold_acks"] = []
        self.state["publication_round"] = None
        super().hold(reason)

    def request(self, action):
        if action != "hold" and self.state["publication_round"] is not None:
            raise ValueError("pending-publication-round")
        if action != "hold":
            if self.state["probe"] is not None or self.state["lease"] is not None:
                raise ValueError("pending-execution")
            if (
                action not in {"arm", "resume"}
                or action == "arm"
                and self.state["ever_armed"]
                or action == "resume"
                and self.state["mode"] != "hold"
            ):
                raise ValueError("invalid-resume-request")
            self.state["hold_acks"] = []
        super().request(action)

    def launch_probe(self):
        record = dict(
            pid=None,
            nonce=uuid.uuid4().hex,
            started=self.clock(),
            wall_started=self.wall_clock(),
            generation=self.state["generation"],
        )
        self.state["probe"] = record
        self.persist()
        record["pid"] = self.backend.launch(
            "core", ["probe-core-writer", "--nonce", record["nonce"]]
        )
        self.persist()

    def poll_probe(self):
        record = self.state["probe"]
        if record is None:
            return
        if record["pid"] is None:
            self.hold("probe-launch-ambiguous")
            return
        result = self.backend.poll("core", record["pid"])
        expired = self.clock() - record["started"] > PROBE_DEADLINE
        if result is None:
            if expired:
                self.hold("probe-timeout")
            return
        self.state["probe"] = None
        if expired:
            self.hold("probe-timeout")
            return
        if self.state["mode"] != "armed":
            self.state["reason"] = "probe-completed-stale"
            self.persist()
            return
        keys = {
            "version",
            "nonce",
            "healthy",
            "reason",
            "generation",
            "boot_id",
            "filesystem_uuid",
            "observed_uptime_seconds",
        }
        if (
            not isinstance(result, dict)
            or set(result) != keys
            or type(result["version"]) is not int
            or result["version"] != 2
            or result["healthy"] is not True
            or result["reason"] != "ok"
            or result["nonce"] != record["nonce"]
            or not matches(r"[0-9a-f]{64}", result["generation"])
            or not matches(UUID_PATTERN, result["boot_id"])
            or not matches(UUID_PATTERN, result["filesystem_uuid"])
            or not unsigned(result["observed_uptime_seconds"])
            or record["generation"] != self.state["generation"]
        ):
            self.hold("probe-rejected")
            return
        if self.state["physical_generation"] not in (None, result["generation"]):
            self.hold("physical-generation-changed")
            return
        self.state["physical_generation"] = result["generation"]
        self.state["next_probe"] = self.clock() + PROBE_INTERVAL
        self.state["publication_round"] = dict(
            generation=record["generation"],
            nonce=record["nonce"],
            core_boot_id=result["boot_id"],
            filesystem_uuid=result["filesystem_uuid"],
            physical_generation=result["generation"],
            observed_uptime_seconds=result["observed_uptime_seconds"],
            started=record["started"],
            wall_started=record["wall_started"],
            deadline=record["started"] + LEASE_TTL,
            not_after=int(record["wall_started"]) + LEASE_TTL,
            acknowledged=[],
        )
        self.persist()

    def launch_lease(self, state, recipient):
        proof = copy.deepcopy(self.state["publication_round"]) if state == "ready" else None
        if proof is not None:
            remaining = proof["deadline"] - self.clock()
            drift = (self.wall_clock() - proof["wall_started"]) - (self.clock() - proof["started"])
            if remaining < 1 or abs(drift) > 1:
                self.hold("proof-deadline")
                return
            not_after = min(proof["not_after"], int(self.wall_clock() + remaining))
        self.state["sequence"] += 1
        record = dict(
            pid=None,
            sequence=self.state["sequence"],
            state=state,
            generation=self.state["generation"],
            started=self.clock(),
            recipient=recipient,
            proof=proof,
        )
        self.state["lease"] = record
        self.persist()
        action = f"lease-{state}" if recipient == "playback" else f"core-writer-lease-{state}"
        args = [action, "--generation", record["generation"], "--sequence", str(record["sequence"])]
        if proof is not None:
            args += ["--not-after", str(not_after)]
            if recipient == "core-writer":
                args += writer_proof_args(proof)
        record["pid"] = self.backend.launch("playback" if recipient == "playback" else "core", args)
        self.persist()

    def poll_lease(self):
        record = self.state["lease"]
        if record is None:
            return
        if record["pid"] is None:
            self.hold("lease-launch-ambiguous")
            return
        result = self.backend.poll(
            "playback" if record["recipient"] == "playback" else "core", record["pid"]
        )
        expired = self.clock() - record["started"] > LEASE_DEADLINE
        if result is None:
            if expired:
                self.hold("lease-timeout")
            return
        self.state["lease"] = None
        expected = dict(
            version=1,
            written=True,
            sequence=record["sequence"],
            generation=record["generation"],
            state=record["state"],
        )
        if record["recipient"] == "core-writer" and isinstance(result, dict):
            proof = record["proof"]
            boot, filesystem = result.get("boot_id"), result.get("filesystem_uuid")
            if (
                not matches(UUID_PATTERN, boot)
                or not matches(UUID_PATTERN, filesystem)
                or proof is not None
                and (boot != proof["core_boot_id"] or filesystem != proof["filesystem_uuid"])
            ):
                self.hold("lease-rejected")
                return
            expected.update(version=2, role="core-writer", boot_id=boot, filesystem_uuid=filesystem)
        if (
            result != expected
            or type(result["version"]) is not int
            or type(result["sequence"]) is not int
            or result["written"] is not True
        ):
            self.hold("lease-rejected")
        elif expired:
            self.hold("lease-timeout")
        elif record["generation"] != self.state["generation"]:
            self.state["reason"] = "lease-completed-stale"
            self.persist()
        elif record["state"] == "hold":
            self.state["hold_acks"].append(record["recipient"])
            self.state["hold_published"] = self.state["hold_acks"] == ["core-writer", "playback"]
            self.state["reason"] = "lease-hold-published"
            self.persist()
        else:
            current = self.state["publication_round"]
            if current is None or current != record["proof"] or self.clock() >= current["deadline"]:
                self.hold("proof-deadline")
                return
            current["acknowledged"].append(record["recipient"])
            if record["recipient"] == "core-writer":
                self.state["publication_round"] = None
                self.state["reason"] = "healthy-leases-published"
            else:
                self.state["reason"] = "awaiting-writer-publication"
            self.persist()

    def tick(self):
        try:
            self.backend.verify_profile()
        except (OSError, RuntimeError, ValueError, subprocess.SubprocessError):
            self.hold("profile-unavailable")
            return
        try:
            self.poll_lease()
            self.poll_probe()
            if self.state["lease"] is not None:
                return
            if self.state["mode"] == "hold":
                for recipient in ("core-writer", "playback"):
                    if recipient not in self.state["hold_acks"]:
                        self.launch_lease("hold", recipient)
                        break
            elif self.state["publication_round"] is not None:
                current = self.state["publication_round"]
                recipient = "core-writer" if current["acknowledged"] else "playback"
                self.launch_lease("ready", recipient)
            elif self.state["probe"] is None and self.clock() >= self.state["next_probe"]:
                self.launch_probe()
        except (OSError, RuntimeError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
            self.hold("operation-failed")


def writer_proof_args(proof):
    return [
        "--expected-boot",
        proof["core_boot_id"],
        "--filesystem-uuid",
        proof["filesystem_uuid"],
        "--physical-generation",
        proof["physical_generation"],
        "--observed-uptime",
        str(proof["observed_uptime_seconds"]),
    ]


def matches(pattern, value):
    return isinstance(value, str) and re.fullmatch(pattern, value) is not None


def unsigned(value):
    return type(value) is int and 0 <= value <= 2**63 - 1


def strict_json(text):
    def pairs(rows):
        data = {}
        for key, value in rows:
            if key in data:
                raise ValueError("duplicate-key")
            data[key] = value
        return data

    return json.loads(
        text,
        object_pairs_hook=pairs,
        parse_constant=lambda _: (_ for _ in ()).throw(ValueError("json-number")),
    )


def trusted(path, directory=False):
    for parent in reversed(path.parents):
        info = parent.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise ValueError("unsafe-parent")
    info = path.lstat()
    valid = stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)
    if (
        not valid
        or info.st_uid != 0
        or info.st_mode & 0o077
        or (not directory and info.st_nlink != 1)
    ):
        raise ValueError("unsafe-file")
    return info


def atomic_state(path, value):
    fd, temporary = tempfile.mkstemp(prefix=".supervisor-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            os.fchmod(stream.fileno(), 0o600)
            json.dump(value, stream, sort_keys=True, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def validate_profile(profile):
    if (
        isinstance(profile, dict)
        and type(profile.get("version")) is int
        and profile["version"] == 2
    ):
        if profile.get("core_writer_enabled") is not True:
            raise ValueError("profile-opt-in")
        legacy = {key: value for key, value in profile.items() if key != "core_writer_enabled"}
        legacy["version"] = 1
        validate_profile(legacy)
        return profile
    if (
        not isinstance(profile, dict)
        or set(profile)
        != {"version", "core_vmid", "playback_vmid", "core_name", "playback_name", "usb_port"}
        or profile["version"] != 1
    ):
        raise ValueError("profile-fields")
    for role in ("core", "playback"):
        if type(profile[f"{role}_vmid"]) is not int or not 100 <= profile[f"{role}_vmid"] < 10**9:
            raise ValueError("profile-vmid")
        if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9-]{0,62}", profile[f"{role}_name"]):
            raise ValueError("profile-name")
    if profile["core_vmid"] == profile["playback_vmid"] or not re.fullmatch(
        r"[1-9][0-9]*-[1-9][0-9]*(?:\.[1-9][0-9]*)*", profile["usb_port"]
    ):
        raise ValueError("profile-device")
    return profile


def validate_reconciliation_record(record):
    if (
        not isinstance(record, dict)
        or type(record.get("pid")) is not int
        or not 1 <= record["pid"] <= 2**31 - 1
        or type(record.get("sequence")) is not int
        or not 1 <= record["sequence"] <= 2**63 - 1
        or not isinstance(record.get("generation"), str)
        or not re.fullmatch(r"[0-9a-f]{32}", record["generation"])
        or record.get("state") not in {"ready", "hold"}
    ):
        raise ValueError("lease-reconciliation-record")


def validate_reconciliation_proof(proof, record):
    if record.get("recipient") == "core-writer":
        if (
            not isinstance(proof, dict)
            or type(proof.get("version")) is not int
            or proof["version"] != 2
            or proof.get("role") != "core-writer"
            or not matches(UUID_PATTERN, proof.get("filesystem_uuid"))
        ):
            raise ValueError("writer-reconciliation-role")
        physical = proof.get("physical_generation")
        if record["state"] == "ready":
            expected = record["proof"]
            if (
                proof.get("boot_id") != expected["core_boot_id"]
                or proof["filesystem_uuid"] != expected["filesystem_uuid"]
                or physical != expected["physical_generation"]
            ):
                raise ValueError("writer-reconciliation-identity")
        elif physical != "none":
            raise ValueError("writer-reconciliation-hold")
        legacy = {
            key: value
            for key, value in proof.items()
            if key not in {"role", "filesystem_uuid", "physical_generation"}
        }
        legacy["version"] = 1
        validate_reconciliation_proof(
            legacy, {key: value for key, value in record.items() if key != "recipient"}
        )
        return
    if (
        not isinstance(proof, dict)
        or set(proof)
        != {
            "version",
            "reconciled",
            "pid",
            "sequence",
            "generation",
            "state",
            "boot_id",
            "expires_uptime_seconds",
            "observed_uptime_seconds",
            "lease_sha256",
            "journal_sha256",
        }
        or type(proof["version"]) is not int
        or proof["version"] != 1
        or proof["reconciled"] is not True
    ):
        raise ValueError("lease-reconciliation-proof")
    validate_reconciliation_record(proof)
    if any(proof[key] != record[key] for key in ("pid", "sequence", "generation", "state")):
        raise ValueError("lease-reconciliation-mismatch")
    for field, pattern in (
        ("boot_id", r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}"),
        ("lease_sha256", r"[0-9a-f]{64}"),
        ("journal_sha256", r"[0-9a-f]{64}"),
    ):
        if not isinstance(proof[field], str) or not re.fullmatch(pattern, proof[field]):
            raise ValueError("lease-reconciliation-identity")
    for field in ("expires_uptime_seconds", "observed_uptime_seconds"):
        if type(proof[field]) is not int or not 0 <= proof[field] <= 2**63 - 1:
            raise ValueError("lease-reconciliation-time")
    expiry = proof["expires_uptime_seconds"]
    if (
        expiry > proof["observed_uptime_seconds"]
        or (proof["state"] == "hold" and expiry != 0)
        or (proof["state"] == "ready" and expiry == 0)
    ):
        raise ValueError("lease-reconciliation-expiry")


class QgaBackend:
    def __init__(self, profile):
        self.profile = validate_profile(profile)

    @staticmethod
    def run(args):
        def limit_output():
            resource.setrlimit(resource.RLIMIT_FSIZE, (1048576, 1048576))

        with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as error:
            process = subprocess.Popen(
                ["/usr/sbin/qm", *args], stdout=output, stderr=error, preexec_fn=limit_output
            )
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                process.kill()
                # This process only speaks to PVE/QGA; do not block on a guest I/O worker.
                try:
                    process.wait(timeout=0.1)
                except subprocess.TimeoutExpired:
                    pass
                raise RuntimeError("qga-timeout") from None
            output.seek(0)
            value = output.read(262145)
            if process.returncode or len(value) > 262144:
                raise RuntimeError("qga-command")
        return value.decode("utf-8")

    def verify_profile(self):
        for role in ("core", "playback"):
            raw = self.run(["config", str(self.profile[f"{role}_vmid"])])
            values = dict(line.split(": ", 1) for line in raw.splitlines() if ": " in line)
            if values.get("name") != self.profile[f"{role}_name"] or "lock" in values:
                raise ValueError("vm-profile")
            if role == "core":
                usb = dict(
                    pair.split("=", 1) for pair in values.get("usb0", "").split(",") if "=" in pair
                )
                if usb.get("host") != self.profile["usb_port"]:
                    raise ValueError("usb-profile")

    def launch(self, role, args):
        result = strict_json(
            self.run(
                [
                    "guest",
                    "exec",
                    str(self.profile[f"{role}_vmid"]),
                    "--synchronous",
                    "0",
                    "--",
                    "/usr/bin/python3",
                    "-B",
                    GUEST_HELPER,
                    *args,
                ]
            )
        )
        if set(result) != {"pid"} or type(result["pid"]) is not int or result["pid"] < 1:
            raise ValueError("qga-pid")
        return result["pid"]

    def poll(self, role, pid):
        result = strict_json(
            self.run(
                [
                    "guest",
                    "exec-status",
                    str(self.profile[f"{role}_vmid"]),
                    str(pid),
                ]
            )
        )
        return self.completion(result)

    def reconcile_lease(self, record):
        validate_reconciliation_record(record)
        writer = record.get("recipient") == "core-writer"
        extra = writer_proof_args(record["proof"]) if writer and record["state"] == "ready" else []
        result = strict_json(
            self.run(
                [
                    "guest",
                    "exec",
                    str(self.profile["core_vmid" if writer else "playback_vmid"]),
                    "--synchronous",
                    "1",
                    "--timeout",
                    "5",
                    "--",
                    "/usr/bin/python3",
                    "-B",
                    GUEST_HELPER,
                    "reconcile-core-writer-lease" if writer else "reconcile-lease",
                    "--pid",
                    str(record["pid"]),
                    "--sequence",
                    str(record["sequence"]),
                    "--generation",
                    record["generation"],
                    "--state",
                    record["state"],
                    *extra,
                ]
            )
        )
        return self.completion(result)

    @staticmethod
    def completion(result):
        if (
            not isinstance(result, dict)
            or type(result.get("exited")) not in {int, bool}
            or result["exited"] not in (0, 1)
        ):
            raise ValueError("qga-status-ambiguous")
        # Proxmox converts QGA JSON booleans to integer 0/1 in its API response.
        if result["exited"] == 0:
            return None
        if (
            result.get("exitcode") != 0
            or result.get("out-truncated")
            or result.get("err-truncated")
        ):
            return {"failed": True}
        value = result.get("out-data", "")
        if not isinstance(value, str) or len(value) > 16384:
            return {"failed": True}
        try:
            decoded = strict_json(value)
        except (ValueError, RecursionError):
            return {"failed": True}
        return decoded if isinstance(decoded, dict) else {"failed": True}


def validate_state(state, boot_id, profile_digest):
    if isinstance(state, dict) and type(state.get("version")) is int and state["version"] == 2:
        return validate_writer_state(state, boot_id, profile_digest)

    def seconds(value):
        return type(value) in {int, float} and math.isfinite(value) and value >= 0

    expected = set(new_state(boot_id, profile_digest))
    if (
        not isinstance(state, dict)
        or set(state) != expected
        or state["version"] != 1
        or state["mode"] not in {"hold", "armed"}
        or state["host_boot_id"] != boot_id
        or state["profile_digest"] != profile_digest
        or not re.fullmatch(r"[0-9a-f]{32}", str(state["generation"]))
        or type(state["sequence"]) is not int
        or state["sequence"] < 0
        or type(state["ever_armed"]) is not bool
        or type(state["hold_published"]) is not bool
        or not seconds(state["next_probe"])
        or not isinstance(state["reason"], str)
        or not re.fullmatch(r"[a-z-]{1,64}", state["reason"])
        or state["physical_generation"] is not None
        and not re.fullmatch(r"[0-9a-f]{64}", str(state["physical_generation"]))
    ):
        raise ValueError("state-review-required")
    for name in ("probe", "lease"):
        record = state[name]
        if record is None:
            continue
        keys = {"pid", "started", "generation"} | (
            {"nonce"} if name == "probe" else {"sequence", "state"}
        )
        if (
            not isinstance(record, dict)
            or set(record) != keys
            or not seconds(record["started"])
            or not re.fullmatch(r"[0-9a-f]{32}", str(record["generation"]))
            or record["pid"] is not None
            and (type(record["pid"]) is not int or record["pid"] < 1)
        ):
            raise ValueError("state-pending-invalid")
        if name == "probe":
            if not re.fullmatch(r"[0-9a-f]{32}", str(record["nonce"])):
                raise ValueError("state-probe-invalid")
        elif (
            record["state"] not in {"ready", "hold"}
            or type(record["sequence"]) is not int
            or not 1 <= record["sequence"] <= state["sequence"]
        ):
            raise ValueError("state-lease-invalid")
    return state


def validate_round(value):
    keys = {
        "generation",
        "nonce",
        "core_boot_id",
        "filesystem_uuid",
        "physical_generation",
        "observed_uptime_seconds",
        "started",
        "wall_started",
        "deadline",
        "not_after",
        "acknowledged",
    }
    if not isinstance(value, dict) or set(value) != keys:
        raise ValueError("round-fields")
    for key, pattern in (
        ("generation", r"[0-9a-f]{32}"),
        ("nonce", r"[0-9a-f]{32}"),
        ("core_boot_id", UUID_PATTERN),
        ("filesystem_uuid", UUID_PATTERN),
        ("physical_generation", r"[0-9a-f]{64}"),
    ):
        if not matches(pattern, value[key]):
            raise ValueError("round-identity")
    if (
        not unsigned(value["observed_uptime_seconds"])
        or not unsigned(value["not_after"])
        or value["acknowledged"] not in ([], ["playback"])
    ):
        raise ValueError("round-value")
    for key in ("started", "wall_started", "deadline"):
        if type(value[key]) not in (int, float) or not math.isfinite(value[key]) or value[key] < 0:
            raise ValueError("round-clock")
    if (
        value["deadline"] != value["started"] + LEASE_TTL
        or value["not_after"] != int(value["wall_started"]) + LEASE_TTL
    ):
        raise ValueError("round-deadline")


def validate_writer_state(state, boot_id, digest):
    if set(state) != set(new_state(boot_id, digest)) | {"publication_round", "hold_acks"}:
        raise ValueError("writer-state-fields")
    legacy = copy.deepcopy(state)
    legacy.update(version=1)
    current = legacy.pop("publication_round")
    acks = legacy.pop("hold_acks")
    if (
        acks not in ([], ["core-writer"], ["core-writer", "playback"])
        or state["hold_published"] != (acks == ["core-writer", "playback"])
        or state["mode"] == "armed"
        and acks
    ):
        raise ValueError("writer-hold-acks")
    if current is not None:
        validate_round(current)
        if (
            state["mode"] != "armed"
            or current["generation"] != state["generation"]
            or state["probe"] is not None
        ):
            raise ValueError("writer-round-state")
    probe, lease = legacy["probe"], legacy["lease"]
    if probe is not None:
        wall = probe.pop("wall_started", None)
        if type(wall) not in (int, float) or not math.isfinite(wall) or wall < 0:
            raise ValueError("writer-probe-clock")
    if lease is not None:
        recipient = lease.pop("recipient", None)
        if "proof" not in lease or recipient not in ("playback", "core-writer"):
            raise ValueError("writer-lease-recipient")
        proof = lease.pop("proof")
        if lease.get("state") == "ready":
            validate_round(proof)
            if proof["generation"] != lease.get("generation"):
                raise ValueError("writer-lease-generation")
            if recipient != ("core-writer" if proof["acknowledged"] else "playback"):
                raise ValueError("writer-lease-order")
            if state["mode"] == "armed" and proof != current:
                raise ValueError("writer-lease-round")
        elif proof is not None:
            raise ValueError("writer-hold-proof")
    validate_state(legacy, boot_id, digest)
    return state


def profile_digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def read_private_json(path, limit):
    if trusted(path).st_size > limit:
        raise ValueError("private-json-size")
    return strict_json(path.read_text())


def migration_candidate(profile, state, boot_id):
    validate_profile(profile)
    validate_state(state, boot_id, profile_digest(profile))
    if (
        profile["version"] != 1
        or state["version"] != 1
        or state["mode"] != "hold"
        or state["probe"] is not None
        or state["lease"] is not None
    ):
        raise ValueError("migration-precondition")
    candidate_profile = {**profile, "version": 2, "core_writer_enabled": True}
    candidate_state = copy.deepcopy(state)
    candidate_state.update(
        version=2,
        profile_digest=profile_digest(candidate_profile),
        reason="core-writer-migrated",
        publication_round=None,
        hold_acks=[],
        hold_published=False,
    )
    validate_state(candidate_state, boot_id, profile_digest(candidate_profile))
    return candidate_profile, candidate_state


def validate_migration_receipt(receipt, boot_id):
    keys = {
        "version",
        "action",
        "phase",
        "host_boot_id",
        "old_profile",
        "old_state",
        "new_profile",
        "new_state",
        "hashes",
    }
    if (
        not isinstance(receipt, dict)
        or set(receipt) != keys
        or type(receipt["version"]) is not int
        or receipt["version"] != 1
        or receipt["action"] != "enable-core-writer"
        or receipt["phase"] not in ("prepared", "committed")
        or receipt["host_boot_id"] != boot_id
    ):
        raise ValueError("migration-receipt")
    names = ("old_profile", "old_state", "new_profile", "new_state")
    if receipt["hashes"] != {name: profile_digest(receipt[name]) for name in names}:
        raise ValueError("migration-hashes")
    candidate = migration_candidate(receipt["old_profile"], receipt["old_state"], boot_id)
    if candidate != (receipt["new_profile"], receipt["new_state"]):
        raise ValueError("migration-candidate")


def migrate_files(config, state_path, receipt_path, boot_id, *, complete=False):
    """Caller holds the supervisor flock. Never launch, resume, or reset state."""
    actual_profile = read_private_json(config, 16384)
    actual_state = read_private_json(state_path, 32768)
    if complete:
        receipt = read_private_json(receipt_path, 131072)
        validate_migration_receipt(receipt, boot_id)
    else:
        if receipt_path.exists():
            raise ValueError("migration-receipt-exists")
        new_profile, new_state = migration_candidate(actual_profile, actual_state, boot_id)
        receipt = dict(
            version=1,
            action="enable-core-writer",
            phase="prepared",
            host_boot_id=boot_id,
            old_profile=actual_profile,
            old_state=actual_state,
            new_profile=new_profile,
            new_state=new_state,
        )
        receipt["hashes"] = {
            name: profile_digest(receipt[name])
            for name in ("old_profile", "old_state", "new_profile", "new_state")
        }
        atomic_state(receipt_path, receipt)
    if actual_profile not in (
        receipt["old_profile"],
        receipt["new_profile"],
    ) or actual_state not in (receipt["old_state"], receipt["new_state"]):
        raise ValueError("migration-pair-changed")
    if receipt["phase"] == "committed":
        if actual_profile != receipt["new_profile"] or actual_state != receipt["new_state"]:
            raise ValueError("migration-committed-pair")
        return actual_state
    atomic_state(state_path, receipt["new_state"])
    atomic_state(config, receipt["new_profile"])
    if (
        read_private_json(state_path, 32768) != receipt["new_state"]
        or read_private_json(config, 16384) != receipt["new_profile"]
    ):
        raise ValueError("migration-write-mismatch")
    receipt["phase"] = "committed"
    atomic_state(receipt_path, receipt)
    return receipt["new_state"]


def one(action):
    if os.geteuid() != 0:
        raise ValueError("root-required")
    trusted(DIRECTORY, directory=True)
    boot_id = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    descriptor = os.open(DIRECTORY / "lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {"mode": "busy"}
        path = DIRECTORY / "state.json"
        receipt_path = DIRECTORY / "core-writer-migration.json"
        receipt = None
        if action in {"enable-core-writer", "complete-core-writer-migration"}:
            profile = validate_profile(read_private_json(CONFIG, 16384))
            QgaBackend(profile).verify_profile()
            state = migrate_files(
                CONFIG,
                path,
                receipt_path,
                boot_id,
                complete=action == "complete-core-writer-migration",
            )
            return {
                "mode": "hold",
                "reason": state["reason"],
                "pending_probe": False,
                "pending_lease": False,
            }
        if receipt_path.exists():
            receipt = read_private_json(receipt_path, 131072)
            validate_migration_receipt(receipt, boot_id)
            if receipt["phase"] != "committed":
                if action == "status":
                    return {"mode": "hold", "reason": "migration-pending"}
                raise ValueError("migration-pending")
        profile = validate_profile(read_private_json(CONFIG, 16384))
        if (
            (profile["version"] == 2 and receipt is None)
            or receipt is not None
            and profile != receipt["new_profile"]
        ):
            raise ValueError("migration-profile-required")
        digest = profile_digest(profile)
        if path.exists():
            if trusted(path).st_size > 32768:
                raise ValueError("state-size")
            state = validate_state(strict_json(path.read_text()), boot_id, digest)
        else:
            if profile["version"] == 2:
                raise ValueError("writer-state-missing")
            state = new_state(boot_id, digest)
        if state["version"] != profile["version"]:
            raise ValueError("state-profile-version")
        if receipt is not None and state["sequence"] < receipt["new_state"]["sequence"]:
            raise ValueError("migration-sequence-rewind")

        def persist():
            atomic_state(path, state)

        def uptime():
            return time.clock_gettime(time.CLOCK_BOOTTIME)

        controller_type = WriterController if profile["version"] == 2 else Controller
        controller = controller_type(state, QgaBackend(profile), uptime, time.time, persist)
        if action in {"arm", "resume", "hold"}:
            controller.request(action)
        if action == "reconcile-lease":
            controller.reconcile_lease(
                lambda receipt: atomic_state(DIRECTORY / "lease-reconciliation.json", receipt)
            )
        elif action != "status":
            controller.tick()
        return {
            "mode": state["mode"],
            "reason": state["reason"],
            "pending_probe": state["probe"] is not None,
            "pending_lease": state["lease"] is not None,
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action",
        choices=[
            "arm",
            "resume",
            "hold",
            "tick",
            "watch",
            "status",
            "reconcile-lease",
            "enable-core-writer",
            "complete-core-writer-migration",
        ],
    )
    parser.add_argument("--seconds", type=int, default=58)
    args = parser.parse_args()
    if not 1 <= args.seconds <= 58:
        parser.error("seconds must be between 1 and 58")
    until = time.monotonic() + args.seconds
    while True:
        try:
            result = one("tick" if args.action == "watch" else args.action)
        except (OSError, ValueError, RuntimeError, KeyError, TypeError, subprocess.SubprocessError):
            print(json.dumps({"mode": "hold", "reason": "supervisor-review-required"}))
            return 1
        print(json.dumps(result), flush=True)
        if (
            args.action
            in {
                "arm",
                "resume",
                "hold",
                "reconcile-lease",
                "enable-core-writer",
                "complete-core-writer-migration",
            }
            and result.get("mode") == "busy"
        ):
            return 75
        if args.action != "watch" or time.monotonic() + 2 >= until:
            return 0
        time.sleep(2)


if __name__ == "__main__":
    raise SystemExit(main())
