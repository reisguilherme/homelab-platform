"""Bounded physical disk observations. Standalone guest mode writes exporter textfiles.

No mounting, repairs, media scans, self-tests or device configuration. Host PVE
SMART is deliberately skipped; guest ATA queries exit on standby/unknown power.
"""

import argparse
import ipaddress
import json
import math
import os
import re
import subprocess
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, build_opener

MAX_BODY = 1024 * 1024
MAX_DISKS = 64
MAX_PARTITIONS = 256
PROBE_STALE_AFTER = 150
DEVICE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
LABEL = re.compile(r'([a-z_]+)=("(?:[^"\\]|\\[\\n"])*")(?:,|$)')
KINDS = {"hdd", "ssd", "nvme", "unknown"}
HEALTH = {"passed", "failed", "unknown"}


def identity(value):
    if not isinstance(value, str) or not DEVICE.fullmatch(value):
        raise ValueError("invalid device identity")
    return value


def clean_text(value, maximum=128):
    if not isinstance(value, str) or len(value) > maximum or any(ord(c) < 32 for c in value):
        raise ValueError("invalid display text")
    return value


def numeric(value):
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise ValueError("invalid measurement")
    return value


def device_path(value):
    if not isinstance(value, str) or not value.startswith("/dev/"):
        raise ValueError("invalid device path")
    return identity(value[5:])


def iso(timestamp):
    return datetime.fromtimestamp(timestamp, UTC).isoformat().replace("+00:00", "Z")


def metric(name, labels, value):
    suffix = (
        "{"
        + ",".join(
            f"{key}={json.dumps(str(value), ensure_ascii=False)}" for key, value in labels.items()
        )
        + "}"
    )
    return f"homelab_storage_{name}{suffix if labels else ''} {numeric(value)}\n"


def pve_disks(node, rows):
    identity(node)
    if not isinstance(rows, list) or len(rows) > MAX_PARTITIONS:
        raise ValueError("invalid disks")
    disks, seen = {}, set()
    for row in rows:
        device = device_path(row["devpath"])
        if device in seen:
            raise ValueError("duplicate device")
        seen.add(device)
        if row.get("type") == "partition":
            continue
        kind = row.get("type", "unknown")
        disks[row["devpath"]] = {
            "id": f"pve:{node}:{device}",
            "scope": "pve",
            "node": node,
            "owner": "host",
            "device": device,
            "model": clean_text(row.get("model", "")),
            "kind": kind if kind in KINDS else "unknown",
            "capacityBytes": numeric(row["size"]),
            "health": "unknown",
            "healthReason": "not_polled_to_avoid_wakeup",
            "readOnly": None,
            "mounted": row.get("mounted") == 1,
            "mounts": [],
            "partitions": [],
        }
    if len(disks) > MAX_DISKS:
        raise ValueError("too many disks")
    for row in rows:
        target = disks.get(row.get("parent")) if row.get("type") == "partition" else None
        if target is not None:
            target["partitions"].append(
                {
                    "device": device_path(row["devpath"]),
                    "capacityBytes": numeric(row["size"]),
                    "filesystem": clean_text("" if row.get("used") is None else row["used"]),
                    "mounted": row.get("mounted") == 1,
                }
            )
            target["mounted"] |= row.get("mounted") == 1
    return list(disks.values())


def flatten(rows):
    result = []
    pending = list(rows)
    while pending:
        row = pending.pop(0)
        if not isinstance(row, dict) or len(result) >= MAX_PARTITIONS:
            raise ValueError("invalid device tree")
        result.append(row)
        pending.extend(row.get("children", []))
    return result


def physical_disks(block):
    rows = block.get("blockdevices")
    if not isinstance(rows, list) or len(rows) > MAX_DISKS:
        raise ValueError("invalid block devices")
    return [
        row
        for row in rows
        if row.get("type") == "disk"
        and row.get("tran") in ("usb", "nvme", "sata", "ata")
        and not str(row.get("model", "")).upper().startswith(("QEMU", "VBOX", "VIRTUAL"))
    ]


