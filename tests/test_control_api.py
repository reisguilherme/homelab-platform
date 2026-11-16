"""Typed HTTP integration against a stateful fake PVE, never real guests."""

import json
import sqlite3
import time
from urllib.parse import parse_qs

import httpx
import pytest
from fastapi.testclient import TestClient

from services.control.app import create_app
from services.control.models import Profile, Settings
from services.control.proxmox import ProxmoxClient

ORIGIN = "https://control.test"
DIGEST = "a" * 40
UPID = "UPID:pve01:00000001:00000001:00000001:qmcreate:901:operator@pve:"


class PVE:
    def __init__(self):
        self.calls = []
        self.mutations = []
        self.denied = set()
        self.config = {
            "name": "fixture-vm",
            "cores": 1,
            "memory": "current=512",
            "digest": DIGEST,
            "tags": "fixture",
            "scsi0": "local-lvm:vm-900-disk-0,size=4G",
            "cipassword": "must-not-leak",
            "sshkeys": "must-not-leak-too",
        }
        self.task = {"status": "running"}
        self.acls = [
            {
                "path": "/",
                "type": "user",
                "ugid": "reader@pve",
                "roleid": "PVEAuditor",
                "propagate": 1,
            }
        ]
        self.timeout_create = False
        self.created = None
        self.deleted = False
        self.revoke_acl_readback = False
        self.global_allocate = True
        self.metadata_used = 1
        self.live_memory_mib = 512
        self.node_memory_mib = 16384
        self.hidden_memory_mib = 0
        self.capacity_authority = {
            "groups": [],
            "tokens": {"collector": {"privsep": 1}},
            "enable": 1,
        }
        self.capacity_acl_override = False
        self.capacity_reads = 0
        self.capacity_change_during_read = False
        self.pool = "fixtures/children"
        self.storage_config = {"type": "lvmthin", "vgname": "pve", "thinpool": "data"}
        self.volumes = [{"size": 4 * 1024**3, "volid": "local-lvm:vm-900-disk-0"}]
        self.permissions = {
            p: 1
            for p in (
                "VM.Audit",
                "VM.Allocate",
                "VM.PowerMgmt",
                "VM.Config.CPU",
                "VM.Config.Memory",
                "VM.Config.Options",
                "VM.Config.HWType",
                "Permissions.Modify",
                "Sys.Audit",
                "Datastore.Audit",
                "Datastore.AllocateSpace",
            )
        }

    def __call__(self, request):
        self.calls.append(request)
        path = request.url.path.removeprefix("/api2/json")
        data = parse_qs(request.content.decode())
        method = request.method
        budget = request.headers.get("Authorization", "").startswith("PVEAPIToken=")
        if budget:
            assert method == "GET" and "Cookie" not in request.headers
        if path == "/access/ticket":
            result = {
                "username": "operator@pve",
                "ticket": f"PVE:operator@pve:{int(time.time()):08X}::test",
                "CSRFPreventionToken": "upstream-csrf",
            }
        elif path == "/access/permissions":
            result = {
                request.url.params["path"]: {
                    k: v for k, v in self.permissions.items() if k not in self.denied
                }
            }
            if not self.global_allocate and request.url.params["path"] == "/vms":
                result["/vms"].pop("VM.Allocate", None)
            if budget:
                result = {
                    request.url.params["path"]: {
                        p: 1 for p in ("VM.Audit", "Sys.Audit", "Datastore.Audit")
                    }
                }
        elif path == "/access/users/metrics@pve":
            self.capacity_reads += 1
            result = dict(self.capacity_authority)
            if self.capacity_change_during_read and self.capacity_reads > 1:
                result["groups"] = ["unexpected"]
        elif path == "/cluster/resources":
            result = [
                {
                    "type": "node",
                    "node": "pve01",
                    "status": "online",
                    "maxmem": 16 * 1024**3,
                    "mem": 2 * 1024**3,
                },
                {
                    "type": "qemu",
                    "node": "pve01",
                    "vmid": 900,
                    "status": "stopped",
                    "maxmem": self.live_memory_mib * 1024**2,
                    "maxdisk": 4 * 1024**3,
                    "pool": self.pool,
                },
            ]
            if self.deleted:
                result = [entry for entry in result if entry.get("vmid") != 900]
            if self.created:
                result.append(
                    {
                        "type": "qemu",
                        "node": "pve01",
                        "vmid": 901,
                        "status": "stopped",
                        "maxmem": 512 * 1024**2,
                        "maxdisk": 4 * 1024**3,
                    }
                )
            if budget and self.hidden_memory_mib:
                result.append(
                    {
                        "type": "qemu",
                        "node": "pve01",
                        "vmid": 120,
                        "status": "running",
                        "maxmem": self.hidden_memory_mib * 1024**2,
                    }
                )
        elif path == "/cluster/nextid":
            result = 901
        elif path == "/nodes/pve01/status":
            result = {"memory": {"total": self.node_memory_mib * 1024**2}}
        elif path == "/nodes/pve01/storage/local-lvm/status":
            result = {"type": "lvmthin", "active": 1, "enabled": 1, "avail": 200 * 1024**3}
        elif path == "/storage":
            result = [{"storage": "local-lvm", **self.storage_config}]
        elif path == "/nodes/pve01/storage/local-lvm/content":
            result = self.volumes
        elif path == "/nodes/pve01/disks/lvmthin":
            result = [
                {
                    "lv": "data",
                    "vg": "pve",
                    "lv_state": "a",
                    "lv_size": 350 * 1024**3,
                    "metadata_size": 100,
                    "metadata_used": self.metadata_used,
                    "used": 40 * 1024**3,
                }
            ]
        elif path == "/nodes/pve01/qemu" and method == "POST":
            self.mutations.append(request)
            self.created = {
                "name": data["name"][0],
                "cores": int(data["cores"][0]),
                "memory": data["memory"][0],
                "description": data["description"][0],
            }
            if self.timeout_create:
                raise httpx.ReadTimeout("unknown-outcome", request=request)
            result = UPID
        elif path == "/nodes/pve01/qemu/901/config" and self.created:
            result = self.created
        elif path == "/nodes/pve01/qemu/120/config" and budget:
            result = {"memory": self.hidden_memory_mib}
        elif path == "/nodes/pve01/qemu/900/config":
            if method == "PUT":
                self.mutations.append(request)
                self.config.update(
                    cores=int(data["cores"][0]),
                    sockets=int(data["sockets"][0]),
                    memory=data["memory"][0],
                    digest="b" * 40,
                )
                result = None
            else:
                result = self.config
        elif path == "/nodes/pve01/qemu/900/pending":
            result = [{"key": "memory", "value": "512", "pending": "1024"}]
        elif path.startswith("/nodes/pve01/qemu/900/status/") or (
            path == "/nodes/pve01/qemu/900" and method == "DELETE"
        ):
            self.mutations.append(request)
            if method == "DELETE":
                self.deleted = True
            result = UPID.replace("qmcreate:901", "qmstop:900")
        elif "/tasks/" in path and path.endswith("/status"):
            result = self.task
        elif path == "/access/acl":
            if method == "PUT":
                self.mutations.append(request)
                entry = {
                    "path": data["path"][0],
                    "type": "user" if "users" in data else "group",
                    "ugid": data.get("users", data.get("groups"))[0],
                    "roleid": data["roles"][0],
                    "propagate": int(data["propagate"][0]),
                }
                self.acls = [
                    item
                    for item in self.acls
                    if not all(item[k] == entry[k] for k in ("path", "type", "ugid", "roleid"))
                ]
                if data["delete"] == ["0"]:
                    self.acls.append(entry)
                if self.revoke_acl_readback:
                    self.denied.add("Permissions.Modify")
                result = None
            else:
                result = self.acls
                if budget:
                    result = list(result) + [
                        {
                            "path": "/",
                            "type": kind,
                            "ugid": identifier,
                            "roleid": "HomelabMetrics",
                            "propagate": 1,
                        }
                        for kind, identifier in (
                            ("user", "metrics@pve"),
                            ("token", "metrics@pve!collector"),
                        )
                    ]
                    if self.capacity_acl_override:
                        result.append(
                            {
                                "path": "/vms/120",
                                "type": "user",
                                "ugid": "metrics@pve",
                                "roleid": "NoAccess",
                                "propagate": 1,
                            }
                        )
        elif path in ("/access/users", "/access/groups", "/access/roles"):
            result = {
                "/access/users": [{"userid": "reader@pve"}],
                "/access/groups": [{"groupid": "operators"}],
                "/access/roles": [{"roleid": "PVEAuditor"}],
            }[path]
        else:
            raise AssertionError(f"unexpected fake request {method} {path}")
        return httpx.Response(200, json={"data": result})


