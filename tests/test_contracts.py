"""Exercise the offline validator using isolated JSON documents and the real CLI."""

import copy
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def service():
    return {
        "apiVersion": "homelab/v1",
        "id": "example-app",
        "repository": "https://github.com/example/example-app",
        "runtime": "compose-vm",
        "resources": {"cpu": 2, "memoryMiB": 1024, "gpu": "none"},
        "network": {
            "administration": "private",
            "inheritPlatformPrivileges": False,
            "exposure": "private",
            "ingress": [],
            "egress": [],
        },
        "storage": [
            {
                "id": "database",
                "mountPath": "/var/lib/example",
                "kind": "local-block",
                "access": "rw",
                "purpose": "database",
                "requestedGiB": 10,
            }
        ],
        "telemetry": {"metricsPath": None, "healthcheckPath": "/health/live"},
        "secrets": ["EXAMPLE_API_TOKEN"],
        "recovery": {
            "authority": "consumer",
            "runbookPath": "docs/recovery.md",
            "requiresStorageReady": True,
            "preserveOperatorPauses": True,
        },
    }


@pytest.fixture
def catalog():
    return {
        "apiVersion": "homelab/v1",
        "services": [
            {
                "id": "example-app",
                "repository": "https://github.com/example/example-app",
                "commit": "a" * 40,
                "contractPath": "platform.contract.json",
                "manifestPaths": ["compose.yaml"],
                "status": "proposed",
            }
        ],
    }


def run_validator(tmp_path, kind, document):
    path = tmp_path / "fixture.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    before = {item.name: item.read_bytes() for item in tmp_path.iterdir()}
    result = subprocess.run(
        [sys.executable, "-B", str(ROOT / "scripts/validate.py"), kind, str(path)],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        env={**os.environ, "http_proxy": "http://127.0.0.1:1", "https_proxy": "http://127.0.0.1:1"},
        timeout=10,
        check=False,
    )
    assert {item.name: item.read_bytes() for item in tmp_path.iterdir()} == before
    return result


def test_valid_service_accepts_declared_resources_without_writing(tmp_path, service):
    result = run_validator(tmp_path, "service", service)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("password", "SECRET-SENTINEL-DO-NOT-PRINT"),
        ("apiVersion", "homelab/v2"),
        ("runtime", "bare-metal"),
        ("secrets", {"API_TOKEN": "SECRET-SENTINEL-DO-NOT-PRINT"}),
        ("secrets", ["token=value"]),
        ("secrets", ["TOKEN_FILE"]),
        ("repository", "https://user:SECRET-SENTINEL-DO-NOT-PRINT@github.com/a/b"),
    ],
)
def test_invalid_service_fields_rejected_without_values(tmp_path, service, field, value):
    service[field] = value
    result = run_validator(tmp_path, "service", service)
    assert result.returncode == 1
    assert "SECRET-SENTINEL-DO-NOT-PRINT" not in result.stdout + result.stderr


@pytest.mark.parametrize(
    ("section", "field", "value"),
    [
        ("resources", "cpu", -1),
        ("resources", "memoryMiB", -1),
        ("resources", "memoryMiB", 1.5),
        ("resources", "extra", True),
        ("network", "administration", "public"),
        ("network", "inheritPlatformPrivileges", True),
        ("network", "allowGlobalAdmin", True),
        ("telemetry", "healthcheckPath", "../private/env"),
        ("telemetry", "metricsPath", "/metrics?token=secret"),
        ("telemetry", "metricsPort", 8090),
        ("telemetry", "healthcheckPort", 65536),
        ("recovery", "runbookPath", "docs/../../env"),
        ("recovery", "requiresStorageReady", False),
        ("recovery", "preserveOperatorPauses", False),
    ],
)
def test_unsafe_service_declarations_rejected(tmp_path, service, section, field, value):
    service[section][field] = value
    assert run_validator(tmp_path, "service", service).returncode == 1


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("kind", "network-share"),
        ("kind", "mergerfs"),
        ("access", "ro"),
        ("mountPath", "/srv/../private"),
        ("mountPath", "/../private"),
        ("mountPath", "C:\\private"),
        ("mountPath", "/"),
        ("mountPath", "/srv//data"),
        ("requestedGiB", 0),
        ("requestedGiB", -1),
    ],
)
def test_database_requires_local_writable_storage_and_safe_path(tmp_path, service, field, value):
    service["storage"][0][field] = value
    assert run_validator(tmp_path, "service", service).returncode == 1


def test_duplicate_storage_ids_rejected(tmp_path, service):
    duplicate = copy.deepcopy(service["storage"][0])
    duplicate["mountPath"] = "/srv/other"
    service["storage"].append(duplicate)
    assert run_validator(tmp_path, "service", service).returncode == 1