def probe_metrics(block, mounts, health, now):
    filesystems = flatten(mounts["filesystems"])
    lines = [metric("probe_up", {}, 1), metric("probe_timestamp_seconds", {}, numeric(now))]
    for disk in physical_disks(block):
        device = device_path(disk["path"])
        children = flatten([disk])
        paths = {child["path"]: child for child in children}
        matched = [mount for mount in filesystems if mount.get("source") in paths]
        kind = "nvme" if disk.get("tran") == "nvme" else "hdd" if disk.get("rota") else "ssd"
        state = health.get(device, "unknown")
        if state not in HEALTH or type(disk.get("ro")) is not bool:
            raise ValueError("invalid disk status")
        labels = {
            "device": device,
            "model": clean_text(disk.get("model") or ""),
            "kind": kind,
            "health": state,
            "readonly": str(disk["ro"]).lower(),
            "mounted": str(bool(matched)).lower(),
        }
        lines.append(metric("probe_disk_bytes", labels, numeric(disk["size"])))
        for mount in matched:
            options = set(mount["options"].split(","))
            if len(options & {"ro", "rw"}) != 1:
                raise ValueError("unknown mount mode")
            labels = {
                "disk": device,
                "device": device_path(mount["source"]),
                "mountpoint": clean_text(mount["target"], 512),
                "filesystem": clean_text(mount["fstype"], 32),
                "readonly": str("ro" in options).lower(),
            }
            for source, suffix in (("size", "size"), ("used", "used"), ("avail", "available")):
                lines.append(
                    metric(f"probe_filesystem_{suffix}_bytes", labels, numeric(mount[source]))
                )
    return "".join(lines)


def parse_labels(raw):
    labels, position = {}, 0
    while position < len(raw):
        match = LABEL.match(raw, position)
        if not match or match[1] in labels:
            raise ValueError("invalid metric labels")
        labels[match[1]] = clean_text(json.loads(match[2]), 512)
        position = match.end()
    return labels


def parse_probe(text, *, node, vmid, now):
    if not isinstance(text, str) or len(text.encode()) > MAX_BODY:
        raise ValueError("probe body limit")
    identity(node)
    if type(vmid) is not int or not 1 <= vmid <= 999999999:
        raise ValueError("invalid VM")
    samples, seen = [], set()
    for line in text.splitlines():
        if not line.startswith("homelab_storage_probe_"):
            continue
        match = re.fullmatch(r"homelab_storage_probe_([a-z_]+)(?:\{(.*)\})? ([0-9.eE+-]+)", line)
        if not match or len(samples) >= 1024:
            raise ValueError("invalid probe metrics")
        labels = parse_labels(match[2] or "")
        key = (match[1], tuple(sorted(labels.items())))
        if key in seen:
            raise ValueError("duplicate probe metric")
        seen.add(key)
        samples.append((match[1], labels, numeric(float(match[3]))))
    globals_ = {key: value for key, labels, value in samples if not labels}
    timestamp = globals_.get("timestamp_seconds", 0)
    if globals_.get("up") != 1 or not 0 <= now - timestamp <= PROBE_STALE_AFTER:
        raise ValueError("probe unavailable or stale")
    disks, mounts = {}, {}
    for key, labels, value in samples:
        if key == "disk_bytes":
            if set(labels) != {"device", "model", "kind", "health", "readonly", "mounted"}:
                raise ValueError("invalid disk labels")
            device = identity(labels["device"])
            if device in disks or labels["kind"] not in KINDS or labels["health"] not in HEALTH:
                raise ValueError("invalid disk")
            if any(labels[field] not in ("true", "false") for field in ("readonly", "mounted")):
                raise ValueError("invalid boolean")
            disks[device] = {
                "id": f"core:{node}:{device}",
                "scope": "core",
                "node": node,
                "owner": f"vm-{vmid}",
                "device": device,
                "model": clean_text(labels["model"]),
                "kind": labels["kind"],
                "capacityBytes": value,
                "health": labels["health"],
                "healthReason": "smart_no_wakeup"
                if labels["health"] != "unknown"
                else "standby_unsupported_or_unavailable",
                "readOnly": labels["readonly"] == "true",
                "mounted": labels["mounted"] == "true",
                "mounts": [],
                "partitions": [],
            }
        elif key in (
            "filesystem_size_bytes",
            "filesystem_used_bytes",
            "filesystem_available_bytes",
        ):
            if set(labels) != {"disk", "device", "mountpoint", "filesystem", "readonly"}:
                raise ValueError("invalid filesystem labels")
            identity(labels["disk"])
            identity(labels["device"])
            if labels["readonly"] not in ("true", "false") or not labels["mountpoint"].startswith(
                "/"
            ):
                raise ValueError("invalid mount")
            mount_key = tuple(sorted(labels.items()))
            mount = mounts.setdefault(
                mount_key,
                {
                    "device": labels["device"],
                    "path": labels["mountpoint"],
                    "filesystem": labels["filesystem"],
                    "readOnly": labels["readonly"] == "true",
                },
            )
            field = {
                "filesystem_size_bytes": "sizeBytes",
                "filesystem_used_bytes": "usedBytes",
                "filesystem_available_bytes": "availableBytes",
            }[key]
            mount[field] = value
    if len(disks) > MAX_DISKS:
        raise ValueError("too many disks")
    for key, mount in mounts.items():
        disk = dict(key)["disk"]
        if disk not in disks or not {"sizeBytes", "usedBytes", "availableBytes"} <= mount.keys():
            raise ValueError("incomplete mount")
        if mount["usedBytes"] > mount["sizeBytes"] or mount["availableBytes"] > mount["sizeBytes"]:
            raise ValueError("invalid filesystem capacity")
        disks[disk]["mounts"].append(mount)
    return {"timestamp": timestamp, "disks": list(disks.values())}


