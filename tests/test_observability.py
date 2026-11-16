"""Shared collection must stay independent of consumer builds and private data."""

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "deploy/observability"


def load(path):
    assert path.is_file(), f"Missing observability configuration: {path.name}"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_shared_stack_never_builds_or_runs_a_consumer():
    stack = load(ROOT / "compose.observability.yaml")
    assert stack["name"] == "homelab-observability"
    assert set(stack["services"]) == {"prometheus", "grafana"}
    assert stack["networks"] == {
        "backend": {"internal": True},
        "metrics": {"name": "homelab-metrics", "internal": True},
        "scrape": {},
        "grafana-ui": {"driver": "bridge"},
    }
    assert stack["services"]["prometheus"]["networks"] == ["backend", "metrics", "scrape"]
    assert stack["services"]["grafana"]["networks"] == ["backend", "grafana-ui"]
    for name, service in stack["services"].items():
        for forbidden in ("build", "depends_on", "network_mode", "pid", "env_file", "devices"):
            assert forbidden not in service
        assert not service.get("privileged")
        assert service["read_only"] is True
        assert service["cap_drop"] == ["ALL"]
        assert service["security_opt"] == ["no-new-privileges:true"]
        if name == "grafana":
            assert service["ports"] == ["127.0.0.1:3080:3000"]
        else:
            assert service["ports"] == ["127.0.0.1:9090:9090"]


def test_grafana_loopback_publish_has_dedicated_gateway_network():
    stack = load(ROOT / "compose.observability.yaml")
    grafana = stack["services"]["grafana"]
    gateway_networks = {
        name for name in grafana["networks"] if not stack["networks"][name].get("internal", False)
    }
    # Docker does not realize published ports for internal-only containers.
    assert gateway_networks == {"grafana-ui"}
    assert grafana["ports"] == ["127.0.0.1:3080:3000"]
    assert all(
        "grafana-ui" not in service["networks"]
        for name, service in stack["services"].items()
        if name != "grafana"
    )
    assert stack["networks"]["backend"]["internal"] is True
    assert stack["networks"]["metrics"]["internal"] is True
    for name in (
        "GF_ANALYTICS_REPORTING_ENABLED",
        "GF_ANALYTICS_CHECK_FOR_UPDATES",
        "GF_ANALYTICS_CHECK_FOR_PLUGIN_UPDATES",
    ):
        assert grafana["environment"][name] == "false"
    assert grafana["environment"]["GF_PLUGINS_PREINSTALL_DISABLED"] == "true"


def test_pinned_budgets_and_local_persistence_are_preserved():
    services = load(ROOT / "compose.observability.yaml")["services"]
    assert services["prometheus"]["image"] == "prom/prometheus:v3.13.5"
    assert services["grafana"]["image"] == "grafana/grafana:13.3.1"
    assert services["prometheus"]["mem_limit"] == "512m"
    assert services["grafana"]["mem_limit"] == "384m"
    assert "--storage.tsdb.retention.time=7d" in services["prometheus"]["command"]
    assert "--storage.tsdb.retention.size=4GB" in services["prometheus"]["command"]
    for name, target in (("prometheus", "/prometheus"), ("grafana", "/var/lib/grafana")):
        data = next(m for m in services[name]["volumes"] if m["target"] == target)
        assert data["source"] == (
            "${HOMELAB_OBSERVABILITY_DIR:-/srv/appdata/homelab-observability}/" + name
        )
        assert not data.get("read_only")


def test_private_bind_allowlist_has_no_consumer_checkout_dependency():
    services = load(ROOT / "compose.observability.yaml")["services"]
    allowed = {
        "./deploy/observability/prometheus.yml",
        "./deploy/observability/rules",
        "./deploy/observability/grafana/provisioning",
        "./deploy/observability/grafana/dashboards",
        "${HOMELAB_OBSERVABILITY_DIR:-/srv/appdata/homelab-observability}/prometheus",
        "${HOMELAB_OBSERVABILITY_DIR:-/srv/appdata/homelab-observability}/grafana",
    }
    for service in services.values():
        assert not service.get("secrets")
        for mount in service["volumes"]:
            assert mount["type"] == "bind"
            assert mount["bind"]["create_host_path"] is False
            if mount["target"] == "/etc/prometheus/targets":
                assert mount["source"].startswith("${HOMELAB_PROMETHEUS_TARGETS_DIR:?")
            else:
                assert mount["source"] in allowed
            if mount["target"] not in {"/prometheus", "/var/lib/grafana"}:
                assert mount["read_only"] is True


