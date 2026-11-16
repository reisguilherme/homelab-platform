"""Fixed-destination typed PVE adapter; no generic proxy endpoint or shell."""

import ssl
import time
from urllib.parse import quote

import httpx

from .audit import fingerprint
from .models import ControlError, require


class ProxmoxClient:
    def __init__(self, settings, transport=None):
        self.settings = settings
        context = ssl.create_default_context()
        if settings.pve_ca_pem:
            context.load_verify_locations(cadata=settings.pve_ca_pem)
        elif transport is None:
            raise ValueError("PVE_CA_PEM is required")
        self.client = httpx.Client(
            base_url=settings.pve_url + "/api2/json/",
            verify=context,
            timeout=15,
            follow_redirects=False,
            trust_env=False,
            transport=transport,
        )

    def _request(self, method, path, session=None, data=None, params=None, *, budget=False):
        headers = {}
        if budget:
            require(
                method == "GET" and session is None and data is None,
                "capacity_unknown",
                "Credencial de capacidade aceita somente leitura.",
            )
            require(
                self.settings.capacity_token_id and self.settings.capacity_token_secret,
                "capacity_unknown",
                "Fonte independente de capacidade não configurada.",
            )
            headers = {
                "Authorization": "PVEAPIToken="
                + self.settings.capacity_token_id
                + "="
                + self.settings.capacity_token_secret
            }
        elif session:
            headers = {
                "Cookie": "PVEAuthCookie=" + session.ticket,
                "CSRFPreventionToken": session.upstream_csrf,
            }
        try:
            response = self.client.request(method, path, headers=headers, data=data, params=params)
        except httpx.HTTPError:
            raise ControlError(
                503,
                "upstream_unavailable",
                "Proxmox indisponível; resultado pode exigir reconciliação.",
            ) from None
        if response.status_code in (401, 403):
            raise ControlError(
                response.status_code,
                "upstream_denied",
                "Sessão ou permissão recusada pelo Proxmox.",
            )
        if response.status_code in (400, 409):
            raise ControlError(
                409, "upstream_conflict", "O Proxmox recusou a operação; confira o estado atual."
            )
        if response.status_code == 404:
            raise ControlError(404, "not_found", "Recurso não encontrado.")
        if response.status_code != 200:
            raise ControlError(
                503, "upstream_unavailable", "Proxmox indisponível; confira a operação."
            )
        try:
            return response.json()["data"]
        except (ValueError, KeyError, TypeError):
            raise ControlError(503, "upstream_invalid", "Resposta inválida do Proxmox.") from None

    def login(self, username, password, otp=None):
        body = {"username": username, "password": password}
        if otp:
            body["otp"] = otp
        return self._request("POST", "access/ticket", data=body)

    def _capacity_authority(self):
        """Prove the RO account has no groups or ACL overrides hiding resources."""
        identifier = self.settings.capacity_token_id
        require("!" in identifier, "capacity_unknown", "Fonte de capacidade ausente.")
        user, token = identifier.split("!", 1)
        privileges = {"Sys.Audit", "VM.Audit", "Datastore.Audit"}
        for path in ("/", "/access"):
            actual = self._request(
                "GET", "access/permissions", params={"path": path}, budget=True
            ).get(path, {})
            require(
                set(actual) == privileges and all(value == 1 for value in actual.values()),
                "capacity_unknown",
                "Autoridade de leitura incompleta ou ampliada.",
            )
        authority = self._request("GET", "access/users/" + quote(user, safe=""), budget=True)
        info = authority.get("tokens", {}).get(token, {})
        require(
            authority.get("groups") == []
            and authority.get("enable", 1) == 1
            and info.get("privsep") == 1
            and all(
                not expires or expires > time.time()
                for expires in (authority.get("expire", 0), info.get("expire", 0))
            ),
            "capacity_unknown",
            "Identidade da fonte de capacidade mudou.",
        )
        entries = self._request("GET", "access/acl", budget=True)
        relevant = [
            entry
            for entry in entries
            if (entry.get("type"), entry.get("ugid")) in (("user", user), ("token", identifier))
        ]
        expected = [
            {
                "type": kind,
                "ugid": principal,
                "path": "/",
                "roleid": self.settings.capacity_role,
                "propagate": 1,
            }
            for kind, principal in (("user", user), ("token", identifier))
        ]

        def canonical(rows):
            return sorted(
                rows, key=lambda row: (row["type"], row["ugid"], row["path"], row["roleid"])
            )

        require(
            canonical(relevant) == canonical(expected),
            "capacity_unknown",
            "ACL da fonte de capacidade mudou.",
        )
        return fingerprint(
            [
                canonical(relevant),
                authority.get("groups"),
                info,
                authority.get("enable", 1),
                authority.get("expire", 0),
            ]
        )

    def capacity_snapshot(self, node, profile=None):
        """RO token is confined to GET; this internal snapshot never becomes a browser DTO."""
        require(node in self.settings.allowed_nodes, "capacity_unknown", "Nó fora do escopo.")
        try:
            before = self._capacity_authority()
            resources = self._request("GET", "cluster/resources", budget=True)
            configs = {
                r["vmid"]: self._request(
                    "GET", self._vm_path(node, r["vmid"]) + "/config", budget=True
                )
                for r in resources
                if r.get("type") == "qemu" and r.get("node") == node
            }
            result = {
                "resources": resources,
                "configs": configs,
                "status": self._request("GET", f"nodes/{node}/status", budget=True),
            }
            if profile:
                path = f"nodes/{node}/storage/{quote(profile.storage, safe='')}"
                result.update(
                    storage_config=self._select_storage(
                        self._request("GET", "storage", budget=True), profile.storage
                    ),
                    storage=self._request("GET", path + "/status", budget=True),
                    volumes=self._request(
                        "GET", path + "/content", params={"content": "images"}, budget=True
                    ),
                    pools=self._request("GET", f"nodes/{node}/disks/lvmthin", budget=True),
                )
            require(
                before == self._capacity_authority(),
                "capacity_unknown",
                "Autoridade mudou durante a coleta.",
            )
            return result
        except (ControlError, ValueError, TypeError, KeyError, AttributeError):
            raise ControlError(
                409, "capacity_unknown", "Não foi possível provar a capacidade completa do nó."
            ) from None

    def tfa(self, challenge, code):
        return self._request(
            "POST",
            "access/ticket",
            data={
                "username": challenge["user"],
                "password": "totp:" + code,
                "tfa-challenge": challenge["ticket"],
            },
        )

    def permissions(self, session, path):
        data = self._request("GET", "access/permissions", session, params={"path": path})
        # Values are propagation flags: a zero value STILL grants the privilege.
        return data.get(path, {})

    def require_permissions(self, session, path, privileges):
        actual = self.permissions(session, path)
        require(
            all(p in actual for p in privileges),
            "permission_denied",
            "Permissão insuficiente.",
            403,
        )
        return actual

    def resources(self, session):
        return self._request("GET", "cluster/resources", session)

    def _vm_path(self, node, vmid):
        require(
            node in self.settings.allowed_nodes and type(vmid) is int and vmid >= 100,
            "target_denied",
            "Destino não permitido.",
            403,
        )
        return f"nodes/{node}/qemu/{vmid}"

    def config(self, session, node, vmid):
        return self._request("GET", self._vm_path(node, vmid) + "/config", session)

    def pending(self, session, node, vmid):
        return self._request("GET", self._vm_path(node, vmid) + "/pending", session)

    def node_status(self, session, node):
        require(node in self.settings.allowed_nodes, "target_denied", "Destino não permitido.", 403)
        return self._request("GET", f"nodes/{node}/status", session)

    def acl(self, session):
        return self._request("GET", "access/acl", session)

    def principals(self, session, kind):
        require(kind in ("users", "groups", "roles"), "invalid_type", "Tipo inválido.", 422)
        return self._request("GET", "access/" + kind, session)

    def next_id(self, session):
        return int(self._request("GET", "cluster/nextid", session))

    def storage_status(self, session, node, storage):
        require(node in self.settings.allowed_nodes, "target_denied", "Destino não permitido.", 403)
        return self._request(
            "GET", f"nodes/{node}/storage/{quote(storage, safe='')}/status", session
        )

    def storage_config(self, session, storage):
        # The index permits Datastore.Audit; GET /storage/{id} requires write privileges.
        return self._select_storage(self._request("GET", "storage", session), storage)

    @staticmethod
    def _select_storage(entries, storage):
        matches = [entry for entry in entries if entry.get("storage") == storage]
        require(len(matches) == 1, "storage_unavailable", "Configuração do storage não comprovada.")
        return matches[0]

    def storage_content(self, session, node, storage):
        require(node in self.settings.allowed_nodes, "target_denied", "Destino não permitido.", 403)
        return self._request(
            "GET",
            f"nodes/{node}/storage/{quote(storage, safe='')}/content",
            session,
            params={"content": "images"},
        )

    def thin_pools(self, session, node):
        require(node in self.settings.allowed_nodes, "target_denied", "Destino não permitido.", 403)
        return self._request("GET", f"nodes/{node}/disks/lvmthin", session)

    def create(self, session, profile, vmid, request, operation_id):
        path = self._vm_path(profile.node, vmid).rsplit("/", 1)[0]
        return self._request(
            "POST",
            path,
            session,
            data={
                "vmid": vmid,
                "name": request.name,
                "tags": request.project,
                "description": f"homelab-control operation={operation_id} owner={request.project}",
                "cores": request.cores,
                "sockets": 1,
                "memory": request.memoryMiB,
                "balloon": 0,
                "scsihw": "virtio-scsi-pci",
                "scsi0": f"{profile.storage}:{request.diskGiB}",
                "ostype": "l26",
                "onboot": 0,
                "start": 0,
                "cpu": "x86-64-v2-AES",
            },
        )

    def set_resources(self, session, node, vmid, request):
        return self._request(
            "PUT",
            self._vm_path(node, vmid) + "/config",
            session,
            data={
                "cores": request.cores,
                "sockets": 1,
                "memory": request.memoryMiB,
                "digest": request.expectedDigest,
            },
        )

    def action(self, session, node, vmid, action):
        require(
            action in ("start", "shutdown", "reboot", "stop"),
            "invalid_action",
            "Ação inválida.",
            422,
        )
        body = {"forceStop": 0, "timeout": 60} if action == "shutdown" else {}
        return self._request(
            "POST", self._vm_path(node, vmid) + "/status/" + action, session, data=body
        )

    def delete(self, session, node, vmid):
        return self._request(
            "DELETE",
            self._vm_path(node, vmid),
            session,
            params={"purge": 0, "destroy-unreferenced-disks": 0},
        )

    def update_acl(self, session, vmid, request, remove=False):
        body = {
            "path": f"/vms/{vmid}",
            "roles": request.role,
            "users" if request.principalType == "user" else "groups": request.principal,
            "propagate": int(request.propagate),
            "delete": int(remove),
        }
        return self._request("PUT", "access/acl", session, data=body)

    def task_status(self, session, node, upid):
        require(
            node in self.settings.allowed_nodes and upid.startswith("UPID:" + node + ":"),
            "task_invalid",
            "Tarefa inválida.",
            503,
        )
        return self._request("GET", f"nodes/{node}/tasks/{quote(upid, safe='')}/status", session)
