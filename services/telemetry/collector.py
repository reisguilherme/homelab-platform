"""Bounded, read-only Proxmox collection with explicit missing-data semantics."""

import json
import math
import os
import re
import ssl
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, ProxyHandler, Request, build_opener

MAX_BODY = 1024 * 1024
MAX_RESOURCES = 2048
MAX_NODES = 16
INTERVAL = 30
STALE_AFTER = 75
NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, newurl):
        raise HTTPError("redacted", code, "redirect refused", {}, None)


class PveClient:
    def __init__(self, url, token_id, token_secret, context):
        parsed = urlsplit(url)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in ("", "/", "/api2/json", "/api2/json/")
        ):
            raise ValueError("invalid upstream")
        if not context.check_hostname or context.verify_mode != ssl.CERT_REQUIRED:
            raise ValueError("TLS verification is required")
        if not re.fullmatch(r"[A-Za-z0-9_.-]+@[A-Za-z0-9_.-]+![A-Za-z0-9_.-]+", token_id):
            raise ValueError("invalid token identity")
        if not re.fullmatch(r"[!-~]{1,256}", token_secret):
            raise ValueError("invalid token secret")
        self.base = f"https://{parsed.netloc}/api2/json"
        self.authorization = f"PVEAPIToken={token_id}={token_secret}"
        self.opener = build_opener(ProxyHandler({}), HTTPSHandler(context=context), NoRedirect())

    def get(self, path):
        if path != "/cluster/resources" and not re.fullmatch(
            r"/nodes/[A-Za-z0-9][A-Za-z0-9_.-]{0,63}/tasks\?source=all&limit=100&since=[0-9]+",
            path,
        ):
            raise ValueError("endpoint not allowed")
        request = Request(
            self.base + path,
            headers={"Authorization": self.authorization, "Accept": "application/json"},
            method="GET",
        )
        with self.opener.open(request, timeout=5) as response:
            body = response.read(MAX_BODY + 1)
        if len(body) > MAX_BODY:
            raise ValueError("response too large")
        result = json.loads(body)
        if not isinstance(result, dict) or not isinstance(result.get("data"), list):
            raise ValueError("invalid response schema")
        return result["data"]


def name(value):
    if not isinstance(value, str) or not NAME.fullmatch(value):
        raise ValueError("invalid resource identity")
    return value


def number(value):
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise ValueError("invalid measurement")
    return str(value)


def sample(metric, labels, value):
    suffix = "{" + ",".join(f'{key}="{value}"' for key, value in labels.items()) + "}"
    return f"homelab_pve_{metric}{suffix if labels else ''} {number(value)}\n"


def resource_metrics(resources):
    if not isinstance(resources, list) or len(resources) > MAX_RESOURCES:
        raise ValueError("invalid resource list")
    lines, seen = [], set()
    for item in resources:
        if not isinstance(item, dict):
            raise ValueError("invalid resource")
        kind = item.get("type")
        if kind not in ("node", "qemu", "lxc", "storage"):
            continue
        node = name(item.get("node"))
        labels = {"node": node}
        if kind == "node":
            identity = (kind, node)
            prefix = "node"
            values = {
                "cpu": "cpu_ratio",
                "mem": "memory_used_bytes",
                "maxmem": "memory_capacity_bytes",
                "maxcpu": "cpu_capacity",
                "uptime": "uptime_seconds",
            }
            if item.get("status") in ("online", "offline"):
                lines.append(sample("node_up", labels, int(item["status"] == "online")))
        elif kind == "storage":
            storage = name(item.get("storage"))
            identity = (kind, node, storage)
            labels["storage"] = storage
            prefix = "storage"
            values = {"disk": "used_bytes", "maxdisk": "capacity_bytes"}
        else:
            vmid = item.get("vmid")
            if type(vmid) is not int or not 1 <= vmid <= 999999999:
                raise ValueError("invalid VM identity")
            identity = ("vm", vmid)
            tags = item.get("tags", "")
            if not isinstance(tags, str) or len(tags) > 4096:
                raise ValueError("invalid tags")
            projects = set(tags.split(";")) & {"homelab", "mediaserver"}
            project = next(iter(projects)) if len(projects) == 1 else "unclassified"
            labels.update(vmid=str(vmid), project=project, type=kind)
            prefix = "vm"
            values = {
                "cpu": "cpu_ratio",
                "mem": "memory_used_bytes",
                "maxmem": "memory_capacity_bytes",
                "maxcpu": "cpu_limit",
                "maxdisk": "reported_disk_capacity_bytes",
                "uptime": "uptime_seconds",
            }
            if item.get("status") in ("running", "stopped", "paused"):
                lines.append(sample("vm_running", labels, int(item["status"] == "running")))
        if identity in seen:
            raise ValueError("duplicate resource")
        seen.add(identity)
        for key, suffix in values.items():
            if key in item:
                lines.append(sample(f"{prefix}_{suffix}", labels, item[key]))
    return "".join(lines)


