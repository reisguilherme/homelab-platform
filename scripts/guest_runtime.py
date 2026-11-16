#!/usr/bin/env python3
"""Root-owned QGA helper. A fixed local catalog selects existing containers only.

Install as /usr/local/libexec/homelab-runtime.py with root-owned mode 0755;
catalog /etc/homelab-runtime.json is root-owned 0600. No daemon or shell API.
"""

import fcntl
import hashlib
import json
import os
import re
import socket
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

CONFIG = Path("/etc/homelab-runtime.json")


class Refused(Exception):
    pass


def run(args, timeout=8):
    result = subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=True)
    if len(result.stdout) > 8 * 1024 * 1024:
        raise Refused("action_failed")
    return result.stdout


def trusted_json(path):
    info = path.lstat()
    if path.is_symlink() or info.st_uid != 0 or info.st_mode & 0o022:
        raise Refused("maintenance_guard")
    return json.loads(path.read_text())


def inspect():
    ids = run(["/usr/bin/docker", "ps", "-aq", "--no-trunc"]).split()
    if not ids:
        return []
    if len(ids) > 100 or any(not re.fullmatch(r"[a-f0-9]{64}", value) for value in ids):
        raise Refused("action_failed")
    return json.loads(run(["/usr/bin/docker", "inspect", *ids]))


def matches(spec, containers):
    return [
        item
        for item in containers
        if item.get("Config", {}).get("Labels", {}).get("com.docker.compose.project")
        == spec["project"]
        and item.get("Config", {}).get("Labels", {}).get("com.docker.compose.service")
        == spec["service"]
    ]


def working_memory(pid):
    try:
        if type(pid) is not int or pid <= 0:
            return None
        group = next(
            line[3:]
            for line in Path(f"/proc/{pid}/cgroup").read_text().splitlines()
            if line.startswith("0::")
        )
        root = Path("/sys/fs/cgroup").resolve()
        folder = (root / group.lstrip("/")).resolve()
        if not folder.is_relative_to(root):
            return None
        used = int((folder / "memory.current").read_text())
        stats = dict(line.split() for line in (folder / "memory.stat").read_text().splitlines())
        return max(0, used - int(stats.get("inactive_file", 0)))
    except (OSError, ValueError, StopIteration):
        return None


def native_child_running(spec, item):
    """Read an existing guard's direct child; never execute the catalog command."""
    expected = spec.get("nativeCommand")
    if expected is None:
        return True
    if (
        not isinstance(expected, list)
        or not expected
        or not all(isinstance(part, str) and part and "\x00" not in part for part in expected)
    ):
        return False
    pid = item.get("State", {}).get("Pid")
    if type(pid) is not int or pid <= 0:
        return False
    try:
        children = Path(f"/proc/{pid}/task/{pid}/children").read_text().split()
        for child in children:
            if not child.isdecimal():
                continue
            try:
                command = Path(f"/proc/{child}/cmdline").read_bytes().rstrip(b"\x00").split(b"\x00")
                if command == [part.encode() for part in expected]:
                    return True
            except OSError:
                continue
    except OSError:
        pass
    return False


def describe(spec, containers):
    found = matches(spec, containers)
    dto = {
        "id": spec["id"],
        "label": spec.get("label", spec["id"]),
        "project": spec["project"],
        "state": "unknown",
        "health": "unknown",
        "image": None,
        "memoryBytes": None,
        "revision": None,
        "actions": [],
        "reason": None,
        "url": spec.get("url"),
        "readiness": "unconfirmed",
    }
    if len(found) != 1:
        dto["reason"] = (
            "Container ausente" if not found else "Mais de um container com a mesma identidade"
        )
        return dto
    item = found[0]
    state = item.get("State", {})
    dto.update(
        state=state.get("Status", "unknown"),
        health=state.get("Health", {}).get("Status", "not_configured"),
        image=item.get("Config", {}).get("Image"),
        memoryBytes=working_memory(state.get("Pid")),
    )
    if dto["state"] == "running" and native_child_running(spec, item):
        if dto["health"] == "healthy":
            dto["readiness"] = "healthcheck"
        elif dto["health"] == "not_configured":
            dto["readiness"] = "process_only"
    revision = [
        item["Id"],
        dto["state"],
        state.get("StartedAt"),
        state.get("FinishedAt"),
        item.get("RestartCount"),
        spec,
    ]
    dto["revision"] = hashlib.sha256(json.dumps(revision, sort_keys=True).encode()).hexdigest()
    if spec.get("protected"):
        dto["reason"] = spec["protected"]
    elif dto["state"] == "running":
        dto["actions"] = ["stop", "restart"]
    elif dto["state"] in ("exited", "created"):
        dto["actions"] = ["start"]
    return dto