@pytest.fixture
def api(tmp_path):
    pve = PVE()
    settings = Settings(
        origin=ORIGIN,
        pve_url="https://pve.test:8006",
        db_path=tmp_path / "state.sqlite",
        allowed_nodes=("pve01",),
        capacity_token_id="metrics@pve!collector",
        capacity_token_secret="synthetic-capacity-token",
        profiles=(
            Profile(
                id="fixture",
                label="Hardware desligado",
                node="pve01",
                storage="local-lvm",
                projects=["fixture"],
            ),
        ),
    )
    adapter = ProxmoxClient(settings, transport=httpx.MockTransport(pve))
    app = create_app(settings, adapter)
    with TestClient(app, base_url=ORIGIN) as client:
        response = client.post(
            "/api/v1/session",
            headers={"Origin": ORIGIN},
            json={"username": "operator@pve", "password": "synthetic-only"},
        )
        headers = {
            "Origin": ORIGIN,
            "X-CSRF-Token": response.json()["csrfToken"],
            "Idempotency-Key": "one-intention-12345",
        }
        yield client, pve, headers, app, settings


def creation():
    return {
        "name": "fixture-created",
        "project": "fixture",
        "profileId": "fixture",
        "cores": 1,
        "memoryMiB": 512,
        "diskGiB": 4,
    }