def test_grafana_requires_its_own_credentials_without_anonymous_access():
    env = load(ROOT / "compose.observability.yaml")["services"]["grafana"]["environment"]
    for suffix in ("USER", "PASSWORD"):
        assert re.fullmatch(
            rf"\$\{{HOMELAB_GRAFANA_ADMIN_{suffix}:\?[^}}]+\}}",
            env[f"GF_SECURITY_ADMIN_{suffix}"],
        )
    assert env["GF_AUTH_ANONYMOUS_ENABLED"] == "false"
    assert env["GF_USERS_ALLOW_SIGN_UP"] == "false"
    assert env["GF_ANALYTICS_REPORTING_ENABLED"] == "false"
    assert env["GF_SERVER_SERVE_FROM_SUB_PATH"] == "${HOMELAB_GRAFANA_SERVE_FROM_SUB_PATH:-true}"
    assert "/grafana/" in env["GF_SERVER_ROOT_URL"]


def test_targets_are_private_opt_in_and_ingestion_is_bounded():
    config = load(DEPLOY / "prometheus.yml")
    assert config["global"]["scrape_interval"] == "15s"
    jobs = {job["job_name"]: job for job in config["scrape_configs"]}
    assert jobs["prometheus"]["static_configs"] == [{"targets": ["localhost:9090"]}]
    consumers = jobs["consumers"]
    assert consumers["file_sd_configs"] == [
        {
            "files": ["/etc/prometheus/targets/*.json"],
            "refresh_interval": "30s",
        }
    ]
    assert "static_configs" not in consumers
    assert consumers["sample_limit"] == 128
    assert consumers["body_size_limit"] == "1MB"
    assert consumers["honor_labels"] is False
    assert not config.get("remote_write") and not config.get("alerting")
    example = json.loads((DEPLOY / "targets/media.example.json").read_text(encoding="utf-8"))
    assert example == [{"targets": ["media-metrics:8090"], "labels": {"job": "homeserver"}}]


def test_platform_provisions_infrastructure_dashboard_without_consumer_data():
    data = load(DEPLOY / "grafana/provisioning/datasources/prometheus.yml")
    assert len(data["datasources"]) == 1
    source = data["datasources"][0]
    assert source["uid"] == "homelab-prometheus"
    assert source["url"] == "http://prometheus:9090"
    assert source["access"] == "proxy" and source["editable"] is False
    provider = load(DEPLOY / "grafana/provisioning/dashboards/default.yml")["providers"][0]
    assert provider["options"]["path"] == "/var/lib/grafana/dashboards"
    assert provider["allowUiUpdates"] is False
    dashboard = json.loads((DEPLOY / "grafana/dashboards/infrastructure.json").read_text())
    assert dashboard["uid"] == "homelab-infrastructure"
    assert dashboard["refresh"] == "30s"
    expressions = " ".join(t["expr"] for p in dashboard["panels"] for t in p["targets"])
    assert "homelab_pve_collection_up" in expressions
    assert "homelab_pve_vm_running" in expressions
    assert "homelab_pve_storage_used_bytes" in expressions
    assert "homelab_pve_recent_tasks" in expressions
    assert "or vector(0)" not in expressions
    assert all(p["fieldConfig"]["defaults"]["noValue"] == "Sem dados" for p in dashboard["panels"])


