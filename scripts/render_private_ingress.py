"""Render a private Nginx include; never install it or change a running service."""

import argparse
import ipaddress
import json
import re
import sys
from pathlib import Path, PurePosixPath

TEMPLATE = (
    Path(__file__).resolve().parents[1]
    / "infrastructure/control/private-domains.nginx.conf.template"
)
TAILNET = ipaddress.IPv4Network("100.64.0.0/10")
PRIVATE = tuple(
    ipaddress.IPv4Network(value) for value in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
)
FIELDS = {
    "TAILSCALE_IP",
    "CORE_IP",
    "PLAYBACK_IP",
    "PVE_IP",
    "PVE_TLS_NAME",
    "TLS_CERT_PATH",
    "TLS_KEY_PATH",
    "PVE_CA_PATH",
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def validate(config):
    require(isinstance(config, dict) and set(config) == FIELDS, "unexpected configuration fields")
    require(all(isinstance(value, str) for value in config.values()), "fields must be strings")
    tail = ipaddress.IPv4Address(config["TAILSCALE_IP"])
    require(
        tail in TAILNET
        and tail not in (TAILNET.network_address, TAILNET.broadcast_address)
        and str(tail) != "100.100.100.100",
        "listener must be a specific Tailscale IPv4 address",
    )
    for field in ("CORE_IP", "PLAYBACK_IP", "PVE_IP"):
        value = ipaddress.IPv4Address(config[field])
        require(any(value in network for network in PRIVATE), "upstreams must be RFC1918 IPv4")
    name = config["PVE_TLS_NAME"]
    require(
        len(name) <= 253
        and re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?", name)
        and all(
            len(label) <= 63 and label and not label.startswith("-") and not label.endswith("-")
            for label in name.split(".")
        ),
        "invalid upstream TLS name",
    )
    for field in ("TLS_CERT_PATH", "TLS_KEY_PATH", "PVE_CA_PATH"):
        path = config[field]
        require(
            1 < len(path) <= 1024
            and re.fullmatch(r"/[A-Za-z0-9_./-]+", path)
            and str(PurePosixPath(path)) == path
            and ".." not in PurePosixPath(path).parts
            and not path.endswith("/"),
            "certificate paths must be absolute normalized Linux paths",
        )
    require(config["TLS_CERT_PATH"] != config["TLS_KEY_PATH"], "certificate and key must differ")


def render(config: dict) -> str:
    validate(config)
    text = TEMPLATE.read_text(encoding="utf-8")
    require(
        set(re.findall(r"@@([A-Z_]+)@@", text)) == FIELDS, "template fields do not match schema"
    )
    for field, value in config.items():
        text = text.replace(f"@@{field}@@", value)
    require("@@" not in text, "unresolved template placeholder")
    return text


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "duplicate JSON field")
        result[key] = value
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path, help="private JSON input")
    parser.add_argument("--output", required=True, type=Path, help="new configuration file")
    args = parser.parse_args(argv)
    try:
        config = json.loads(
            args.config.read_text(encoding="utf-8"), object_pairs_hook=unique_object
        )
        text = render(config)
        with args.output.open("x", encoding="utf-8", newline="\n") as output:
            output.write(text)
    except (ValueError, OSError):
        print(
            "Cannot render: invalid input, unreadable template, or output already exists.",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