def inventory_metrics(disks):
    lines = []
    for disk in disks:
        base = {key: disk[key] for key in ("scope", "node", "device")}
        labels = {**base, **{key: disk[key] for key in ("owner", "kind", "model")}}
        lines.append(metric("disk_capacity_bytes", labels, disk["capacityBytes"]))
        lines.append(metric("disk_health", {**base, "state": disk["health"]}, 1))
        lines.append(metric("disk_mounted", base, int(disk["mounted"])))
        if disk["readOnly"] is not None:
            lines.append(metric("disk_readonly", base, int(disk["readOnly"])))
        for mount in disk["mounts"]:
            labels = {
                "scope": disk["scope"],
                "node": disk["node"],
                "disk": disk["device"],
                "device": mount["device"],
                "mountpoint": mount["path"],
                "filesystem": mount["filesystem"],
                "readonly": str(mount["readOnly"]).lower(),
            }
            for field, suffix in (
                ("sizeBytes", "size"),
                ("usedBytes", "used"),
                ("availableBytes", "available"),
            ):
                lines.append(metric(f"filesystem_{suffix}_bytes", labels, mount[field]))
    return "".join(lines)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, newurl):
        raise HTTPError("redacted", code, "redirect refused", {}, None)


class ExporterClient:
    def __init__(self, url):
        parsed = urlsplit(url)
        address = ipaddress.ip_address(parsed.hostname or "")
        allowed = any(
            address in ipaddress.ip_network(network)
            for network in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
        )
        if (
            not allowed
            or parsed.scheme != "http"
            or parsed.port != 9100
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path != "/metrics"
        ):
            raise ValueError("invalid private exporter URL")
        self.url = url
        self.opener = build_opener(ProxyHandler({}), NoRedirect())

    def get(self):
        with self.opener.open(self.url, timeout=5) as response:
            body = response.read(MAX_BODY + 1)
        if len(body) > MAX_BODY:
            raise ValueError("exporter response too large")
        return body.decode("utf-8")


def command_json(args):
    result = subprocess.run(args, capture_output=True, timeout=8, check=False)
    if len(result.stdout) > MAX_BODY:
        raise ValueError("command response too large")
    return result.returncode, json.loads(result.stdout)


def observe_guest(now):
    started = time.monotonic()
    code, block = command_json(
        [
            "lsblk",
            "--json",
            "--bytes",
            "--tree",
            "-o",
            "NAME,PATH,TYPE,SIZE,MODEL,TRAN,RO,FSTYPE,MOUNTPOINTS,ROTA",
        ]
    )
    if code:
        raise ValueError("block inventory unavailable")
    code, mounts = command_json(
        [
            "findmnt",
            "--json",
            "--bytes",
            "--real",
            "-o",
            "SOURCE,TARGET,FSTYPE,OPTIONS,SIZE,USED,AVAIL",
        ]
    )
    if code:
        raise ValueError("mount inventory unavailable")
    health = {}
    for disk in physical_disks(block):
        device = device_path(disk["path"])
        health[device] = "unknown"
        # ATA only: STATUS2 prevents smartctl continuing when power mode is unknown.
        # Explicit transport avoids auto-detection waking an unsupported USB bridge.
        transport = "sat,12" if disk.get("tran") == "usb" else "ata"
        if disk.get("tran") not in ("usb", "ata", "sata"):
            continue
        if time.monotonic() - started >= 18:
            continue
        try:
            code, result = command_json(
                ["smartctl", "-d", transport, "-n", "standby,3,5", "-H", "-j", disk["path"]]
            )
            passed = result.get("smart_status", {}).get("passed")
            if not code & 3 and type(passed) is bool:
                health[device] = "passed" if passed else "failed"
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
    return probe_metrics(block, mounts, health, now)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    now = time.time()
    try:
        text = observe_guest(now)
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        text = metric("probe_up", {}, 0) + metric("probe_timestamp_seconds", {}, now)
    descriptor, temporary = tempfile.mkstemp(prefix=".storage-", dir=args.output.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            os.fchmod(stream.fileno(), 0o644)
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, args.output)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


if __name__ == "__main__":
    main()
