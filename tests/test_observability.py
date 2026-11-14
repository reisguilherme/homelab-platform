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
    }
    assert stack["services"]["prometheus"]["networks"] == ["backend", "metrics"]
    assert stack["services"]["grafana"]["networks"] == ["backend"]
    for name, service in stack["services"].items():
        for forbidden in ("build", "depends_on", "network_mode", "pid", "env_file", "devices"):
            assert forbidden not in service
        assert not service.get("privileged")
        assert service["read_only"] is True
        assert service["cap_drop"] == ["ALL"]
        assert service["security_opt"] == ["no-new-privileges:true"]
        if name == "grafana":
            assert service["ports"] == ["127.0.0.1:3000:3000"]
        else:
            assert not service.get("ports")


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


def test_platform_provisions_only_shared_datasource_and_empty_dashboard_directory():
    data = load(DEPLOY / "grafana/provisioning/datasources/prometheus.yml")
    assert len(data["datasources"]) == 1
    source = data["datasources"][0]
    assert source["uid"] == "homelab-prometheus"
    assert source["url"] == "http://prometheus:9090"
    assert source["access"] == "proxy" and source["editable"] is False
    provider = load(DEPLOY / "grafana/provisioning/dashboards/default.yml")["providers"][0]
    assert provider["options"]["path"] == "/var/lib/grafana/dashboards"
    assert provider["allowUiUpdates"] is False
    assert not list((DEPLOY / "grafana/dashboards").glob("*.json"))


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
