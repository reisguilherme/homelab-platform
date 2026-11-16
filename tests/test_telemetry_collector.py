"""Metrics must reflect bounded read-only evidence, never cached false health."""

import importlib.util
import json
import ssl
from pathlib import Path
from urllib.error import HTTPError

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_collector_exists_as_independent_read_only_service():
    assert (ROOT / "services/telemetry/collector.py").is_file()


@pytest.fixture
def collector():
    path = ROOT / "services/telemetry/collector.py"
    assert path.is_file(), "Read-only Proxmox collector is not implemented"
    spec = importlib.util.spec_from_file_location("telemetry_collector", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def resources():
    return [
        {
            "type": "node",
            "node": "pve-test",
            "status": "online",
            "cpu": 0.2,
            "mem": 1000,
            "maxmem": 16000,
            "maxcpu": 12,
            "uptime": 99,
        },
        {
            "type": "qemu",
            "node": "pve-test",
            "vmid": 121,
            "status": "running",
            "tags": "mediaserver;playback",
            "name": "PRIVATE-MEDIA-NAME",
            "cpu": 0.4,
            "mem": 300,
            "maxmem": 4096,
            "maxcpu": 4,
            "maxdisk": 8000,
            "uptime": 88,
        },
        {
            "type": "storage",
            "node": "pve-test",
            "storage": "local-lvm",
            "disk": 1000,
            "maxdisk": 10000,
            "status": "available",
        },
    ]


def test_resource_metrics_have_safe_labels_and_only_observed_values(collector, resources):
    text = collector.resource_metrics(resources)
    assert 'homelab_pve_node_cpu_ratio{node="pve-test"} 0.2' in text
    assert 'project="mediaserver"' in text
    assert 'homelab_pve_storage_used_bytes{node="pve-test",storage="local-lvm"} 1000' in text
    assert "PRIVATE-MEDIA-NAME" not in text
    assert "temperature" not in text and "smart" not in text
    assert "metadata" not in text


def test_absent_values_do_not_become_zero(collector):
    text = collector.resource_metrics([{"type": "node", "node": "pve", "status": "online"}])
    assert "node_cpu_ratio" not in text and "node_memory_used_bytes" not in text
    assert 'homelab_pve_node_up{node="pve"} 1' in text


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1, True, "secret", None])
def test_invalid_measurements_fail_without_echoing_input(collector, resources, value):
    resources[0]["cpu"] = value
    with pytest.raises(ValueError, match="invalid measurement"):
        collector.resource_metrics(resources)


def test_duplicate_series_are_rejected(collector, resources):
    with pytest.raises(ValueError, match="duplicate resource"):
        collector.resource_metrics(resources + [resources[0]])


def test_task_metrics_are_aggregated_without_user_task_or_error_text(collector):
    tasks = [
        {"status": "RUNNING", "user": "secret-user", "upid": "secret-upid"},
        {"status": "OK"},
        {"status": "ERROR password=secret-value"},
        {},
    ]
    text = collector.task_metrics("pve", tasks)
    for state in ("running", "succeeded", "failed", "unknown"):
        assert f'state="{state}"}} 1' in text
    assert "secret" not in text and "password" not in text and "upid" not in text


def test_failed_collection_removes_resource_samples_and_retains_last_success(collector, resources):
    state = collector.CollectorState()
    state.collect(lambda path: resources if path == "/cluster/resources" else [], now=100)
    assert "node_cpu_ratio" in state.render(now=100)

    def broken(path):
        raise OSError("private token=never-print")

    state.collect(broken, now=130)
    text = state.render(now=130)
    assert "homelab_pve_collection_up 0" in text
    assert "homelab_pve_last_success_timestamp_seconds 100" in text
    assert "node_cpu_ratio" not in text
    assert "never-print" not in text


def test_partial_task_failure_preserves_resources_but_is_not_full_health(collector, resources):
    def partial(path):
        if path == "/cluster/resources":
            return resources
        raise OSError("forbidden")

    state = collector.CollectorState()
    state.collect(partial, now=100)
    text = state.render(now=101)
    assert "node_cpu_ratio" in text
    assert "homelab_pve_collection_up 0" in text
    assert 'source="tasks",node="pve-test"} 0' in text
    assert "homelab_pve_recent_tasks{" not in text


def test_stale_collector_drops_samples_even_if_server_is_alive(collector, resources):
    state = collector.CollectorState()
    state.collect(lambda path: resources if path == "/cluster/resources" else [], now=100)
    text = state.render(now=176)
    assert "node_cpu_ratio" not in text
    assert "homelab_pve_collection_up 0" in text
    assert "homelab_pve_last_success_timestamp_seconds 100" in text


class Response:
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def read(self, size):
        return self.body[:size]


def test_http_client_sends_token_only_in_header_and_reads_bounded_json(collector, monkeypatch):
    seen = []

    class Opener:
        def open(self, request, timeout):
            seen.append((request, timeout))
            return Response(json.dumps({"data": [{"node": "pve"}]}).encode())

    monkeypatch.setattr(collector, "build_opener", lambda *handlers: Opener())
    context = ssl.create_default_context()
    client = collector.PveClient("https://pve.example:8006", "metric@pve!read", "private", context)
    assert client.get("/cluster/resources") == [{"node": "pve"}]
    request, timeout = seen[0]
    assert request.get_method() == "GET"
    assert request.full_url == "https://pve.example:8006/api2/json/cluster/resources"
    assert request.get_header("Authorization") == "PVEAPIToken=metric@pve!read=private"
    assert timeout == 5
    assert "private" not in request.full_url


@pytest.mark.parametrize("url", ["http://pve", "https://user:pass@pve", "https://pve/?secret=1"])
def test_invalid_upstream_is_refused(collector, url):
    with pytest.raises(ValueError):
        collector.PveClient(url, "metric@pve!read", "private", ssl.create_default_context())


def test_tls_verification_cannot_be_disabled(collector):
    context = ssl._create_unverified_context()
    with pytest.raises(ValueError, match="TLS verification"):
        collector.PveClient("https://pve", "metric@pve!read", "private", context)


def test_redirect_is_not_followed_with_credentials(collector):
    with pytest.raises(HTTPError):
        collector.NoRedirect().redirect_request(None, None, 302, "redirect", {}, "https://evil/")


def test_oversized_upstream_body_is_refused(collector, monkeypatch):
    class Opener:
        def open(self, request, timeout):
            return Response(b" " * (1024 * 1024 + 1))

    monkeypatch.setattr(collector, "build_opener", lambda *handlers: Opener())
    client = collector.PveClient("https://pve", "m@pve!r", "private", ssl.create_default_context())
    with pytest.raises(ValueError, match="response too large"):
        client.get("/cluster/resources")
