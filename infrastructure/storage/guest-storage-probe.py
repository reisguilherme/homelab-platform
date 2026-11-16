#!/usr/bin/env python3
"""Fixed QGA operations: observe the hub or publish short admission on guest SSD.

Never mounts, repairs, formats, starts applications or writes to the media disk.
An I/O probe may remain stuck in the kernel; the external supervisor owns timeouts.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import math
import mmap
import os
import re
import signal
import stat
import subprocess
import tempfile
import time
from pathlib import Path

CONFIG = Path("/etc/homelab-storage.json")
STATE = Path("/var/lib/homelab-storage")
PROC = Path("/proc")
MOUNT = Path("/srv/external3")
FIXTURE = MOUNT / ".homelab-storage/health.bin"
UUID = r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}"
GENERATION = r"[0-9a-f]{32}"


def strict_json(text):
    def pairs(rows):
        result = {}
        for key, value in rows:
            if key in result:
                raise ValueError("duplicate-json-key")
            result[key] = value
        return result

    return json.loads(
        text,
        object_pairs_hook=pairs,
        parse_constant=lambda _: (_ for _ in ()).throw(ValueError("json-number")),
    )


def trusted(path, *, directory=False, private=False):
    for parent in reversed(path.parents):
        info = parent.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise ValueError("unsafe-parent")
    info = path.lstat()
    valid_type = stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)
    if (
        not valid_type
        or info.st_uid != 0
        or info.st_mode & 0o022
        or (not directory and info.st_nlink != 1)
        or (private and info.st_mode & 0o077)
    ):
        raise ValueError("unsafe-file")
    return info


def read_profile():
    info = trusted(CONFIG, private=True)
    if info.st_size > 16384:
        raise ValueError("profile-size")
    result = strict_json(CONFIG.read_text())
    base = {"version", "role"}
    core = {
        "filesystem_uuid",
        "bridge_serial",
        "ata_serial",
        "disk_size_bytes",
        "partition_size_bytes",
        "partition_number",
        "fixture_sha256",
        "smart_device_type",
    }
    if not isinstance(result, dict) or result.get("version") != 1:
        raise ValueError("profile-version")
    if result.get("role") == "playback" and set(result) == base:
        return result
    if result.get("role") != "core" or set(result) != base | core:
        raise ValueError("profile-role")
    if not re.fullmatch(UUID, result["filesystem_uuid"]):
        raise ValueError("profile-uuid")
    for key in ("bridge_serial", "ata_serial"):
        if not isinstance(result[key], str) or not re.fullmatch(r"[\w .:-]{1,128}", result[key]):
            raise ValueError("profile-serial")
    for key in ("disk_size_bytes", "partition_size_bytes", "partition_number"):
        if type(result[key]) is not int or result[key] < 1:
            raise ValueError("profile-dimension")
    if not re.fullmatch(r"[0-9a-f]{64}", result["fixture_sha256"]):
        raise ValueError("profile-hash")
    if result["smart_device_type"] not in {"sat,12", "sat,16"}:
        raise ValueError("profile-smart-transport")
    return result


def atomic(path, data, mode):
    fd, name = tempfile.mkstemp(prefix=".storage-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            os.fchmod(stream.fileno(), mode)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
        descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def lease_expiry(state, not_after, wall_time, uptime):
    if state == "hold":
        return 0
    remaining = not_after - math.ceil(wall_time)
    if state != "ready" or not 1 <= remaining <= 45:
        raise ValueError("lease-deadline")
    return int(uptime) + remaining


def lease_text(state, boot_id, generation, expiry):
    if (
        state not in {"ready", "hold"}
        or not re.fullmatch(UUID, boot_id)
        or not re.fullmatch(GENERATION, generation)
        or type(expiry) is not int
        or expiry < 0
    ):
        raise ValueError("lease-format")
    return (
        f"version=1\nstate={state}\nboot_id={boot_id}\ngeneration={generation}\n"
        f"expires_uptime_seconds={expiry}\n"
    )


def publish_lease(
    directory, journal, state, generation, sequence, not_after, boot_id, wall_time, uptime
):
    if type(sequence) is not int or sequence < 1:
        raise ValueError("lease-sequence")
    expiry = lease_expiry(state, not_after, wall_time, uptime)
    value = lease_text(state, boot_id, generation, expiry)
    if journal.exists():
        trusted(journal, private=True)
        prior = strict_json(journal.read_text())
        if (
            set(prior) != {"version", "sequence"}
            or prior["version"] != 1
            or type(prior["sequence"]) is not int
            or sequence <= prior["sequence"]
        ):
            raise ValueError("lease-sequence")
    # Persist the sequence first: an interrupted write cannot permit a replay.
    atomic(journal, json.dumps({"version": 1, "sequence": sequence}).encode(), 0o600)
    atomic(directory / "lease", value.encode("ascii"), 0o644)
    return {
        "version": 1,
        "written": True,
        "sequence": sequence,
        "generation": generation,
        "state": state,
    }


def open_trusted_readonly(path, *, private=False):
    before = trusted(path, private=private)
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    opened = os.fstat(descriptor)
    if not stat.S_ISREG(opened.st_mode) or (
        before.st_dev,
        before.st_ino,
        before.st_mode,
        before.st_uid,
        before.st_nlink,
    ) != (opened.st_dev, opened.st_ino, opened.st_mode, opened.st_uid, opened.st_nlink):
        os.close(descriptor)
        raise ValueError("reconciliation-file-changed")
    return descriptor


def read_bounded(path, *, private=False):
    with os.fdopen(open_trusted_readonly(path, private=private), "rb") as stream:
        if os.fstat(stream.fileno()).st_size > 4096:
            raise ValueError("reconciliation-file-size")
        value = stream.read(4097)
    if len(value) > 4096:
        raise ValueError("reconciliation-file-size")
    return value


def reconcile_lease(profile, pid, sequence, generation, state):
    """Observe only SSD/proc state under the existing publication lock; never publish."""
    if (
        profile != {"version": 1, "role": "playback"}
        or type(pid) is not int
        or not 1 <= pid <= 2**31 - 1
        or type(sequence) is not int
        or not 1 <= sequence <= 2**63 - 1
        or not isinstance(generation, str)
        or not re.fullmatch(GENERATION, generation)
        or state not in {"ready", "hold"}
    ):
        raise ValueError("reconciliation-arguments")
    trusted(STATE, directory=True)
    trusted(STATE / "admission", directory=True)
    with os.fdopen(open_trusted_readonly(STATE / "lease.lock", private=True), "rb") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            (PROC / str(pid)).lstat()
        except FileNotFoundError:
            pass
        else:
            raise ValueError("reconciliation-pid-present")
        # Kernel pseudo-files are fixed paths, bounded independently of file size.
        with (PROC / "sys/kernel/random/boot_id").open("rb") as stream:
            boot = stream.read(4097).decode("ascii").strip()
        with (PROC / "uptime").open("rb") as stream:
            uptime_text = stream.read(4097).decode("ascii")
        if not re.fullmatch(UUID, boot) or not re.fullmatch(
            r"[0-9]{1,16}(?:\.[0-9]+)? [0-9]{1,20}(?:\.[0-9]+)?\n?", uptime_text
        ):
            raise ValueError("reconciliation-boot-time")
        uptime = int(float(uptime_text.split()[0]))
        journal_bytes = read_bounded(STATE / "lease-state.json", private=True)
        journal = strict_json(journal_bytes)
        if (
            not isinstance(journal, dict)
            or set(journal) != {"version", "sequence"}
            or type(journal["version"]) is not int
            or journal["version"] != 1
            or type(journal["sequence"]) is not int
            or journal["sequence"] != sequence
        ):
            raise ValueError("reconciliation-journal")
        lease_bytes = read_bounded(STATE / "admission/lease")
        match = re.fullmatch(
            rf"version=1\nstate=(ready|hold)\nboot_id=({UUID})\ngeneration=({GENERATION})\n"
            r"expires_uptime_seconds=(0|[1-9][0-9]{0,15})\n",
            lease_bytes.decode("ascii"),
        )
        if match is None or match.group(1, 2, 3) != (state, boot, generation):
            raise ValueError("reconciliation-lease")
        expiry = int(match.group(4))
        if (
            expiry > uptime
            or (state == "hold" and expiry != 0)
            or (state == "ready" and expiry == 0)
        ):
            raise ValueError("reconciliation-expiry")
        return {
            "version": 1,
            "reconciled": True,
            "pid": pid,
            "sequence": sequence,
            "generation": generation,
            "state": state,
            "boot_id": boot,
            "expires_uptime_seconds": expiry,
            "observed_uptime_seconds": uptime,
            "lease_sha256": hashlib.sha256(lease_bytes).hexdigest(),
            "journal_sha256": hashlib.sha256(journal_bytes).hexdigest(),
        }


def mount_identity(text, device):
    matches = []
    for line in text.splitlines():
        fields = line.split()
        if len(fields) < 10:
            raise ValueError("mount-format")
        if fields[4].startswith(str(MOUNT) + "/"):
            raise ValueError("nested-mount")
        if fields[4] != str(MOUNT):
            continue
        separator = fields.index("-")
        options = fields[5].split(",")
        super_options = fields[separator + 3].split(",")
        if (
            fields[2] != device
            or fields[3] != "/"
            or "rw" not in options
            or "ro" in options
            or "rw" not in super_options
            or "ro" in super_options
            or fields[separator + 1] != "ext4"
        ):
            raise ValueError("mount-identity")
        matches.append(fields[0])
    if len(matches) != 1:
        raise ValueError("mount-count")
    return matches[0]


def run_json(argv):
    result = subprocess.run(argv, capture_output=True, text=True, timeout=8, check=False)
    if result.returncode or len(result.stdout) > 262144:
        raise ValueError("device-command")
    return strict_json(result.stdout)


def select_device(data, profile):
    rows = []

    def walk(items, disk=None):
        for item in items:
            parent = item if item.get("type") == "disk" else disk
            rows.append((item, parent))
            walk(item.get("children", []), parent)

    walk(data["blockdevices"])
    matches = [
        (part, disk) for part, disk in rows if part.get("uuid") == profile["filesystem_uuid"]
    ]
    if len(matches) != 1:
        raise ValueError("device-count")
    part, disk = matches[0]
    if (
        disk is None
        or part.get("type") != "part"
        or part.get("fstype") != "ext4"
        or part.get("ro") not in (False, 0)
        or disk.get("ro") not in (False, 0)
        or int(part["size"]) != profile["partition_size_bytes"]
        or int(disk["size"]) != profile["disk_size_bytes"]
        or disk.get("serial") != profile["bridge_serial"]
        or not re.fullmatch(r"/dev/sd[a-z]+[0-9]+", part["path"])
        or not re.fullmatch(r"/dev/sd[a-z]+", disk["path"])
    ):
        raise ValueError("device-identity")
    return part, disk


def generation(part, disk, boot_id):
    sys_part = Path("/sys/class/block") / Path(part["path"]).name
    sys_disk = Path("/sys/class/block") / Path(disk["path"]).name
    resolved = sys_disk.resolve(strict=True)
    usb = next(
        (
            parent
            for parent in (resolved, *resolved.parents)
            if (parent / "devnum").is_file() and (parent / "busnum").is_file()
        ),
        None,
    )
    if usb is None or (sys_disk / "device/state").read_text().strip() != "running":
        raise ValueError("usb-unavailable")
    tokens = [
        boot_id,
        str(resolved),
        (usb / "devnum").read_text().strip(),
        (usb / "busnum").read_text().strip(),
        (sys_disk / "diskseq").read_text().strip(),
        part["maj:min"],
        (sys_part / "partition").read_text().strip(),
    ]
    return hashlib.sha256("|".join(tokens).encode()).hexdigest()


def direct_hash(path, expected_device):
    info = trusted(path)
    if info.st_size != 65536 or info.st_dev != expected_device:
        raise ValueError("fixture-identity")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_DIRECT | os.O_NOATIME)
    try:
        opened = os.fstat(descriptor)
        if (opened.st_dev, opened.st_ino, opened.st_size) != (
            info.st_dev,
            info.st_ino,
            info.st_size,
        ):
            raise ValueError("fixture-changed")
        with mmap.mmap(-1, 65536) as buffer:
            if os.readv(descriptor, [buffer]) != 65536:
                raise ValueError("fixture-short-read")
            return hashlib.sha256(buffer).hexdigest()
    finally:
        os.close(descriptor)


def block_inventory():
    return run_json(
        [
            "/usr/bin/lsblk",
            "--json",
            "--bytes",
            "--tree",
            "--output",
            "PATH,TYPE,UUID,FSTYPE,SERIAL,SIZE,RO,MAJ:MIN",
        ]
    )


def smart_identity(device, device_type):
    if device_type not in {"sat,12", "sat,16"}:
        raise ValueError("smart-transport")
    return run_json(["/usr/sbin/smartctl", "--device", device_type, "--info", "--json", device])


def core_probe(profile, nonce):
    boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    data = block_inventory()
    part, disk = select_device(data, profile)
    sys_part = Path("/sys/class/block") / Path(part["path"]).name
    if int((sys_part / "partition").read_text()) != profile["partition_number"]:
        raise ValueError("partition-identity")
    info = Path(part["path"]).stat()
    major, minor = map(int, part["maj:min"].split(":"))
    if not stat.S_ISBLK(info.st_mode) or info.st_rdev != os.makedev(major, minor):
        raise ValueError("block-identity")
    mounts = Path("/proc/self/mountinfo")
    mount_id = mount_identity(mounts.read_text(), part["maj:min"])
    before = generation(part, disk, boot)
    errors = Path("/sys/fs/ext4") / Path(part["path"]).name / "errors_count"
    if not errors.is_file() or int(errors.read_text()) != 0:
        raise ValueError("filesystem-errors")
    smart = smart_identity(disk["path"], profile["smart_device_type"])
    if smart.get("serial_number") != profile["ata_serial"]:
        raise ValueError("ata-identity")
    if direct_hash(FIXTURE, info.st_rdev) != profile["fixture_sha256"]:
        raise ValueError("fixture-hash")
    if (
        before != generation(part, disk, boot)
        or mount_identity(mounts.read_text(), part["maj:min"]) != mount_id
        or int(errors.read_text()) != 0
    ):
        raise ValueError("generation-changed")
    physical = hashlib.sha256(f"{before}:{mount_id}".encode()).hexdigest()
    return {
        "version": 1,
        "nonce": nonce,
        "healthy": True,
        "reason": "ok",
        "generation": physical,
        "boot_id": boot,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["probe", "lease-ready", "lease-hold", "reconcile-lease"])
    parser.add_argument("--nonce")
    parser.add_argument("--generation")
    parser.add_argument("--sequence", type=int)
    parser.add_argument("--not-after", type=int, default=0)
    parser.add_argument("--pid", type=int)
    parser.add_argument("--state", choices=["ready", "hold"])
    args = parser.parse_args()
    result = {"version": 1, "healthy": False, "reason": "probe-refused"}
    try:
        if os.geteuid() != 0:
            raise ValueError("root-required")
        if args.action == "reconcile-lease":
            # A lost QGA reply must not leave an unbounded reconciliation helper.
            signal.alarm(5)
        profile = read_profile()
        if args.action == "reconcile-lease":
            result = reconcile_lease(profile, args.pid, args.sequence, args.generation, args.state)
            print(json.dumps(result))
            return 0
        trusted(STATE, directory=True)
        lock_path = STATE / ("probe.lock" if args.action == "probe" else "lease.lock")
        fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if args.action == "probe":
                if profile["role"] != "core" or not re.fullmatch(GENERATION, args.nonce or ""):
                    raise ValueError("probe-arguments")
                result = core_probe(profile, args.nonce)
            else:
                if profile["role"] != "playback":
                    raise ValueError("lease-role")
                admission = STATE / "admission"
                trusted(admission, directory=True)
                boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
                uptime = float(Path("/proc/uptime").read_text().split()[0])
                result = publish_lease(
                    admission,
                    STATE / "lease-state.json",
                    args.action.removeprefix("lease-"),
                    args.generation or "",
                    args.sequence,
                    args.not_after,
                    boot,
                    time.time(),
                    uptime,
                )
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        print(json.dumps(result))
        return 1
    finally:
        if args.action == "reconcile-lease":
            signal.alarm(0)
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
