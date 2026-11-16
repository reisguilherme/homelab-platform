"""Authenticated read-only view of the bounded telemetry inventory."""

import json

import httpx

from .models import ControlError, require

SOURCE_FIELDS = {"scope", "node", "state", "collectedAt", "reason"}
DISK_FIELDS = {
    "id",
    "scope",
    "node",
    "owner",
    "device",
    "model",
    "kind",
    "capacityBytes",
    "health",
    "healthReason",
    "readOnly",
    "mounted",
    "mounts",
    "partitions",
}
MOUNT_FIELDS = {
    "device",
    "path",
    "filesystem",
    "readOnly",
    "sizeBytes",
    "usedBytes",
    "availableBytes",
}
PARTITION_FIELDS = {"device", "capacityBytes", "filesystem", "mounted"}


def selected(row, fields):
    if not isinstance(row, dict) or not fields <= row.keys():
        raise ValueError("incomplete inventory")
    return {key: row[key] for key in fields}


class StorageInventory:
    def __init__(self, settings, pve, transport=None):
        self.settings, self.pve = settings, pve
        self.client = httpx.Client(
            timeout=5, follow_redirects=False, trust_env=False, transport=transport
        )

    def get(self, session):
        for node in self.settings.allowed_nodes:
            self.pve.require_permissions(session, f"/nodes/{node}", ("Sys.Audit",))
        try:
            with self.client.stream("GET", "http://pve-metrics:9101/inventory") as response:
                require(
                    response.status_code == 200,
                    "storage_unavailable",
                    "Inventário de storage indisponível.",
                    503,
                )
                body = bytearray()
                for chunk in response.iter_bytes():
                    body.extend(chunk)
                    if len(body) > 1024 * 1024:
                        raise ValueError("inventory body limit")
            result = json.loads(body)
            if (
                not isinstance(result, dict)
                or set(result) != {"collectedAt", "sourceState", "sources", "disks"}
                or not isinstance(result["sources"], list)
                or len(result["sources"]) > 32
                or not isinstance(result["disks"], list)
                or len(result["disks"]) > 128
            ):
                raise ValueError("invalid inventory")
            result["sources"] = [
                selected(row, SOURCE_FIELDS)
                for row in result["sources"]
                if row["node"] in self.settings.allowed_nodes
            ]
            result["disks"] = [
                selected(row, DISK_FIELDS)
                for row in result["disks"]
                if row["node"] in self.settings.allowed_nodes
            ]
            for disk in result["disks"]:
                disk["mounts"] = [selected(row, MOUNT_FIELDS) for row in disk["mounts"]]
                disk["partitions"] = [selected(row, PARTITION_FIELDS) for row in disk["partitions"]]
            fresh = sum(source["state"] == "fresh" for source in result["sources"])
            result["sourceState"] = (
                "fresh"
                if fresh and fresh == len(result["sources"])
                else ("partial" if fresh else "unknown")
            )
            return result
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            raise ControlError(
                503, "storage_unavailable", "Inventário de storage indisponível."
            ) from None
