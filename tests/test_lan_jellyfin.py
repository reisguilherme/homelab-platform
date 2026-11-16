"""LAN configuration never expands to a public or wildcard listener."""

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def module():
    spec = importlib.util.spec_from_file_location("lan", ROOT / "scripts/render_lan_jellyfin.py")
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def profile():
    return {
        "LAN_IP": "192.168.77.20",
        "LAN_CIDR": "192.168.77.0/24",
        "CONTROL_IP": "172.28.70.40",
        "PLAYBACK_IP": "172.28.70.20",
    }


@pytest.mark.parametrize(
    "key,value",
    [
        ("LAN_IP", "8.8.8.8"),
        ("CONTROL_IP", "0.0.0.0"),
        ("LAN_CIDR", "0.0.0.0/0"),
        ("LAN_IP", "192.168.88.20"),
        ("PLAYBACK_IP", "172.28.70.20;bad"),
    ],
)
def test_refuses_unscoped_or_injected_destination(key, value):
    config = profile() | {key: value}
    with pytest.raises(ValueError):
        module().render(config)


def test_generated_network_plan_keeps_only_lan_destination_and_existing_bridge():
    result = module().network_plan(profile())
    assert result["natRule"] == [
        "PREROUTING",
        "-i",
        "vmbr0",
        "-s",
        "192.168.77.0/24",
        "-d",
        "192.168.77.20/32",
        "-p",
        "tcp",
        "--dport",
        "8096",
        "-m",
        "comment",
        "--comment",
        "homelab-jellyfin-lan-8096",
        "-j",
        "DNAT",
        "--to-destination",
        "172.28.70.40:8096",
    ]
    assert result["firewallRule"] == (
        "IN ACCEPT -source 192.168.77.0/24 -p tcp -dport 8096 # LAN Jellyfin only"
    )