def test_external_storage_volume_cannot_be_deleted(api):
    client, pve, headers, _, _ = api
    pve.config["scsi0"] = "ceph-media:vm-900-disk-0,size=4G"
    preview = client.post("/api/v1/vms/900/deletion-preview", headers=headers, json={})
    assert preview.status_code == 200
    assert not preview.json()["allowed"] and "intentId" not in preview.json()
    assert not pve.mutations


def test_budget_pool_must_match_actual_storage_configuration(api):
    client, pve, headers, _, _ = api
    pve.storage_config["thinpool"] = "different-pool"
    response = client.post("/api/v1/vms", headers=headers, json=creation())
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "storage_unavailable"
    assert not pve.mutations


def test_budget_requires_size_of_every_volume(api):
    client, pve, headers, _, _ = api
    del pve.volumes[0]["size"]
    response = client.post("/api/v1/vms", headers=headers, json=creation())
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "capacity_unknown"
    assert not pve.mutations


def test_acl_does_not_claim_completeness_when_pool_is_hidden(api):
    client, pve, _, _, _ = api
    pve.pool = None
    assert client.get("/api/v1/vms/900/acl").json()["completeness"] == "partial"


def test_shared_storage_configuration_blocks_deletion(api):
    client, pve, headers, _, _ = api
    pve.storage_config["shared"] = 1
    preview = client.post("/api/v1/vms/900/deletion-preview", headers=headers, json={})
    assert not preview.json()["allowed"] and not pve.mutations


def test_acl_shows_pool_inheritance_and_partial_read_scope(api):
    client, pve, _, _, _ = api
    pve.denied.add("Sys.Audit")
    pve.acls.append(
        {
            "path": "/pool/fixtures",
            "type": "group",
            "ugid": "operators",
            "roleid": "PVEAuditor",
            "propagate": 1,
        }
    )
    response = client.get("/api/v1/vms/900/acl")
    assert response.json()["completeness"] == "partial"
    assert any(
        entry["origin"] == "/pool/fixtures" and entry["inherited"]
        for entry in response.json()["items"]
    )


