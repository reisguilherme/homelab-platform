#!/usr/bin/env python3
"""QGA storage containment. No remount, repair, passthrough change or app start."""

from __future__ import annotations

import argparse
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
        if self.clock() - record["started"] > LEASE_DEADLINE:
            self.hold("lease-timeout")
        if result is None:
            return
        self.state["lease"] = None
        expected = {
            "version": 1,
            "written": True,
            "sequence": record["sequence"],
            "generation": record["generation"],
            "state": record["state"],
        }
        if result != expected:
            self.hold("lease-rejected")
        elif record["state"] == "hold" and record["generation"] == self.state["generation"]:
            self.state["hold_published"] = True
            self.persist()
        elif self.state["mode"] == "armed" and record["generation"] == self.state["generation"]:
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
        if len(value) > 16384:
            return {"failed": True}
        return strict_json(value)


def validate_state(state, boot_id, profile_digest):
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


def one(action):
    if os.geteuid() != 0:
        raise ValueError("root-required")
    trusted(DIRECTORY, directory=True)
    if trusted(CONFIG).st_size > 16384:
        raise ValueError("profile-size")
    profile = validate_profile(strict_json(CONFIG.read_text()))
    digest = hashlib.sha256(json.dumps(profile, sort_keys=True).encode()).hexdigest()
    boot_id = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    descriptor = os.open(DIRECTORY / "lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {"mode": "busy"}
        path = DIRECTORY / "state.json"
        if path.exists():
            if trusted(path).st_size > 32768:
                raise ValueError("state-size")
            state = validate_state(strict_json(path.read_text()), boot_id, digest)
        else:
            state = new_state(boot_id, digest)

        def persist():
            atomic_state(path, state)

        def uptime():
            return time.clock_gettime(time.CLOCK_BOOTTIME)

        controller = Controller(state, QgaBackend(profile), uptime, time.time, persist)
        if action in {"arm", "resume", "hold"}:
            controller.request(action)
        if action != "status":
            controller.tick()
        return {
            "mode": state["mode"],
            "reason": state["reason"],
            "pending_probe": state["probe"] is not None,
            "pending_lease": state["lease"] is not None,
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["arm", "resume", "hold", "tick", "watch", "status"])
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
        if args.action in {"arm", "resume", "hold"} and result.get("mode") == "busy":
            return 75
        if args.action != "watch" or time.monotonic() + 2 >= until:
            return 0
        time.sleep(2)


if __name__ == "__main__":
    raise SystemExit(main())