def test_control_separates_human_sessions_and_read_only_collection():
    stack = load(ROOT / "compose.control.yaml")
    assert stack["name"] == "homelab-control"
    assert set(stack["services"]) == {"control", "pve-metrics"}
    control, collector = (stack["services"][name] for name in ("control", "pve-metrics"))
    assert control["mem_limit"] == "256m" and collector["mem_limit"] == "128m"
    assert control["ports"] == ["127.0.0.1:8080:8080"]
    assert not collector.get("ports") and not collector.get("volumes")
    assert "PVE_METRICS_TOKEN_SECRET" not in control["environment"]
    assert set(collector["environment"]) == {
        "PVE_URL",
        "PVE_CA_PEM",
        "PVE_METRICS_TOKEN_ID",
        "PVE_METRICS_TOKEN_SECRET",
        "STORAGE_CORE_EXPORTER_URL",
        "STORAGE_CORE_VMID",
    }
    for service in (control, collector):
        assert service["read_only"] is True and service["cap_drop"] == ["ALL"]
        assert not service.get("privileged") and not service.get("env_file")
        assert service["logging"]["options"] == {"max-size": "10m", "max-file": "2"}
    assert stack["networks"]["metrics"] == {"external": True, "name": "homelab-metrics"}


def test_platform_scrape_rules_are_local_bounded_and_freshness_aware():
    config = load(DEPLOY / "prometheus.yml")
    job = next(j for j in config["scrape_configs"] if j["job_name"] == "homelab-pve")
    assert job["scrape_interval"] == "30s" and job["scrape_timeout"] == "5s"
    assert job["static_configs"] == [{"targets": ["homelab-pve-metrics:9101"]}]
    assert job["body_size_limit"] == "1MB" and job["sample_limit"] == 20000
    assert config["rule_files"] == ["/etc/prometheus/rules/*.yml"]
    rules = load(DEPLOY / "rules/platform.yml")["groups"][0]["rules"]
    assert {r["alert"] for r in rules} == {
        "GuestExporterUnavailable",
        "GuestStorageEvidenceMissing",
        "GuestFilesystemSpaceLow",
        "ProxmoxCollectionUnavailable",
        "ProxmoxCollectionStale",
        "ProxmoxStorageSpaceLow",
        "ProxmoxRecentTaskFailures",
    }
    assert all(r["for"] and r["annotations"]["runbook_url"] for r in rules)
    assert not config.get("alerting") and not config.get("remote_write")


def test_guest_targets_are_private_opt_in_with_documentation_addresses():
    config = load(DEPLOY / "prometheus.yml")
    job = next(j for j in config["scrape_configs"] if j["job_name"] == "guests")
    assert job["scrape_interval"] == "30s" and job["sample_limit"] == 5000
    assert job["body_size_limit"] == "5MB"
    assert job["file_sd_configs"][0]["files"] == ["/etc/prometheus/targets/guests/*.json"]
    example = json.loads((DEPLOY / "targets/guests.example.json").read_text())
    assert len(example) == 4
    assert all(target["targets"][0].startswith("192.0.2.") for target in example)
    assert {t["labels"]["project"] for t in example} == {"homelab", "mediaserver"}


