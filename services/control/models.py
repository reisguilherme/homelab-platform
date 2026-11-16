"""Strict browser inputs and operator-owned deployment settings."""

import json
import os
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field


def utc(value=None):
    return (
        datetime.fromtimestamp(value, UTC).isoformat() if value else datetime.now(UTC).isoformat()
    )


class ControlError(Exception):
    def __init__(self, status, code, message):
        self.status, self.code, self.message = status, code, message
        super().__init__(code)


def require(condition, code="conflict", message="O estado mudou; atualize a leitura.", status=409):
    if not condition:
        raise ControlError(status, code, message)


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Login(Input):
    username: str = Field(pattern=r"^[^\s:/!@]{1,48}@[A-Za-z][A-Za-z0-9._-]{0,31}$", max_length=64)
    password: str = Field(min_length=1, max_length=4096, repr=False)
    otp: str | None = Field(default=None, pattern=r"^[0-9]{6,8}$", repr=False)


class Tfa(Input):
    challengeId: str = Field(min_length=40, max_length=128)
    code: str = Field(pattern=r"^[0-9]{6,8}$", repr=False)


class Resources(Input):
    cores: int = Field(ge=1, le=128)
    memoryMiB: int = Field(ge=128, le=1048576)
    expectedDigest: str = Field(pattern=r"^[a-f0-9]{40}$")


class CreateVM(Input):
    name: str = Field(pattern=r"^[a-z][a-z0-9-]{0,62}$")
    project: str = Field(pattern=r"^[a-z][a-z0-9-]{0,30}$")
    profileId: str = Field(pattern=r"^[a-z][a-z0-9-]{0,62}$")
    cores: int = Field(ge=1, le=128)
    memoryMiB: int = Field(ge=128, le=1048576)
    diskGiB: int = Field(ge=1, le=1048576)


class Action(Input):
    action: Literal["start", "shutdown", "reboot", "stop"]
    expectedDigest: str = Field(pattern=r"^[a-f0-9]{40}$")
    confirmation: str | None = Field(default=None, max_length=63)


class Deletion(Input):
    intentId: str = Field(min_length=32, max_length=128)
    confirmationName: str = Field(min_length=1, max_length=63)


class Acl(Input):
    principalType: Literal["user", "group"]
    principal: str = Field(pattern=r"^[A-Za-z0-9_.@-]{1,64}$")
    role: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_.-]{0,63}$")
    propagate: bool = True
    expectedAclDigest: str = Field(pattern=r"^[a-f0-9]{64}$")


class Profile(Input):
    id: str = Field(pattern=r"^[a-z][a-z0-9-]{0,62}$")
    label: str = Field(min_length=1, max_length=100)
    node: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9-]{0,62}$")
    storage: str = Field(pattern=r"^[a-zA-Z][a-zA-Z0-9_-]{0,62}$")
    volumeGroup: str = Field(default="pve", pattern=r"^[a-zA-Z0-9_-]{1,63}$")
    thinPool: str = Field(default="data", pattern=r"^[a-zA-Z0-9_-]{1,63}$")
    projects: list[str]
    vmids: list[int] = Field(default_factory=list)
    minCores: int = 1
    maxCores: int = 2
    minMemoryMiB: int = 128
    maxMemoryMiB: int = 512
    minDiskGiB: int = 1
    maxDiskGiB: int = 8
    reserveMemoryMiB: int = 3072
    reserveStorageGiB: int = 24
    maxCommittedGiB: int = 320
    maxMetadataPercent: float = 70.0
    maxDataPercent: float = 80.0
    readiness: Literal["hardware-only"] = "hardware-only"


@dataclass
class Settings:
    origin: str
    pve_url: str
    db_path: Path
    pve_ca_pem: str = field(default="", repr=False)
    allowed_nodes: tuple[str, ...] = ()
    protected_vmids: tuple[int, ...] = (110, 120, 121, 122)
    control_vmid: int = 110
    profiles: tuple[Profile, ...] = ()
    dependencies: dict[int, list[str]] = field(default_factory=dict)
    pve_web_url: str = ""
    grafana_url: str = ""
    resource_max_cores: int = 6
    resource_max_memory_mib: int = 6144
    reserve_memory_mib: int = 3072
    capacity_token_id: str = ""
    capacity_token_secret: str = field(default="", repr=False)
    capacity_role: str = "HomelabMetrics"

    def __post_init__(self):
        for address, allow_path in (
            (self.origin, False),
            (self.pve_url, False),
            (self.pve_web_url, True),
            (self.grafana_url, True),
        ):
            if not address:
                continue
            parts = urlsplit(address)
            if (
                parts.scheme != "https"
                or not parts.hostname
                or parts.username
                or parts.password
                or parts.query
                or parts.fragment
                or (not allow_path and parts.path not in ("", "/"))
                or "\\" in address
                or any(ord(character) < 33 for character in address)
            ):
                raise ValueError("fixed HTTPS origin required")
        self.origin = self.origin.rstrip("/")
        self.pve_url = self.pve_url.rstrip("/")
        if not self.allowed_nodes or any(
            not re.fullmatch(r"[A-Za-z0-9-]{1,63}", n) for n in self.allowed_nodes
        ):
            raise ValueError("allowed nodes required")
        if any(p.node not in self.allowed_nodes for p in self.profiles):
            raise ValueError("profile node outside allowlist")
        if self.capacity_token_id and not re.fullmatch(
            r"[A-Za-z0-9_.-]+@[A-Za-z0-9_.-]+![A-Za-z0-9_.-]+", self.capacity_token_id
        ):
            raise ValueError("invalid capacity token identity")

    @classmethod
    def from_env(cls):
        return cls(
            origin=os.environ["PLATFORM_ORIGIN"],
            pve_url=os.environ["PVE_URL"],
            pve_ca_pem=os.environ["PVE_CA_PEM"],
            db_path=Path(os.getenv("CONTROL_DB_PATH", "/var/lib/homelab-control/control.sqlite3")),
            allowed_nodes=tuple(os.environ["CONTROL_ALLOWED_NODES"].split(",")),
            protected_vmids=tuple(
                int(v) for v in os.getenv("CONTROL_PROTECTED_VMIDS", "110,120,121,122").split(",")
            ),
            control_vmid=int(os.getenv("CONTROL_VM_ID", "110")),
            profiles=tuple(
                Profile.model_validate(p)
                for p in json.loads(os.getenv("CONTROL_PROFILES_JSON", "[]"))
            ),
            dependencies={
                int(k): v
                for k, v in json.loads(os.getenv("CONTROL_DEPENDENCIES_JSON", "{}")).items()
            },
            pve_web_url=os.getenv("PVE_WEB_URL", ""),
            grafana_url=os.getenv("GRAFANA_URL", ""),
            capacity_token_id=os.getenv("PVE_CAPACITY_TOKEN_ID", ""),
            capacity_token_secret=os.getenv("PVE_CAPACITY_TOKEN_SECRET", ""),
            capacity_role=os.getenv("PVE_CAPACITY_ROLE", "HomelabMetrics"),
        )
