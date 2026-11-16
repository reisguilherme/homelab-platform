"""Fixed guest helper through the caller's Proxmox identity; no shell endpoint."""

import json
import re
import time

from pydantic import Field

from .models import ControlError, Input, require, utc


class ServiceAction(Input):
    action: str = Field(pattern=r"^(start|stop|restart)$")
    revision: str = Field(pattern=r"^[a-f0-9]{64}$")


class Runtime:
    def __init__(self, governance):
        self.governance = governance
        self.pve, self.store = governance.pve, governance.store

    def locate(self, session, vmid):
        resource = self.governance.locate(session, vmid)
        self.pve.require_permissions(
            session, f"/vms/{vmid}", ("VM.Audit", "VM.GuestAgent.Unrestricted")
        )
        return resource

    def submit(self, session, node, vmid, args):
        result = self.pve._request(
            "POST",
            f"nodes/{node}/qemu/{vmid}/agent/exec",
            session,
            data={"command": ["/usr/bin/python3", "/usr/local/libexec/homelab-runtime.py", *args]},
        )
        require(
            type(result.get("pid")) is int and result["pid"] > 0,
            "runtime_invalid",
            "O agente não confirmou a execução.",
            503,
        )
        return result["pid"]

    def status(self, session, node, vmid, pid):
        return self.pve._request(
            "GET", f"nodes/{node}/qemu/{vmid}/agent/exec-status", session, params={"pid": pid}
        )

    @staticmethod
    def output(status):
        raw = status.get("out-data", "")
        require(
            not status.get("out-truncated") and isinstance(raw, str) and len(raw) <= 131072,
            "runtime_invalid",
            "Leitura do agente incompleta.",
            503,
        )
        try:
            result = json.loads(raw)
        except (ValueError, TypeError):
            raise ControlError(
                503, "runtime_unavailable", "Inventário de serviços indisponível."
            ) from None
        require(isinstance(result, dict), "runtime_invalid", "Resposta inválida do agente.", 503)
        return result

    def list(self, session, vmid):
        resource = self.locate(session, vmid)
        if resource.get("status") != "running":
            return {"sourceState": "stopped", "items": [], "collectedAt": utc(), "memory": None}
        pid = self.submit(session, resource["node"], vmid, ["list"])
        for _ in range(16):
            status = self.status(session, resource["node"], vmid, pid)
            if status.get("exited"):
                result = self.output(status)
                require(
                    status.get("exitcode") == 0
                    and result.get("sourceState") == "fresh"
                    and isinstance(result.get("items"), list)
                    and len(result["items"]) <= 100,
                    "runtime_unavailable",
                    "O inventário desta VM ainda não está disponível.",
                    503,
                )
                return result
            time.sleep(0.25)
        raise ControlError(503, "runtime_timeout", "O agente da VM não respondeu a tempo.")

    def act(self, session, key, vmid, identifier, request):
        require(
            re.fullmatch(r"[a-z][a-z0-9-]{0,62}", identifier),
            "invalid_service",
            "Serviço inválido.",
            422,
        )
        with self.governance.mutation_lock:
            resource = self.locate(session, vmid)
            parameters = {"service": identifier, **request.model_dump()}
            action = "service-" + request.action
            existing = self.store.existing(session.user, key, action, vmid, parameters)
            if existing:
                return existing
            require(resource.get("status") == "running", "vm_stopped", "A VM precisa estar ligada.")
            operation, _ = self.store.begin(session.user, key, action, vmid, parameters)
            try:
                pid = self.submit(
                    session, resource["node"], vmid, [request.action, identifier, request.revision]
                )
            except ControlError:
                # A transport timeout might follow execution. Never automatically resubmit.
                return self.store.update(
                    operation["operationId"],
                    "reconciling",
                    node=resource["node"],
                    error="result_unconfirmed",
                )
            return self.store.update(
                operation["operationId"],
                "submitted",
                node=resource["node"],
                upid=f"guest-exec:{pid}",
            )

    def operation(self, session, identifier):
        row = self.store.get(identifier)
        require(
            row["actor"] == session.user, "permission_denied", "Operação de outra identidade.", 403
        )
        self.locate(session, row["target"])
        if row["state"] in ("succeeded", "failed") or not row["upid"]:
            return self.store.dto(row)
        require(re.fullmatch(r"guest-exec:[1-9][0-9]{0,9}", row["upid"]), "runtime_invalid")
        status = self.status(session, row["node"], row["target"], int(row["upid"].split(":")[1]))
        if not status.get("exited"):
            return self.store.dto(row)
        try:
            result = self.output(status)
        except ControlError:
            # The helper may have changed Docker before losing its result. Keep
            # the original operation/key and never replay an uncertain action.
            return self.store.update(identifier, "reconciling", error="result_unconfirmed")
        if result.get("error") == "readiness_unconfirmed":
            return self.store.update(identifier, "reconciling", error="result_unconfirmed")
        succeeded = status.get("exitcode") == 0 and result.get("ok") is True
        code = result.get("error")
        if code not in {
            "storage_unavailable",
            "state_changed",
            "service_protected",
            "action_failed",
            "maintenance_guard",
        }:
            code = "action_failed"
        return self.store.update(
            identifier, "succeeded" if succeeded else "failed", error=None if succeeded else code
        )
