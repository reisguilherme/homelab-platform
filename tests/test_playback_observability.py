"""Consumer availability must remain distinct from reachable guest exporters."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
RULES = ROOT / "deploy/observability/rules/playback.yml"
FIXTURE = ROOT / "tests/fixtures/playback-alerts.yml"
SELECTOR = '{job="guests",role="playback"}'


def test_playback_alerts_observe_application_admission_and_collection_age():
    assert RULES.is_file(), "playback availability alerts are missing"
    rules = yaml.safe_load(RULES.read_text())["groups"][0]["rules"]
    assert {rule["alert"] for rule in rules} == {
        "PlaybackJellyfinUnavailable",
        "PlaybackStorageAdmissionRefused",
        "PlaybackCollectorStale",
    }
    for rule in rules:
        assert rule["for"] == "1m"
        assert SELECTOR in rule["expr"]
        assert "absent(" in rule["expr"]
        assert rule["annotations"]["runbook_url"].endswith("/docs/runbooks/playback-health.md")


def test_playback_dashboard_preserves_unknown_and_requires_fresh_observation():
    dashboard = json.loads(
        (ROOT / "deploy/observability/grafana/dashboards/infrastructure.json").read_text()
    )
    panels = {panel["id"]: panel for panel in dashboard["panels"] if panel["id"] in (23, 24, 25)}
    assert set(panels) == {23, 24, 25}, "playback availability panels are missing"
    for panel in panels.values():
        assert panel["fieldConfig"]["defaults"]["noValue"] == "Sem dados"
        expression = panel["targets"][0]["expr"]
        assert SELECTOR in expression
        assert "or vector(0)" not in expression
        assert "homeserver_playback_observed_timestamp_seconds" in expression
    for panel_id in (23, 24):
        expression = panels[panel_id]["targets"][0]["expr"]
        assert "<= 60" in expression and ">= 0" in expression
        assert 'up{job="guests",role="playback"} == 1' in expression
    assert panels[25]["fieldConfig"]["defaults"]["unit"] == "s"
    # The executable fixture evaluates the queries actually provisioned in Grafana.
    # A changed dashboard must still prove the same concrete fixture outcomes.
    queries = [panels[number]["targets"][0]["expr"] for number in (23, 24, 25)]
    fixture = yaml.safe_load(FIXTURE.read_text())
    for group in fixture["tests"]:
        assert [case["expr"] for case in group["promql_expr_test"]] == queries


def test_playback_alert_and_dashboard_expressions_with_promtool():
    promtool = shutil.which("promtool")
    if promtool:
        command = [promtool, "test", "rules", str(FIXTURE)]
    else:
        docker = shutil.which("docker")
        if not docker:
            pytest.skip("promtool and Docker unavailable; keep the executable rule fixture")
        image = "prom/prometheus:v3.13.5"
        found = subprocess.run(
            [docker, "image", "inspect", image], capture_output=True, timeout=15, check=False
        )
        if found.returncode:
            pytest.skip("promtool and pinned local Prometheus image unavailable")
        command = [
            docker,
            "run",
            "--rm",
            "--network",
            "none",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--entrypoint",
            "/bin/promtool",
            "--mount",
            f"type=bind,src={ROOT},dst=/work,readonly",
            "--workdir",
            "/work",
            image,
            "test",
            "rules",
            "tests/fixtures/playback-alerts.yml",
        ]
    result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