def task_metrics(node, tasks):
    node = name(node)
    if not isinstance(tasks, list) or len(tasks) > 100:
        raise ValueError("invalid task list")
    states = dict.fromkeys(("running", "succeeded", "failed", "unknown"), 0)
    for task in tasks:
        if not isinstance(task, dict):
            raise ValueError("invalid task")
        status = task.get("status")
        state = "unknown"
        if status == "RUNNING":
            state = "running"
        elif status == "OK":
            state = "succeeded"
        elif isinstance(status, str) and status:
            state = "failed"
        states[state] += 1
    lines = [
        sample("recent_tasks", {"node": node, "state": state}, count)
        for state, count in states.items()
    ]
    lines.append(sample("tasks_window_limited", {"node": node}, int(len(tasks) == 100)))
    return "".join(lines)


class CollectorState:
    def __init__(self):
        self.lock = threading.Lock()
        self.last_success = 0
        self.last_attempt = None
        self.errors = 0
        self.up = False
        self.duration = 0
        self.metrics = ""

    def collect(self, fetch, now=None):
        started = time.monotonic()
        timestamp = time.time() if now is None else now
        freshness = started if now is None else now
        lines, healthy = [], True
        try:
            resources = fetch("/cluster/resources")
            lines.append(resource_metrics(resources))
            lines.append(sample("source_up", {"source": "resources", "node": "all"}, 1))
            nodes = sorted({name(r["node"]) for r in resources if r.get("type") == "node"})
            if not nodes or len(nodes) > MAX_NODES:
                raise ValueError("invalid node count")
        except Exception:
            nodes, healthy = [], False
            lines = [sample("source_up", {"source": "resources", "node": "all"}, 0)]
        for node in nodes:
            try:
                if time.monotonic() - started >= 25:
                    raise TimeoutError("collection deadline")
                tasks = fetch(
                    f"/nodes/{node}/tasks?source=all&limit=100&since={int(timestamp) - 3600}"
                )
                lines.append(task_metrics(node, tasks))
                lines.append(sample("source_up", {"source": "tasks", "node": node}, 1))
            except Exception:
                healthy = False
                lines.append(sample("source_up", {"source": "tasks", "node": node}, 0))
        with self.lock:
            self.metrics = "".join(lines)
            self.up = healthy
            self.last_attempt = freshness
            self.duration = time.monotonic() - started
            if healthy:
                self.last_success = timestamp
            else:
                self.errors += 1

    def render(self, now=None):
        now = time.monotonic() if now is None else now
        with self.lock:
            fresh = self.last_attempt is not None and 0 <= now - self.last_attempt <= STALE_AFTER
            text = sample("collection_up", {}, int(self.up and fresh))
            text += sample("last_success_timestamp_seconds", {}, self.last_success)
            text += sample("collection_duration_seconds", {}, self.duration)
            text += "# TYPE homelab_pve_collection_errors_total counter\n"
            text += sample("collection_errors_total", {}, self.errors)
            return text + (self.metrics if fresh else "")


def handler_for(state):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/metrics":
                body = state.render().encode("ascii")
                content_type = "text/plain; version=0.0.4; charset=utf-8"
            elif self.path == "/healthz":
                body, content_type = b'{"alive":true}\n', "application/json"
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    return Handler


def main():
    try:
        context = ssl.create_default_context(cadata=os.environ["PVE_CA_PEM"])
        client = PveClient(
            os.environ["PVE_URL"],
            os.environ["PVE_METRICS_TOKEN_ID"],
            os.environ["PVE_METRICS_TOKEN_SECRET"],
            context,
        )
    except Exception:
        raise SystemExit("Invalid collector configuration; values suppressed") from None
    state = CollectorState()
    server = ThreadingHTTPServer(("0.0.0.0", 9101), handler_for(state))
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    while True:
        started = time.monotonic()
        state.collect(client.get)
        time.sleep(max(1, INTERVAL - (time.monotonic() - started)))


if __name__ == "__main__":
    main()