def test_control_compose_renders_with_only_fixture_secrets(tmp_path):
    docker = shutil.which("docker")
    if docker is None:
        pytest.skip("Docker Compose CLI unavailable")
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(
            ("HOMELAB_", "PLATFORM_", "PVE_", "CONTROL_", "GRAFANA_", "COMPOSE_", "DOCKER_")
        )
    }
    environment["DOCKER_CONFIG"] = str(tmp_path / "docker-config")
    (tmp_path / "docker-config").mkdir()
    values = {
        "PLATFORM_ORIGIN": "https://127.0.0.1:18443",
        "PVE_URL": "https://pve.fixture.invalid:8006",
        "PVE_WEB_URL": "https://pve.fixture.invalid:8006",
        "GRAFANA_URL": "https://127.0.0.1:18443/grafana/",
        "PVE_CA_PEM": "fixture-public-certificate",
        "CONTROL_PROFILES_JSON": "[]",
        "CONTROL_PROTECTED_VMIDS": "120,121,122,130",
        "CONTROL_ALLOWED_NODES": "pve-fixture",
        "CONTROL_DEPENDENCIES_JSON": "{}",
        "PVE_METRICS_TOKEN_ID": "metrics@pve!readonly",
        "PVE_METRICS_TOKEN_SECRET": "fixture-secret-not-real",
        "HOMELAB_CONTROL_DIR": str(tmp_path / "control"),
    }
    fixture = tmp_path / "control.env"
    fixture.write_text("\n".join(f"{key}={value}" for key, value in values.items()))
    result = subprocess.run(
        [
            docker,
            "compose",
            "-p",
            "homelab-control",
            "--env-file",
            str(fixture),
            "-f",
            "compose.control.yaml",
            "config",
            "--format",
            "json",
        ],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    rendered = json.loads(result.stdout)
    assert rendered["name"] == "homelab-control"
    assert rendered["services"]["control"]["ports"][0]["host_ip"] == "127.0.0.1"
    assert "PVE_METRICS_TOKEN_SECRET" not in rendered["services"]["control"]["environment"]


@pytest.mark.parametrize(
    "missing",
    [
        None,
        "HOMELAB_GRAFANA_ADMIN_USER",
        "HOMELAB_GRAFANA_ADMIN_PASSWORD",
        "HOMELAB_PROMETHEUS_TARGETS_DIR",
    ],
)
@pytest.mark.parametrize("dashboard_override", [False, True])
def test_compose_config_uses_fixture_env_and_optional_dashboard_merge(
    tmp_path,
    missing,
    dashboard_override,
):
    docker = shutil.which("docker")
    if docker is None:
        pytest.skip("Docker Compose CLI unavailable; validation needs no daemon")
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("HOMELAB_", "HOMESERVER_", "COMPOSE_", "DOCKER_"))
    }
    environment["DOCKER_CONFIG"] = str(tmp_path / "docker-config")
    environment["COMPOSE_PROJECT_NAME"] = "conflicting-main-project"
    (tmp_path / "docker-config").mkdir()
    version = subprocess.run(
        [docker, "compose", "version"], env=environment, capture_output=True, text=True, timeout=30
    )
    if version.returncode:
        pytest.skip("Docker Compose CLI unavailable in this environment")
    values = {
        "HOMELAB_GRAFANA_ADMIN_USER": "fixture-user",
        "HOMELAB_GRAFANA_ADMIN_PASSWORD": "fixture-password-not-secret",
        "HOMELAB_PROMETHEUS_TARGETS_DIR": str(tmp_path / "targets"),
        "HOMELAB_OBSERVABILITY_DIR": str(tmp_path / "data"),
    }
    if missing:
        values.pop(missing)
    fixture = tmp_path / "fixture.env"
    fixture.write_text(
        "\n".join(f"{key}={value}" for key, value in values.items()), encoding="utf-8"
    )
    command = [
        docker,
        "compose",
        "-p",
        "homelab-observability",
        "--env-file",
        str(fixture),
        "-f",
        "compose.observability.yaml",
    ]
    if dashboard_override:
        override = tmp_path / "compose.dashboards.yaml"
        override.write_text(
            yaml.safe_dump(
                {
                    "services": {
                        "grafana": {
                            "volumes": [
                                {
                                    "type": "bind",
                                    "source": str(tmp_path / "dashboards"),
                                    "target": "/var/lib/grafana/dashboards",
                                    "read_only": True,
                                    "bind": {"create_host_path": False},
                                }
                            ]
                        }
                    }
                }
            ),
            encoding="utf-8",
        )
        command.extend(["-f", str(override)])
    result = subprocess.run(
        [*command, "config", "--format", "json"],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if missing:
        assert result.returncode != 0
        assert missing in result.stderr
    else:
        assert result.returncode == 0, result.stderr
        rendered = json.loads(result.stdout)
        assert rendered["name"] == "homelab-observability"
        assert set(rendered["services"]) == {"grafana", "prometheus"}
        if dashboard_override:
            mounts = [
                m
                for m in rendered["services"]["grafana"]["volumes"]
                if m["target"] == "/var/lib/grafana/dashboards"
            ]
            assert len(mounts) == 1
            assert mounts[0]["source"].replace("\\", "/").endswith("/dashboards")
            assert mounts[0]["read_only"] is True
