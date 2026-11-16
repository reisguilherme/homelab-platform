"""Physical storage is separate from VM volumes, and failures never imply health."""

import importlib
import json
from types import SimpleNamespace

import pytest


@pytest.fixture
def storage():
    return importlib.import_module("services.telemetry.storage")


def test_pve_inventory_does_not_count_partitions_or_publish_raw_identity(storage):
    rows = [
        {
            "devpath": "/dev/sda",
            "size": 4000000000000,
            "type": "hdd",
            "model": "Fixture disk",
            "serial": "PRIVATE",
            "health": "PASSED",
        },
        {
            "devpath": "/dev/sda1",
            "parent": "/dev/sda",
            "size": 3900000000000,
            "type": "partition",
            "used": "ext4",
            "mounted": 1,
        },
    ]
    disks = storage.pve_disks("pve-test", rows)
    assert len(disks) == 1
    assert disks[0]["capacityBytes"] == 4000000000000
    assert disks[0]["mounted"] is True
    assert disks[0]["readOnly"] is None
    assert disks[0]["health"] == "unknown"
    assert disks[0]["partitions"][0]["capacityBytes"] == 3900000000000
    assert "PRIVATE" not in json.dumps(disks)


def test_pve_partition_with_null_filesystem_preserves_inventory(storage):
    rows = [
        {"devpath": "/dev/sda", "type": "hdd", "size": 4000000000000},
        {
            "devpath": "/dev/sda1",
            "parent": "/dev/sda",
            "type": "partition",
            "size": 2000000000000,
            "used": None,
        },
    ]
    disks = storage.pve_disks("pve-test", rows)
    assert len(disks) == 1
    assert disks[0]["partitions"][0]["filesystem"] == ""
    assert disks[0]["health"] == "unknown"
    rows[1]["used"] = 42
    with pytest.raises(ValueError):
        storage.pve_disks("pve-test", rows)


def test_core_probe_roundtrip_reports_physical_and_filesystem_capacity_separately(storage):
    block = {
        "blockdevices": [
            {
                "name": "sda",
                "path": "/dev/sda",
                "type": "disk",
                "model": "QEMU HARDDISK",
                "size": 100000,
                "tran": None,
                "ro": False,
            },
            {
                "name": "sdb",
                "path": "/dev/sdb",
                "type": "disk",
                "model": "Fixture USB",
                "size": 18000000000000,
                "tran": "usb",
                "ro": False,
                "rota": True,
                "serial": "NEVER-PUBLISH",
                "children": [
                    {
                        "name": "sdb1",
                        "path": "/dev/sdb1",
                        "type": "part",
                        "size": 17999999000000,
                        "fstype": "ext4",
                        "ro": False,
                        "mountpoints": ["/srv/media"],
                    }
                ],
            },
        ]
    }
    mounts = {
        "filesystems": [
            {
                "source": "/dev/sdb1",
                "target": "/srv/media",
                "fstype": "ext4",
                "options": "rw,noatime",
                "size": 17000000000000,
                "used": 11000000000000,
                "avail": 6000000000000,
            }
        ]
    }
    text = storage.probe_metrics(block, mounts, {"sdb": "passed"}, now=100)
    assert "NEVER-PUBLISH" not in text
    result = storage.parse_probe(text, node="pve-test", vmid=120, now=120)
    assert len(result["disks"]) == 1
    disk = result["disks"][0]
    assert disk["owner"] == "vm-120"
    assert disk["capacityBytes"] == 18000000000000
    assert disk["mounts"][0]["sizeBytes"] == 17000000000000
    assert disk["mounts"][0]["availableBytes"] == 6000000000000
    assert disk["mounts"][0]["readOnly"] is False
    assert disk["health"] == "passed"
    with pytest.raises(ValueError, match="stale"):
        storage.parse_probe(text, node="pve-test", vmid=120, now=251)


