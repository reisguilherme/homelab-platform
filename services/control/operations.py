"""Governance policy, durable intents and typed PVE operations."""

import json
import re
import threading

from .audit import fingerprint
from .models import ControlError, require, utc

GIB = 1024**3
MIB = 1024**2
CREATE_PRIVILEGES = (
    "VM.Allocate",
    "VM.Audit",
    "VM.Config.CPU",
    "VM.Config.Memory",
    "VM.Config.Options",
    "VM.Config.HWType",
)


def memory(config):
    value = str(config.get("memory", "512"))
    return int(value.split(",")[0].removeprefix("current="))


class Governance:
    def __init__(self, settings, proxmox, store):
        self.settings, self.pve, self.store = settings, proxmox, store
        self.mutation_lock = threading.RLock()

    def locate(self, session, vmid):
        self.pve.require_permissions(session, f"/vms/{vmid}", ("VM.Audit",))
        for item in self.pve.resources(session):
            if item.get("type") == "qemu" and item.get("vmid") == vmid:
                require(
                    item.get("node") in self.settings.allowed_nodes,
                    "target_denied",
                    "Nó fora do escopo.",
                    403,
                )
                return item
        raise ControlError(404, "not_found", "VM não encontrada ou sem acesso.")

    def details(self, session, vmid):
        resource = self.locate(session, vmid)
        config = self.pve.config(session, resource["node"], vmid)
        permissions = self.pve.permissions(session, f"/vms/{vmid}")
        dependencies = list(self.settings.dependencies.get(vmid, []))
        if vmid in self.settings.protected_vmids:
            dependencies.append("Recurso protegido da infraestrutura ou do acervo")
        if any(re.match(r"^(usb|hostpci|virtiofs|parallel)\d+$", k) for k in config):
            dependencies.append("Dispositivo físico ou compartilhamento externo")
        pending = self.pve.pending(session, resource["node"], vmid)
        pending_names = [item["key"] for item in pending if "pending" in item or item.get("delete")]
        capabilities = {
            "resources": all(p in permissions for p in ("VM.Config.CPU", "VM.Config.Memory")),
            **dict.fromkeys(("start", "shutdown", "reboot", "stop"), "VM.PowerMgmt" in permissions),
            "delete": "VM.Allocate" in permissions and not dependencies,
            "acl": "Permissions.Modify" in permissions,
        }
        if vmid == self.settings.control_vmid:
            capabilities.update(
                dict.fromkeys(("resources", "shutdown", "reboot", "stop", "delete"), False)
            )
        tags = [tag for tag in str(config.get("tags", "")).split(";") if tag]
        dto = {
            "vmid": vmid,
            "node": resource["node"],
            "name": config.get("name", f"vm-{vmid}"),
            "project": "mediaserver"
            if "mediaserver" in tags
            else "homelab"
            if "homelab" in tags
            else None,
            "pool": resource.get("pool"),
            "tags": tags,
            "status": resource.get("status", "unknown"),
            "cores": int(config.get("cores", 1)) * int(config.get("sockets", 1)),
            "memoryMiB": memory(config),
            "memoryUsedMiB": round(resource["mem"] / MIB, 1) if "mem" in resource else None,
            "cpu": resource.get("cpu"),
            "diskGiB": round(resource.get("maxdisk", 0) / GIB, 2),
            "digest": config.get("digest"),
            "pending": pending_names,
            "dependencies": dependencies,
            "capabilities": capabilities,
            "collectedAt": utc(),
        }
        return dto, config

    def list_vms(self, session):
        items = []
        for resource in self.pve.resources(session):
            if (
                resource.get("type") == "qemu"
                and resource.get("node") in self.settings.allowed_nodes
            ):
                try:
                    dto, _ = self.details(session, resource["vmid"])
                    items.append(dto)
                except ControlError as error:
                    if error.status != 403:
                        raise
        return {"items": items, "collectedAt": utc(), "sourceState": "fresh"}

    def overview(self, session):
        resources = self.pve.resources(session)
        nodes = [
            {
                "name": r["node"],
                "status": r.get("status", "unknown"),
                "cpu": r.get("cpu"),
                "memoryMiB": r.get("mem", 0) / MIB,
                "maxMemoryMiB": r.get("maxmem", 0) / MIB,
            }
            for r in resources
            if r.get("type") == "node" and r.get("node") in self.settings.allowed_nodes
        ]
        capacity = {
            "totalMemoryMiB": sum(n["maxMemoryMiB"] for n in nodes),
            "usedMemoryMiB": sum(n["memoryMiB"] for n in nodes),
            "allocatedMemoryMiB": None,
            "visibleAllocatedMemoryMiB": sum(
                r.get("maxmem", 0) / MIB
                for r in resources
                if r.get("type") in ("qemu", "lxc") and r.get("node") in self.settings.allowed_nodes
            ),
            "freeStorageGiB": sum(
                max(0, r.get("maxdisk", 0) - r.get("disk", 0)) / GIB
                for r in resources
                if r.get("type") == "storage" and r.get("node") in self.settings.allowed_nodes
            ),
        }
        alerts = [
            {
                "level": "info",
                "message": "Inventário limitado às permissões desta sessão; "
                "orçamento de alocação usa coleta independente.",
            }
        ]
        links = [
            {"label": label, "url": url}
            for label, url in (
                ("Proxmox", self.settings.pve_web_url),
                ("Grafana", self.settings.grafana_url),
            )
            if url
        ]
        return {
            "collectedAt": utc(),
            "sourceState": "fresh" if nodes else "unknown",
            "nodes": nodes,
            "capacity": capacity,
            "alerts": alerts,
            "consoleLinks": links,
        }

    def profiles(self, session):
        items = []
        for p in self.settings.profiles:
            paths = [f"/vms/{v}" for v in p.vmids] if p.vmids else ["/vms"]
            if any(
                set(CREATE_PRIVILEGES).issubset(self.pve.permissions(session, path))
                for path in paths
            ):
                storage = self.pve.permissions(session, f"/storage/{p.storage}")
                if "Datastore.AllocateSpace" in storage:
                    items.append(
                        {
                            "id": p.id,
                            "label": p.label,
                            "readiness": p.readiness,
                            "projects": p.projects,
                            "network": "none",
                            "limits": {
                                k: v
                                for k, v in p.model_dump().items()
                                if k.startswith(("min", "max"))
                                and k
                                in {
                                    "minCores",
                                    "maxCores",
                                    "minMemoryMiB",
                                    "maxMemoryMiB",
                                    "minDiskGiB",
                                    "maxDiskGiB",
                                }
                            },
                        }
                    )
        return {"items": items, "collectedAt": utc()}

    def capacity(self, session, node, extra_memory, profile=None, disk_gib=0, replacing=None):
        require(
            not any(
                op["action"] in ("create", "resources") and op["node"] == node
                for op in self.store.pending()
            ),
            "capacity_pending",
            "Outra alocação ainda não foi confirmada; acompanhe a operação antes de ampliar.",
        )
        # Parent ACL propagation does not prove inventory completeness: child NoAccess can hide VMs.
        snapshot = self.pve.capacity_snapshot(node, profile)
        status, resources = snapshot["status"], snapshot["resources"]
        require(
            not any(r.get("type") == "lxc" and r.get("node") == node for r in resources),
            "capacity_unknown",
            "Este perfil ainda não dimensiona containers LXC.",
        )
        allocated = 0
        for resource in resources:
            if resource.get("type") == "qemu" and resource.get("node") == node:
                config = snapshot["configs"][resource["vmid"]]
                require(
                    "memory" in config and resource.get("maxmem", 0) > 0,
                    "capacity_unknown",
                    "Memória da VM não comprovada.",
                )
                desired = extra_memory if resource["vmid"] == replacing else memory(config)
                allocated += max(desired * MIB, resource.get("maxmem", 0))
        reserve = profile.reserveMemoryMiB if profile else self.settings.reserve_memory_mib
        total = status.get("memory", {}).get("total", 0)
        require(
            total > 0
            and allocated + (0 if replacing else extra_memory * MIB) + reserve * MIB <= total,
            "capacity_memory",
            "Memória comprometida excede o orçamento com reserva do host.",
        )
        if profile:
            self.pve.require_permissions(
                session,
                f"/storage/{profile.storage}",
                ("Datastore.AllocateSpace",),
            )
            storage = snapshot["storage"]
            config = snapshot["storage_config"]
            require(
                storage.get("active") == 1
                and storage.get("enabled", 1) == 1
                and storage.get("type") == "lvmthin"
                and config.get("type") == "lvmthin"
                and not config.get("shared", 0)
                and config.get("vgname") == profile.volumeGroup
                and config.get("thinpool") == profile.thinPool,
                "storage_unavailable",
                "Storage não está pronto para este perfil.",
            )
            pools = snapshot["pools"]
            matches = [
                p
                for p in pools
                if p.get("vg") == profile.volumeGroup and p.get("lv") == profile.thinPool
            ]
            require(
                len(matches) == 1, "capacity_unknown", "Não foi possível identificar o thin pool."
            )
            pool = matches[0]
            require(
                pool.get("lv_state") == "a"
                and pool.get("metadata_size", 0) > 0
                and pool.get("lv_size", 0) > 0,
                "capacity_unknown",
                "Estado ou metadados do thin pool indisponíveis.",
            )
            require(
                pool["metadata_used"] / pool["metadata_size"] * 100 < profile.maxMetadataPercent,
                "capacity_metadata",
                "Metadados do thin pool acima do limite.",
            )
            require(
                (pool["used"] + disk_gib * GIB) / pool["lv_size"] * 100 < profile.maxDataPercent
                and storage.get("avail", 0) >= (disk_gib + profile.reserveStorageGiB) * GIB,
                "capacity_storage",
                "Folga física insuficiente para esta alocação.",
            )
            volumes = snapshot["volumes"]
            require(
                all(type(v.get("size")) is int and v["size"] >= 0 for v in volumes),
                "capacity_unknown",
                "Tamanho de todos os volumes deve ser comprovado.",
            )
            commitment = sum(v["size"] for v in volumes)
            require(
                commitment + disk_gib * GIB
                <= min(
                    profile.maxCommittedGiB * GIB,
                    pool["lv_size"] - profile.reserveStorageGiB * GIB,
                ),
                "capacity_commitment",
                "Discos virtuais excedem o compromisso permitido.",
            )

    def acl(self, session, vmid):
        resource = self.locate(session, vmid)
        self.pve.require_permissions(session, f"/vms/{vmid}", ("Permissions.Modify",))
        path = f"/vms/{vmid}"
        items = []
        for entry in self.pve.acl(session):
            explicit = entry.get("path") == path
            ancestor = entry.get("path") in ("/", "/vms") and entry.get("propagate") == 1
            pool = resource.get("pool")
            if pool and entry.get("propagate") == 1:
                pool_path = "/pool/" + pool
                origin = entry.get("path", "")
                ancestor |= (
                    origin == "/pool" or pool_path == origin or pool_path.startswith(origin + "/")
                )
            if explicit or ancestor:
                items.append(
                    {
                        "principalType": entry["type"],
                        "principal": entry["ugid"],
                        "role": entry["roleid"],
                        "propagate": bool(entry.get("propagate")),
                        "inherited": not explicit,
                        "origin": entry["path"],
                    }
                )
        items.sort(key=lambda i: (i["origin"], i["principalType"], i["principal"], i["role"]))
        result = {
            "items": items,
            "digest": fingerprint(items),
            "completeness": "complete"
            if resource.get("pool") and "Sys.Audit" in self.pve.permissions(session, "/access")
            else "partial",
        }
        for kind, key in (("users", "userid"), ("groups", "groupid"), ("roles", "roleid")):
            result[kind] = [
                {"id": e[key], "label": e[key]} for e in self.pve.principals(session, kind)
            ]
        return result

    def blockers(self, session, dto, config):
        result = list(dto["dependencies"])
        if dto["status"] != "stopped":
            result.append("Desligue a VM antes de excluir")
        if config.get("protection") or config.get("lock") or config.get("template"):
            result.append("Proteção, lock ou template ativo")
        if any(key in config for key in ("args", "hookscript")):
            result.append("Configuração avançada exige o console nativo")
        for key, value in config.items():
            if re.match(r"^(scsi|virtio|sata|ide|efidisk|tpmstate|unused)\d+$", key):
                value = str(value)
                volume = value.split(",")[0]
                if volume == "none" and "media=cdrom" in value:
                    continue
                if (
                    not re.fullmatch(
                        r"[A-Za-z][A-Za-z0-9_-]*:vm-"
                        + str(dto["vmid"])
                        + r"-(?:disk-\d+|cloudinit)",
                        volume,
                    )
                    or "shared=1" in value
                ):
                    result.append("Volume externo, compartilhado ou de propriedade não comprovada")
                    break
                storage = value.split(":", 1)[0]
                profiles = [
                    p
                    for p in self.settings.profiles
                    if p.storage == storage and p.node == dto["node"]
                ]
                if not profiles:
                    result.append("Storage fora da lista de exclusão local")
                    break
                observed = self.pve.storage_config(session, storage)
                if not any(
                    observed.get("type") == "lvmthin"
                    and not observed.get("shared", 0)
                    and observed.get("vgname") == p.volumeGroup
                    and observed.get("thinpool") == p.thinPool
                    for p in profiles
                ):
                    result.append("Storage local não comprovado")
                    break
        return result

    def deletion_preview(self, session, vmid):
        self.pve.require_permissions(session, f"/vms/{vmid}", ("VM.Allocate",))
        dto, config = self.details(session, vmid)
        blockers = self.blockers(session, dto, config)
        result = {
            "name": dto["name"],
            "digest": dto["digest"],
            "allowed": not blockers,
            "blockers": blockers,
            "impact": ["Excluir esta VM, seus volumes próprios referenciados e ACL específica"],
        }
        if not blockers:
            result.update(self.store.preview(session.user, vmid, dto["name"], dto["digest"]))
        return result

    def _submit(
        self, session, key, action, target, parameters, node, call, verify=None, intent_id=None
    ):
        op, new = self.store.begin(
            session.user, key, action, target, parameters, intent_id=intent_id
        )
        if not new:
            return op
        identifier = op["operationId"]
        self.store.update(identifier, "reconciling", node=node, target=target)
        returned = False
        try:
            result = call(identifier)
            returned = True
            if isinstance(result, str) and result.startswith(f"UPID:{node}:"):
                return self.store.update(identifier, "submitted", upid=result)
            if result is None and verify is not None and verify():
                return self.store.update(identifier, "succeeded")
            return self.store.update(identifier, "reconciling", error="result_unconfirmed")
        except ControlError as error:
            self.store.update(
                identifier,
                "reconciling" if returned or error.status == 503 else "failed",
                error=error.code,
            )
            if error.status in (401, 403):
                raise
            return self.store.dto(self.store.get(identifier))

    def create(self, session, key, request):
        with self.mutation_lock:
            parameters = request.model_dump()
            previous = self.store.existing(session.user, key, "create", None, parameters)
            if previous:
                path = f"/vms/{previous['target']}" if previous["target"] else "/vms"
                self.pve.require_permissions(session, path, ("VM.Allocate",))
                return previous
            profile = next((p for p in self.settings.profiles if p.id == request.profileId), None)
            require(profile is not None, "profile_unavailable", "Perfil indisponível.", 422)
            if profile.vmids:
                used = {r.get("vmid") for r in self.pve.resources(session)}
                available = [
                    v
                    for v in profile.vmids
                    if v not in used
                    and set(CREATE_PRIVILEGES).issubset(self.pve.permissions(session, f"/vms/{v}"))
                ]
                require(
                    bool(available),
                    "vmid_unavailable",
                    "Nenhum VMID permitido livre neste perfil.",
                    403,
                )
                vmid = available[0]
            else:
                self.pve.require_permissions(session, "/vms", CREATE_PRIVILEGES)
                vmid = self.pve.next_id(session)
            self.pve.require_permissions(session, f"/vms/{vmid}", CREATE_PRIVILEGES)
            require(
                request.project in profile.projects,
                "project_denied",
                "Projeto fora do perfil.",
                403,
            )
            for value, minimum, maximum in (
                (request.cores, profile.minCores, profile.maxCores),
                (request.memoryMiB, profile.minMemoryMiB, profile.maxMemoryMiB),
                (request.diskGiB, profile.minDiskGiB, profile.maxDiskGiB),
            ):
                require(
                    minimum <= value <= maximum,
                    "profile_limits",
                    "Recursos fora dos limites do perfil.",
                    422,
                )
            self.capacity(session, profile.node, request.memoryMiB, profile, request.diskGiB)
            require(
                vmid not in self.settings.protected_vmids,
                "vmid_conflict",
                "VMID reservado; confira o inventário.",
            )
            op, new = self.store.begin(session.user, key, "create", None, parameters)
            if not new:
                return op
            identifier = op["operationId"]
            self.store.update(identifier, "reconciling", node=profile.node, target=vmid)
            try:
                upid = self.pve.create(session, profile, vmid, request, identifier)
                require(
                    isinstance(upid, str) and upid.startswith(f"UPID:{profile.node}:"),
                    "result_unconfirmed",
                    "Criação exige reconciliação.",
                    503,
                )
                return self.store.update(identifier, "submitted", upid=upid)
            except ControlError as error:
                self.store.update(
                    identifier, "reconciling" if error.status == 503 else "failed", error=error.code
                )
                if error.status in (401, 403):
                    raise
                return self.store.dto(self.store.get(identifier))

    def mutate_vm(self, session, key, vmid, kind, request):
        with self.mutation_lock:
            privilege = {
                "resources": ("VM.Config.CPU", "VM.Config.Memory"),
                "power": ("VM.PowerMgmt",),
                "delete": ("VM.Allocate",),
                "acl-add": ("Permissions.Modify",),
                "acl-remove": ("Permissions.Modify",),
            }[kind]
            self.pve.require_permissions(session, f"/vms/{vmid}", privilege)
            parameters = request.model_dump()
            previous = self.store.existing(session.user, key, kind, vmid, parameters)
            if previous:
                return previous
            require(
                not any(op["target"] == vmid for op in self.store.pending()),
                "operation_pending",
                "Há outra operação ainda não confirmada nesta VM.",
            )
            dto, config = self.details(session, vmid)
            node = dto["node"]
            if kind in ("power", "resources"):
                require(
                    vmid != self.settings.control_vmid,
                    "self_control",
                    "Use o console Proxmox para alterar a VM deste portal.",
                )
                require(dto["digest"] == request.expectedDigest)
                require(
                    not config.get("lock"), "vm_locked", "A VM está bloqueada por outra tarefa."
                )
            if kind == "resources":
                require(
                    request.cores <= self.settings.resource_max_cores
                    and request.memoryMiB <= self.settings.resource_max_memory_mib,
                    "resource_limits",
                    "Recursos excedem o limite da plataforma.",
                    422,
                )
                self.capacity(session, node, request.memoryMiB, replacing=vmid)
                return self._submit(
                    session,
                    key,
                    kind,
                    vmid,
                    parameters,
                    node,
                    lambda _: self.pve.set_resources(session, node, vmid, request),
                    lambda: self._resources_match(session, node, vmid, request),
                )
            if kind == "power":
                require(
                    request.action != "stop" or request.confirmation == dto["name"],
                    "confirmation_required",
                    "Confirme o nome exato para parada forçada.",
                )
                return self._submit(
                    session,
                    key,
                    kind,
                    vmid,
                    parameters,
                    node,
                    lambda _: self.pve.action(session, node, vmid, request.action),
                )
            if kind == "delete":
                intent = self.store.intent(request.intentId, session.user, vmid)
                require(
                    intent["digest"] == dto["digest"]
                    and intent["name"] == dto["name"]
                    and request.confirmationName == dto["name"],
                    "deletion_changed",
                    "Estado ou confirmação mudou; gere nova prévia.",
                )
                require(
                    not self.blockers(session, dto, config),
                    "deletion_protected",
                    "VM protegida ou dependência presente.",
                )
                return self._submit(
                    session,
                    key,
                    kind,
                    vmid,
                    parameters,
                    node,
                    lambda _: self.pve.delete(session, node, vmid),
                    intent_id=request.intentId,
                )
            acl = self.acl(session, vmid)
            require(
                request.principal != self.settings.capacity_token_id.split("!", 1)[0],
                "acl_protected_principal",
                "Identidade interna de coleta protegida.",
                403,
            )
            require(
                acl["digest"] == request.expectedAclDigest,
                "acl_changed",
                "ACL mudou; atualize a leitura.",
            )
            collection = "users" if request.principalType == "user" else "groups"
            require(
                any(p["id"] == request.principal for p in acl[collection])
                and any(r["id"] == request.role for r in acl["roles"]),
                "acl_identity",
                "Usuário, grupo ou papel não existe ou não está acessível.",
                422,
            )
            remove = kind == "acl-remove"
            if remove:
                require(
                    any(
                        self._acl_match(entry, request) and not entry["inherited"]
                        for entry in acl["items"]
                    ),
                    "acl_inherited",
                    "Esta ACL é herdada ou não existe diretamente na VM.",
                )
            return self._submit(
                session,
                key,
                kind,
                vmid,
                parameters,
                node,
                lambda _: self.pve.update_acl(session, vmid, request, remove),
                lambda: self._acl_after(session, vmid, request, remove),
            )

    def _resources_match(self, session, node, vmid, request):
        config = self.pve.config(session, node, vmid)
        return (
            int(config.get("cores", 1)) * int(config.get("sockets", 1)) == request.cores
            and memory(config) == request.memoryMiB
        )

    @staticmethod
    def _acl_match(entry, request):
        return all(entry[k] == getattr(request, k) for k in ("principalType", "principal", "role"))

    def _acl_after(self, session, vmid, request, remove):
        entries = self.acl(session, vmid)["items"]
        exact = [e for e in entries if self._acl_match(e, request) and not e["inherited"]]
        return not exact if remove else bool(exact) and exact[0]["propagate"] == request.propagate

    def operation(self, session, identifier):
        row = self.store.get(identifier)
        require(
            row["actor"] == session.user,
            "permission_denied",
            "Operação não pertence a esta sessão.",
            403,
        )
        if row["target"]:
            self.pve.require_permissions(session, f"/vms/{row['target']}", ("VM.Audit",))
        else:
            self.pve.require_permissions(session, "/vms", ("VM.Allocate",))
        if row["state"] in ("submitted", "running", "reconciling") and row["upid"]:
            status = self.pve.task_status(session, row["node"], row["upid"])
            if status.get("status") == "stopped":
                if status.get("exitstatus") == "OK":
                    if self._result_matches(session, row):
                        return self.store.update(identifier, "succeeded")
                    if row["state"] != "reconciling":
                        return self.store.update(
                            identifier, "reconciling", error="result_unconfirmed"
                        )
                    return self.store.dto(row)
                return self.store.update(identifier, "failed", error="task_failed")
            if status.get("status") == "running" and row["state"] != "running":
                return self.store.update(identifier, "running")
        if row["state"] == "reconciling" and not row["upid"] and row["action"] == "create":
            # The server-written operation marker disambiguates a lost create response.
            if self._result_matches(session, row):
                return self.store.update(identifier, "succeeded")
        # Without UPID or definitive readback, no automatic resend or fabricated success.
        return self.store.dto(row)

    def _result_matches(self, session, row):
        resources = self.pve.resources(session)
        resource = next(
            (r for r in resources if r.get("type") == "qemu" and r.get("vmid") == row["target"]),
            None,
        )
        parameters = json.loads(row["parameters"])
        if row["action"] == "delete":
            return resource is None
        if resource is None or resource.get("node") != row["node"]:
            return False
        if row["action"] == "power":
            expected = "stopped" if parameters["action"] in ("shutdown", "stop") else "running"
            return resource.get("status") == expected
        if row["action"] == "create":
            config = self.pve.config(session, row["node"], row["target"])
            return (
                f"operation={row['id']} " in config.get("description", "") + " "
                and config.get("name") == parameters["name"]
                and not config.get("lock")
                and int(config.get("cores", 1)) == parameters["cores"]
                and memory(config) == parameters["memoryMiB"]
                and resource.get("maxdisk", 0) == parameters["diskGiB"] * GIB
                and resource.get("status") == "stopped"
            )
        return False

    def audit(self, session, cursor=0):
        events = self.store.events(session.user, cursor)
        visible = []
        for event in events:
            path = f"/vms/{event['target']}" if event["target"] else "/vms"
            privilege = "VM.Audit" if event["target"] else "VM.Allocate"
            if privilege in self.pve.permissions(session, path):
                visible.append(event)
        return {"items": visible, "nextCursor": cursor + 50 if len(events) == 50 else None}