def test_acl_cannot_override_internal_capacity_identity(api):
    client, pve, headers, _, _ = api
    digest = client.get("/api/v1/vms/900/acl").json()["digest"]
    response = client.put(
        "/api/v1/vms/900/acl",
        headers=headers,
        json={
            "principalType": "user",
            "principal": "metrics@pve",
            "role": "PVEAuditor",
            "propagate": True,
            "expectedAclDigest": digest,
        },
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "acl_protected_principal"
    assert not pve.mutations


def enable_capacity(settings):
    settings.capacity_token_id = "metrics@pve!collector"
    settings.capacity_token_secret = "synthetic-capacity-token"
    settings.capacity_role = "HomelabMetrics"


def test_allocation_requires_independent_complete_capacity_source(api):
    client, pve, headers, _, settings = api
    settings.capacity_token_id = ""
    response = client.post("/api/v1/vms", headers=headers, json=creation())
    assert response.status_code == 409 and response.json()["error"]["code"] == "capacity_unknown"
    assert not pve.mutations


def test_hidden_vm_still_consumes_authoritative_capacity_without_leaking(api):
    client, pve, headers, _, settings = api
    enable_capacity(settings)
    pve.hidden_memory_mib = 8192
    pve.node_memory_mib = 10240
    response = client.post("/api/v1/vms", headers=headers, json=creation())
    assert response.status_code == 409 and response.json()["error"]["code"] == "capacity_memory"
    assert [vm["vmid"] for vm in client.get("/api/v1/vms").json()["items"]] == [900]
    assert not pve.mutations


@pytest.mark.parametrize(
    "compromise", ["missing_groups", "groups", "privsep", "override", "changes"]
)
def test_budget_source_proves_authority_before_and_after_read(api, compromise):
    client, pve, headers, _, settings = api
    enable_capacity(settings)
    if compromise == "missing_groups":
        pve.capacity_authority.pop("groups")
    elif compromise == "groups":
        pve.capacity_authority["groups"] = ["unexpected"]
    elif compromise == "privsep":
        pve.capacity_authority["tokens"]["collector"]["privsep"] = 0
    elif compromise == "override":
        pve.capacity_acl_override = True
    else:
        pve.capacity_change_during_read = True
    response = client.post("/api/v1/vms", headers=headers, json=creation())
    assert response.status_code == 409 and response.json()["error"]["code"] == "capacity_unknown"
    assert not pve.mutations


def test_dto_does_not_expose_cloudinit_secrets(api):
    client, _, _, _, _ = api
    response = client.get("/api/v1/vms/900")
    assert response.status_code == 200
    assert response.json()["pending"] == ["memory"]
    assert response.json()["memoryMiB"] == 512
    assert "must-not-leak" not in response.text and "scsi0" not in response.text


def test_revoked_permission_is_rechecked_and_no_mutation_occurs(api):
    client, pve, headers, _, _ = api
    assert client.get("/api/v1/vms/900").json()["capabilities"]["start"]
    pve.denied.add("VM.PowerMgmt")
    response = client.post(
        "/api/v1/vms/900/actions",
        headers=headers,
        json={"action": "start", "expectedDigest": DIGEST},
    )
    assert response.status_code == 403 and not pve.mutations


@pytest.mark.parametrize(
    "privilege", ["VM.Config.Options", "VM.Config.HWType", "VM.Config.CPU", "VM.Config.Memory"]
)
def test_create_profile_requires_permissions_for_fixed_payload(api, privilege):
    client, pve, headers, app, _ = api
    pve.denied.add(privilege)
    assert client.get("/api/v1/profiles").json()["items"] == []
    response = client.post("/api/v1/vms", headers=headers, json=creation())
    assert response.status_code == 403
    assert not pve.mutations
    assert not app.state.governance.store.pending()


def test_stale_digest_and_missing_csrf_cannot_mutate(api):
    client, pve, headers, _, _ = api
    payload = {"cores": 2, "memoryMiB": 1024, "expectedDigest": "b" * 40}
    assert (
        client.patch("/api/v1/vms/900/resources", headers=headers, json=payload).status_code == 409
    )
    del headers["X-CSRF-Token"]
    assert (
        client.patch("/api/v1/vms/900/resources", headers=headers, json=payload).status_code == 403
    )
    assert not pve.mutations


def test_creation_timeout_is_durable_and_retry_never_resends(api):
    client, pve, headers, app, settings = api
    pve.timeout_create = True
    response = client.post("/api/v1/vms", headers=headers, json=creation())
    assert response.status_code == 202 and response.json()["state"] == "reconciling"
    identifier = response.json()["operationId"]
    assert (
        client.post("/api/v1/vms", headers=headers, json=creation()).json()["operationId"]
        == identifier
    )
    assert len(pve.mutations) == 1
    restarted = create_app(settings, app.state.governance.pve)
    with TestClient(restarted, base_url=ORIGIN) as fresh:
        login = fresh.post(
            "/api/v1/session",
            headers={"Origin": ORIGIN},
            json={"username": "operator@pve", "password": "synthetic-only"},
        )
        headers["X-CSRF-Token"] = login.json()["csrfToken"]
        assert (
            fresh.post("/api/v1/vms", headers=headers, json=creation()).json()["operationId"]
            == identifier
        )
    assert len(pve.mutations) == 1
    sent = parse_qs(pve.mutations[0].content.decode())
    assert sent["start"] == ["0"] and sent["onboot"] == ["0"]
    assert "net0" not in sent and "archive" not in sent


def test_task_exit_error_is_not_success_and_never_leaks_raw_error(api):
    client, pve, headers, _, _ = api
    response = client.post(
        "/api/v1/vms/900/actions",
        headers=headers,
        json={"action": "start", "expectedDigest": DIGEST},
    )
    assert response.json()["state"] == "submitted"
    pve.task = {"status": "stopped", "exitstatus": "secret upstream internal error"}
    result = client.get("/api/v1/operations/" + response.json()["operationId"])
    assert result.json()["state"] == "failed" and "secret upstream" not in result.text


def test_metadata_capacity_blocks_creation_before_journaling_or_mutation(api):
    client, pve, headers, app, _ = api
    pve.metadata_used = 90
    result = client.post("/api/v1/vms", headers=headers, json=creation())
    assert result.status_code == 409 and result.json()["error"]["code"] == "capacity_metadata"
    assert not pve.mutations
    assert (
        app.state.governance.store.db.execute("SELECT count(*) FROM operations").fetchone()[0] == 0
    )


def test_journal_failure_blocks_upstream_mutation(api):
    client, pve, headers, app, _ = api
    app.state.governance.store.db.execute("PRAGMA query_only=ON")
    response = client.post(
        "/api/v1/vms/900/actions",
        headers=headers,
        json={"action": "start", "expectedDigest": DIGEST},
    )
    assert response.status_code == 503 and not pve.mutations


def test_deletion_rechecks_passthrough_and_confirmation_after_preview(api):
    client, pve, headers, _, _ = api
    preview = client.post("/api/v1/vms/900/deletion-preview", headers=headers, json={}).json()
    assert preview["allowed"]
    pve.config["usb0"] = "host=1-1"
    response = client.request(
        "DELETE",
        "/api/v1/vms/900",
        headers=headers,
        json={"intentId": preview["intentId"], "confirmationName": "fixture-vm"},
    )
    assert response.status_code == 409 and not pve.mutations


def test_inherited_acl_cannot_be_removed_and_generic_paths_are_rejected(api):
    client, pve, headers, _, _ = api
    acl = client.get("/api/v1/vms/900/acl").json()
    assert acl["items"][0]["inherited"]
    body = {
        "principalType": "user",
        "principal": "reader@pve",
        "role": "PVEAuditor",
        "expectedAclDigest": acl["digest"],
    }
    response = client.request("DELETE", "/api/v1/vms/900/acl", headers=headers, json=body)
    assert response.status_code == 409 and not pve.mutations
    body["path"] = "/"
    assert client.put("/api/v1/vms/900/acl", headers=headers, json=body).status_code == 422


def test_resource_edit_is_verified_and_upstream_ticket_not_stored(api):
    client, pve, headers, _, settings = api
    response = client.patch(
        "/api/v1/vms/900/resources",
        headers=headers,
        json={"cores": 2, "memoryMiB": 1024, "expectedDigest": DIGEST},
    )
    assert response.status_code == 202 and response.json()["state"] == "succeeded"
    assert len(pve.mutations) == 1
    connection = sqlite3.connect(settings.db_path)
    saved = json.dumps(connection.execute("SELECT * FROM operations").fetchall())
    assert (
        "upstream-csrf" not in saved
        and "synthetic-only" not in saved
        and "PVE:operator" not in saved
    )


def test_successful_task_without_resulting_object_state_stays_reconciling(api):
    client, pve, headers, _, _ = api
    response = client.post(
        "/api/v1/vms/900/actions",
        headers=headers,
        json={"action": "start", "expectedDigest": DIGEST},
    )
    pve.task = {"status": "stopped", "exitstatus": "OK"}
    result = client.get("/api/v1/operations/" + response.json()["operationId"])
    # Fake VM remains stopped: UPID OK is not proof that the expected result persists.
    assert result.json()["state"] == "reconciling"


def test_unfinished_create_blocks_second_intention_from_reusing_capacity(api):
    client, pve, headers, _, _ = api
    first = client.post("/api/v1/vms", headers=headers, json=creation())
    assert first.json()["state"] == "submitted"
    headers["Idempotency-Key"] = "different-intention-12345"
    second = client.post("/api/v1/vms", headers=headers, json=creation())
    assert second.status_code == 409
    assert len(pve.mutations) == 1


def test_create_task_and_owned_object_confirm_success(api):
    client, pve, headers, _, _ = api
    response = client.post("/api/v1/vms", headers=headers, json=creation())
    pve.task = {"status": "stopped", "exitstatus": "OK"}
    result = client.get("/api/v1/operations/" + response.json()["operationId"])
    assert result.json()["state"] == "succeeded" and result.json()["target"] == 901


def test_lost_create_response_is_reconciled_by_own_marker_without_retry(api):
    client, pve, headers, _, _ = api
    pve.timeout_create = True
    response = client.post("/api/v1/vms", headers=headers, json=creation())
    assert response.json()["state"] == "reconciling"
    result = client.get("/api/v1/operations/" + response.json()["operationId"])
    assert result.json()["state"] == "succeeded" and len(pve.mutations) == 1


def test_acl_change_is_differential_verified_and_only_target_vm(api):
    client, pve, headers, _, _ = api
    before = client.get("/api/v1/vms/900/acl").json()
    body = {
        "principalType": "user",
        "principal": "reader@pve",
        "role": "PVEAuditor",
        "propagate": False,
        "expectedAclDigest": before["digest"],
    }
    response = client.put("/api/v1/vms/900/acl", headers=headers, json=body)
    assert response.json()["state"] == "succeeded"
    assert pve.acls[0]["path"] == "/" and len(pve.acls) == 2
    sent = parse_qs(pve.mutations[0].content.decode())
    assert sent["path"] == ["/vms/900"] and sent["propagate"] == ["0"]
    headers["Idempotency-Key"] = "remove-acl-intention-1"
    body["expectedAclDigest"] = client.get("/api/v1/vms/900/acl").json()["digest"]
    response = client.request("DELETE", "/api/v1/vms/900/acl", headers=headers, json=body)
    assert response.json()["state"] == "succeeded" and len(pve.acls) == 1


def test_acl_applied_but_readback_revoked_is_uncertain_not_failed(api):
    client, pve, headers, app, _ = api
    before = client.get("/api/v1/vms/900/acl").json()
    pve.revoke_acl_readback = True
    response = client.put(
        "/api/v1/vms/900/acl",
        headers=headers,
        json={
            "principalType": "user",
            "principal": "reader@pve",
            "role": "PVEAuditor",
            "expectedAclDigest": before["digest"],
        },
    )
    assert response.status_code == 403 and len(pve.mutations) == 1
    row = app.state.governance.store.db.execute("SELECT state FROM operations").fetchone()
    assert row["state"] == "reconciling"


def test_delete_uses_only_owned_volumes_without_purge_and_verifies_absence(api):
    client, pve, headers, _, _ = api
    preview = client.post("/api/v1/vms/900/deletion-preview", headers=headers, json={}).json()
    response = client.request(
        "DELETE",
        "/api/v1/vms/900",
        headers=headers,
        json={"intentId": preview["intentId"], "confirmationName": "fixture-vm"},
    )
    assert response.json()["state"] == "submitted"
    assert pve.mutations[0].url.params["purge"] == "0"
    assert pve.mutations[0].url.params["destroy-unreferenced-disks"] == "0"
    pve.task = {"status": "stopped", "exitstatus": "OK"}
    assert (
        client.get("/api/v1/operations/" + response.json()["operationId"]).json()["state"]
        == "succeeded"
    )


def test_delegated_nonpropagating_audit_uses_independent_budget(api):
    client, pve, headers, _, _ = api
    pve.permissions["VM.Audit"] = 0
    assert client.get("/api/v1/vms/900").status_code == 200
    result = client.post("/api/v1/vms", headers=headers, json=creation())
    assert result.status_code == 202 and len(pve.mutations) == 1
    assert "Authorization" not in pve.mutations[0].headers
    assert pve.mutations[0].headers["Cookie"].startswith("PVEAuthCookie=PVE:operator@pve:")
    assert any("Authorization" in request.headers for request in pve.calls)


def test_profile_scoped_vmid_works_without_global_allocate_and_ignores_browser_node(api):
    client, pve, headers, _, settings = api
    pve.global_allocate = False
    settings.profiles[0].vmids = [901]
    assert client.get("/api/v1/profiles").json()["items"][0]["id"] == "fixture"
    body = creation()
    body["node"] = "attacker-node"
    assert client.post("/api/v1/vms", headers=headers, json=body).status_code == 422
    assert not pve.mutations
    body.pop("node")
    response = client.post("/api/v1/vms", headers=headers, json=body)
    assert response.status_code == 202
    assert all(request.url.path != "/api2/json/cluster/nextid" for request in pve.calls)
    assert parse_qs(pve.mutations[0].content.decode())["vmid"] == ["901"]


@pytest.mark.parametrize(("live", "desired"), [(6144, 2048), (2048, 6144)])
def test_capacity_reserves_both_live_and_pending_memory(api, live, desired):
    client, pve, headers, _, _ = api
    pve.node_memory_mib = 9728  # 6144 guest + 3072 host leaves only 512 MiB.
    pve.live_memory_mib = live
    pve.config["memory"] = str(desired)
    body = creation()
    pve.node_memory_mib -= 1
    response = client.post("/api/v1/vms", headers=headers, json=body)
    assert response.status_code == 409 and not pve.mutations


def test_resource_total_vcpu_cannot_multiply_existing_sockets(api):
    client, pve, headers, _, _ = api
    pve.config.update(cores=2, sockets=2)
    assert client.get("/api/v1/vms/900").json()["cores"] == 4
    response = client.patch(
        "/api/v1/vms/900/resources",
        headers=headers,
        json={"cores": 4, "memoryMiB": 512, "expectedDigest": DIGEST},
    )
    assert response.status_code == 202
    sent = parse_qs(pve.mutations[0].content.decode())
    assert sent["cores"] == ["4"] and sent["sockets"] == ["1"]