def test_probe_refuses_duplicate_devices_and_injection(storage):
    with pytest.raises(ValueError):
        storage.pve_disks("pve-test", [{"devpath": "/dev/sda\nINJECT", "size": 1}])
    rows = [{"devpath": "/dev/sda", "size": 1, "type": "hdd"}] * 2
    with pytest.raises(ValueError, match="duplicate"):
        storage.pve_disks("pve-test", rows)


def test_exporter_destination_is_fixed_private_http_without_credentials(storage):
    for url in (
        "http://127.0.0.1:9100/metrics",
        "http://8.8.8.8:9100/metrics",
        "http://172.16.1.2:80/metrics",
        "http://user:pass@172.16.1.2:9100/metrics",
        "http://172.16.1.2:9100/metrics?x=1",
        "http://example.test:9100/metrics",
    ):
        with pytest.raises(ValueError):
            storage.ExporterClient(url)
    storage.ExporterClient("http://172.16.1.2:9100/metrics")


def test_storage_api_checks_human_node_permission_before_fetch():
    module = importlib.import_module("services.control.storage")
    from services.control.models import ControlError

    class Denied:
        def require_permissions(self, session, path, privileges):
            raise ControlError(403, "permission_denied", "Denied")

    service = module.StorageInventory(SimpleNamespace(allowed_nodes=("pve-test",)), Denied())
    with pytest.raises(ControlError) as error:
        service.get(object())
    assert error.value.status == 403


def test_collector_keeps_core_when_host_disks_fail_and_expires_observations(storage):
    from services.telemetry.collector import CollectorState

    text = "homelab_storage_probe_up 1\nhomelab_storage_probe_timestamp_seconds 100\n"
    text += (
        'homelab_storage_probe_disk_bytes{device="sdb",model="Fixture",kind="hdd",'
        'health="unknown",readonly="false",mounted="false"} 18000000000000\n'
    )
    state = CollectorState(lambda: text, 120)

    def fetch(path):
        if path == "/cluster/resources":
            return [
                {"type": "node", "node": "pve-test"},
                {"type": "qemu", "node": "pve-test", "vmid": 120},
            ]
        if "/disks/" in path:
            raise OSError("PRIVATE failure")
        return []

    state.collect(fetch, now=100)
    result = state.inventory(now=101, wall=101)
    assert result["sourceState"] == "partial"
    assert result["disks"][0]["capacityBytes"] == 18000000000000
    assert result["sources"][0]["state"] == "unknown"
    assert state.inventory(now=176, wall=176)["disks"] == []
    assert "PRIVATE" not in json.dumps(result)


def test_malformed_resource_snapshot_cannot_crash_the_collector():
    from services.telemetry.collector import CollectorState

    state = CollectorState()
    state.collect(lambda path: {"private": "not a resource list"}, now=100)
    assert state.inventory(now=100, wall=100)["sourceState"] == "unknown"


def test_non_ascii_display_text_roundtrips_without_invalid_prometheus_escape(storage):
    text = storage.metric("probe_disk_bytes", {"model": "Disco de mídia"}, 100)
    assert "\\u" not in text


def test_guest_health_query_never_enables_smart_or_scans_media(storage, monkeypatch):
    calls = []

    def command(args):
        calls.append(args)
        if args[0] == "lsblk":
            return 0, {
                "blockdevices": [
                    {
                        "name": "sdb",
                        "path": "/dev/sdb",
                        "type": "disk",
                        "size": 18000000000000,
                        "model": "Fixture",
                        "tran": "usb",
                        "ro": False,
                        "rota": True,
                    }
                ]
            }
        if args[0] == "findmnt":
            return 0, {"filesystems": []}
        assert args == ["smartctl", "-d", "sat,12", "-n", "standby,3,5", "-H", "-j", "/dev/sdb"]
        return 5, {"smartctl": {"exit_status": 5}}

    monkeypatch.setattr(storage, "command_json", command)
    result = storage.parse_probe(storage.observe_guest(100), node="pve-test", vmid=120, now=100)
    assert result["disks"][0]["health"] == "unknown"
    assert len(calls) == 3