def test_http_telemetry_and_named_network_dependencies_accepted(tmp_path, service):
    service["telemetry"] = {
        "metricsPath": "/metrics",
        "metricsPort": 8090,
        "healthcheckPath": "/health/live",
        "healthcheckPort": 8080,
    }
    service["network"]["ingress"] = [
        {"port": 8090, "protocol": "tcp", "scope": "private", "purpose": "metrics"}
    ]
    service["network"]["egress"] = [{"dependency": "metadata-api", "port": 443, "protocol": "tcp"}]
    assert run_validator(tmp_path, "service", service).returncode == 0


@pytest.mark.parametrize("purpose", ["administration", "metrics"])
def test_public_administration_and_metrics_ingress_rejected(tmp_path, service, purpose):
    service["network"]["ingress"] = [
        {"port": 8090, "protocol": "tcp", "scope": "public", "purpose": purpose}
    ]
    assert run_validator(tmp_path, "service", service).returncode == 1


def test_catalog_accepts_proposed_and_empty_without_fetching_repositories(tmp_path, catalog):
    assert run_validator(tmp_path, "catalog", catalog).returncode == 0
    catalog["services"] = []
    assert run_validator(tmp_path, "catalog", catalog).returncode == 0


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("commit", "main"),
        ("commit", "a" * 39),
        ("commit", "g" * 40),
        ("contractPath", "../platform.contract.json"),
        ("contractPath", "https://example.com/contract.json"),
        ("manifestPaths", ["/etc/private"]),
        ("manifestPaths", ["docs\\..\\private"]),
        ("manifestPaths", ["./compose.yaml"]),
        ("manifestPaths", ["compose.yaml", "compose.yaml"]),
        ("status", "ready"),
        ("admin", True),
    ],
)
def test_catalog_rejects_mutable_refs_and_unsafe_registration(tmp_path, catalog, field, value):
    catalog["services"][0][field] = value
    assert run_validator(tmp_path, "catalog", catalog).returncode == 1


def test_catalog_rejects_missing_commit(tmp_path, catalog):
    del catalog["services"][0]["commit"]
    assert run_validator(tmp_path, "catalog", catalog).returncode == 1


def test_catalog_rejects_duplicate_ids_even_with_different_commits(tmp_path, catalog):
    duplicate = copy.deepcopy(catalog["services"][0])
    duplicate["commit"] = "b" * 40
    catalog["services"].append(duplicate)
    assert run_validator(tmp_path, "catalog", catalog).returncode == 1


def test_malformed_json_and_missing_file_have_safe_errors(tmp_path):
    path = tmp_path / "malformed.json"
    path.write_text('{"secret":"SECRET-SENTINEL-DO-NOT-PRINT",}', encoding="utf-8")
    for candidate in (path, tmp_path / "missing.json"):
        result = subprocess.run(
            [sys.executable, "-B", str(ROOT / "scripts/validate.py"), "service", str(candidate)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 1
        assert "SECRET-SENTINEL-DO-NOT-PRINT" not in result.stdout + result.stderr
        assert "Traceback" not in result.stderr


def test_duplicate_json_keys_rejected(tmp_path):
    path = tmp_path / "duplicate.json"
    path.write_text('{"apiVersion":"homelab/v1","apiVersion":"homelab/v2"}', encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-B", str(ROOT / "scripts/validate.py"), "catalog", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1


def test_shipped_template_and_catalog_are_valid(tmp_path):
    for kind, relative in (
        ("service", "templates/service.contract.json"),
        ("catalog", "catalog/services.json"),
    ):
        document = json.loads((ROOT / relative).read_text(encoding="utf-8"))
        result = run_validator(tmp_path, kind, document)
        assert result.returncode == 0, result.stderr


def test_validation_works_with_socket_access_denied(tmp_path, service, catalog):
    runner = """
import runpy
import socket
import sys

def denied(*args, **kwargs):
    raise AssertionError("validation attempted network access")

socket.socket = denied
socket.create_connection = denied
socket.getaddrinfo = denied
script = sys.argv.pop(1)
runpy.run_path(script, run_name="__main__")
"""
    for kind, document in (("service", service), ("catalog", catalog)):
        path = tmp_path / f"{kind}.json"
        path.write_text(json.dumps(document), encoding="utf-8")
        result = subprocess.run(
            [
                sys.executable,
                "-B",
                "-c",
                runner,
                str(ROOT / "scripts/validate.py"),
                kind,
                str(path),
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        assert result.returncode == 0, result.stderr
