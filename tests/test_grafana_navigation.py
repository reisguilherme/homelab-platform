"""Dashboards distinguish host allocation, guest pressure and physical storage."""

import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
DASHBOARDS = ROOT / "deploy/observability/grafana/dashboards"


def dashboard(name):
    return json.loads((DASHBOARDS / f"{name}.json").read_text(encoding="utf-8"))


def expressions(name):
    return [t["expr"] for p in dashboard(name)["panels"] for t in p.get("targets", [])]


def test_drilldowns_are_provisioned_and_linked_without_new_datasources():
    names = ("infrastructure", "vms", "disks", "services")
    uids = {dashboard(name)["uid"] for name in names}
    for name in names:
        data = dashboard(name)
        assert uids == {link["url"].split("/")[2] for link in data["links"]}
        for panel in data["panels"]:
            assert panel["fieldConfig"]["defaults"]["noValue"] == "Sem dados"
            if panel.get("targets"):
                assert panel["datasource"]["uid"] == "homelab-prometheus"
        assert len({p["id"] for p in data["panels"]}) == len(data["panels"])


def test_dashboard_titles_identify_each_navigation_destination():
    titles = {
        "infrastructure": "Homelab · Visão geral",
        "vms": "Homelab · VMs · CPU e memória",
        "disks": "Homelab · Discos e espaço",
        "services": "Homelab · Serviços e alertas",
    }
    for name, title in titles.items():
        assert dashboard(name)["title"] == title


def test_units_and_dense_filesystem_states_remain_readable():
    for name in ("infrastructure", "services"):
        for panel in dashboard(name)["panels"]:
            if "dias restantes" in panel["title"]:
                assert panel["fieldConfig"]["defaults"]["unit"] == "suffix: dias"
    access = next(p for p in dashboard("disks")["panels"] if p["id"] == 8)
    assert access["type"] == "table"
    assert access["targets"][0]["instant"] is True
    mappings = access["fieldConfig"]["defaults"]["mappings"][0]["options"]
    assert mappings["1"]["text"] == "Somente leitura"


def test_memory_uses_available_and_keeps_host_and_guest_accounting_separate():
    queries = expressions("vms")
    assert any("MemTotal_bytes" in q and "MemAvailable_bytes" in q for q in queries)
    assert any("MemFree_bytes" in q for q in queries)
    assert any("Cached_bytes" in q and "SReclaimable_bytes" in q for q in queries)
    assert any("node_pressure_memory" in q for q in queries)
    assert all(not ("homelab_pve" in q and "node_memory" in q) for q in queries)
    active = next(q for q in expressions("infrastructure") if "sum(" in q and "capacity" in q)
    assert "homelab_pve_vm_running == 1" in active
    assert "and on(node,vmid)" in active


def test_stopped_vm_is_neutral_and_missing_observation_is_not_zero():
    panels = dashboard("infrastructure")["panels"]
    state = next(p for p in panels if p["id"] == 9)
    mappings = state["fieldConfig"]["defaults"]["mappings"][0]["options"]
    assert mappings["0"]["text"] == "Parada"
    assert mappings["0"]["color"] != "red"
    for name in ("infrastructure", "vms", "disks", "services"):
        assert all("or vector(0)" not in q for q in expressions(name))


def test_physical_capacity_is_not_added_to_filesystem_or_nfs_capacity():
    queries = expressions("disks")
    assert any("homelab_storage_disk_capacity_bytes" in q for q in queries)
    assert any("homelab_storage_source_up" in q for q in queries)
    assert any("homelab_storage_disk_health" in q for q in queries)
    for query in queries:
        if "sum(" in query:
            assert "node_filesystem" not in query
            assert "homelab_storage_filesystem" not in query


def test_unused_backend_plugins_are_disabled_but_provisioned_sources_are_available():
    compose = yaml.safe_load((ROOT / "compose.observability.yaml").read_text())
    env = compose["services"]["grafana"]["environment"]
    disabled = set(env["GF_PLUGINS_DISABLE_PLUGINS"].split(","))
    assert {"tempo", "zipkin", "loki", "cloudwatch", "mysql"} <= disabled
    assert not disabled & {"prometheus", "grafana", "mixed", "dashboard", "stat", "table"}
    source = yaml.safe_load(
        (DASHBOARDS.parent / "provisioning/datasources/prometheus.yml").read_text()
    )
    assert all(ds["type"] not in disabled for ds in source["datasources"])