def check_mounts(config):
    mounts = list(config.get("mounts", []))
    if config.get("storageGuard"):
        guard = trusted_json(Path("/etc/homelab-storage.json"))
        mounts.append(
            {
                "path": "/srv/external3",
                "filesystem": "ext4",
                "uuid": guard["filesystem_uuid"],
                "mode": "rw",
            }
        )
    for expected in mounts:
        try:
            actual = json.loads(
                run(
                    [
                        "/usr/bin/findmnt",
                        "--json",
                        "--mountpoint",
                        expected["path"],
                        "--output",
                        "TARGET,SOURCE,FSTYPE,UUID,OPTIONS",
                    ]
                )
            )["filesystems"]
            if len(actual) != 1:
                raise ValueError()
            mount = actual[0]
            valid = (
                mount["target"] == expected["path"] and mount["fstype"] == expected["filesystem"]
            )
            valid = valid and expected["mode"] in mount["options"].split(",")
            for key in ("uuid", "source"):
                if key in expected:
                    valid = valid and mount.get(key) == expected[key]
            if not valid:
                raise ValueError()
        except (ValueError, KeyError, subprocess.SubprocessError, OSError):
            raise Refused("storage_unavailable") from None


def action(config, verb, identifier, revision):
    if verb not in ("start", "stop", "restart") or not re.fullmatch(
        r"[a-z][a-z0-9-]{0,62}", identifier
    ):
        raise Refused("action_failed")
    found = [spec for spec in config["services"] if spec["id"] == identifier]
    if len(found) != 1:
        raise Refused("service_protected")
    spec = found[0]
    containers = inspect()
    before = describe(spec, containers)
    if before["revision"] != revision:
        raise Refused("state_changed")
    if verb not in before["actions"]:
        raise Refused("service_protected")
    if verb in ("start", "restart"):
        check_mounts(config)
    selected = matches(spec, containers)[0]["Id"]
    run(
        [
            "/usr/bin/docker",
            verb,
            *(["--time", "20"] if verb in ("stop", "restart") else []),
            selected,
        ],
        timeout=40,
    )
    deadline = time.monotonic() + 40
    while True:
        containers = inspect()
        found = matches(spec, containers)
        if len(found) != 1 or found[0]["Id"] != selected:
            raise Refused("state_changed")
        after = describe(spec, containers)
        if verb == "stop":
            if after["state"] not in ("exited", "created"):
                raise Refused("action_failed")
            return {
                "ok": True,
                "service": identifier,
                "state": after["state"],
                "readiness": "stopped",
            }
        if after["state"] != "running" or after["health"] == "unhealthy":
            raise Refused("action_failed")
        if after["readiness"] != "unconfirmed":
            return {
                "ok": True,
                "service": identifier,
                "state": after["state"],
                "readiness": after["readiness"],
            }
        if time.monotonic() >= deadline:
            raise Refused("readiness_unconfirmed")
        time.sleep(1)


def snapshot(config):
    containers = inspect()
    mem = dict(
        (parts[0].rstrip(":"), int(parts[1]) * 1024)
        for line in Path("/proc/meminfo").read_text().splitlines()
        if len(parts := line.split()) >= 2
    )
    return {
        "sourceState": "fresh",
        "collectedAt": datetime.now(UTC).isoformat(),
        "memory": {"totalBytes": mem["MemTotal"], "availableBytes": mem["MemAvailable"]},
        "items": [describe(spec, containers) for spec in config["services"]],
    }


def main():
    try:
        config = trusted_json(CONFIG)
        if (
            os.geteuid() != 0
            or config.get("hostname") != socket.gethostname()
            or len(config["services"]) > 100
        ):
            raise Refused("maintenance_guard")
        with open("/run/lock/homelab-runtime.lock", "a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if sys.argv[1:] == ["list"]:
                result = snapshot(config)
            elif len(sys.argv) == 4:
                result = action(config, *sys.argv[1:])
            else:
                raise Refused("action_failed")
        print(json.dumps(result))
    except Refused as error:
        print(json.dumps({"ok": False, "error": str(error)}))
        return 1
    except Exception:
        # Never echo subprocess stderr, paths, environment or Docker configuration.
        print(json.dumps({"ok": False, "error": "action_failed"}))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
