"""Render a separate LAN-only Jellyfin proxy and exact additive network plan."""

import argparse
import ipaddress
import json
import shlex
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIELDS = {"LAN_IP", "LAN_CIDR", "CONTROL_IP", "PLAYBACK_IP"}
PRIVATE = tuple(
    ipaddress.IPv4Network(value) for value in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
)


def validate(config):
    if not isinstance(config, dict) or set(config) != FIELDS:
        raise ValueError("invalid LAN fields")
    network = ipaddress.IPv4Network(config["LAN_CIDR"])
    if not any(network.subnet_of(item) for item in PRIVATE) or network.prefixlen < 24:
        raise ValueError("LAN must be a bounded private subnet")
    for field in ("LAN_IP", "CONTROL_IP", "PLAYBACK_IP"):
        address = ipaddress.IPv4Address(config[field])
        if not any(address in item for item in PRIVATE):
            raise ValueError("specific RFC1918 address required")
        if field == "LAN_IP" and (
            address not in network
            or address in (network.network_address, network.broadcast_address)
        ):
            raise ValueError("LAN address outside subnet")


def render(config):
    validate(config)
    text = (ROOT / "infrastructure/control/lan-jellyfin.nginx.conf.template").read_text()
    for field, value in config.items():
        text = text.replace(f"@@{field}@@", value)
    if "@@" in text:
        raise ValueError("unresolved placeholder")
    return text


def network_plan(config):
    validate(config)
    rule = [
        "PREROUTING",
        "-i",
        "vmbr0",
        "-s",
        config["LAN_CIDR"],
        "-d",
        config["LAN_IP"] + "/32",
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
        config["CONTROL_IP"] + ":8096",
    ]
    check = shlex.join(["iptables", "-w", "5", "-t", "nat", "-C", *rule])
    add = shlex.join(["iptables", "-w", "5", "-t", "nat", "-A", *rule])
    remove = shlex.join(["iptables", "-w", "5", "-t", "nat", "-D", *rule])
    return {
        "natRule": rule,
        "firewallRule": (
            f"IN ACCEPT -source {config['LAN_CIDR']} -p tcp -dport 8096 # LAN Jellyfin only"
        ),
        "hooks": [f"    post-up {check} || {add}", f"    pre-down {remove} || true"],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    with args.output.open("x", encoding="utf-8") as stream:
        stream.write(render(config))
    print(json.dumps(network_plan(config)))


if __name__ == "__main__":
    main()