def test_storage_api_filters_nodes_and_drops_unapproved_raw_fields(storage):
    import httpx

    from services.control.storage import StorageInventory

    class Allowed:
        def require_permissions(self, session, path, privileges):
            assert path == "/nodes/pve-test" and privileges == ("Sys.Audit",)

    rows = storage.pve_disks("pve-test", [{"devpath": "/dev/sda", "size": 100, "type": "hdd"}])
    rows[0]["serial"] = "PRIVATE"
    foreign = storage.pve_disks("other-node", [{"devpath": "/dev/sdb", "size": 200, "type": "hdd"}])
    body = {
        "collectedAt": "2026-01-01T00:00:00Z",
        "sourceState": "partial",
        "sources": [
            {
                "scope": "pve",
                "node": "pve-test",
                "state": "fresh",
                "collectedAt": "2026-01-01T00:00:00Z",
                "reason": None,
            },
            {
                "scope": "pve",
                "node": "other-node",
                "state": "unknown",
                "collectedAt": None,
                "reason": "unavailable",
            },
        ],
        "disks": rows + foreign,
    }

    def upstream(request):
        assert str(request.url) == "http://pve-metrics:9101/inventory"
        assert "Cookie" not in request.headers and "Authorization" not in request.headers
        return httpx.Response(200, json=body)

    service = StorageInventory(
        SimpleNamespace(allowed_nodes=("pve-test",)),
        Allowed(),
        transport=httpx.MockTransport(upstream),
    )
    result = service.get(object())
    assert result["sourceState"] == "fresh"
    assert len(result["disks"]) == 1
    assert "PRIVATE" not in json.dumps(result)


def test_pve_client_only_allows_disk_query_that_skips_smart(storage, monkeypatch):
    import ssl

    from services.telemetry import collector

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self, size):
            return b'{"data": []}'

    class Opener:
        def open(self, request, timeout):
            assert request.get_method() == "GET"
            assert request.full_url.endswith("/disks/list?include-partitions=1&skipsmart=1")
            return Response()

    monkeypatch.setattr(collector, "build_opener", lambda *args: Opener())
    client = collector.PveClient(
        "https://pve.test:8006", "metric@pve!read", "private", ssl.create_default_context()
    )
    assert client.get("/nodes/pve-test/disks/list?include-partitions=1&skipsmart=1") == []
    for path in (
        "/nodes/pve-test/disks/list",
        "/nodes/pve-test/disks/list?skipsmart=0",
        "/nodes/pve-test/disks/smart",
        "/nodes/pve-test/disks/initgpt",
    ):
        with pytest.raises(ValueError, match="endpoint not allowed"):
            client.get(path)


def test_storage_http_route_requires_session_and_sys_audit(tmp_path):
    import time

    from fastapi.testclient import TestClient

    from services.control.app import create_app
    from services.control.models import ControlError, Settings

    class Denied:
        def login(self, username, password, otp):
            return {
                "username": "reader@pve",
                "ticket": f"PVE:reader@pve:{int(time.time()):08X}::test",
                "CSRFPreventionToken": "synthetic",
            }

        def require_permissions(self, session, path, privileges):
            raise ControlError(403, "permission_denied", "Denied")

    settings = Settings(
        origin="https://control.test",
        pve_url="https://pve.test:8006",
        db_path=tmp_path / "test.sqlite",
        allowed_nodes=("pve-test",),
    )
    with TestClient(create_app(settings, Denied()), base_url="https://control.test") as client:
        assert client.get("/api/v1/storage").status_code == 401
        response = client.post(
            "/api/v1/session",
            headers={"Origin": "https://control.test"},
            json={"username": "reader@pve", "password": "synthetic"},
        )
        assert response.status_code == 200
        response = client.get("/api/v1/storage")
        assert response.status_code == 403
        assert "disks" not in response.json()
