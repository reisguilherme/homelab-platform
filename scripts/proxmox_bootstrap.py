"""Render a reviewable PVE bootstrap bundle. Never execute or apply commands."""

import argparse
import base64
import hashlib
import ipaddress
import json
import re
import struct
from datetime import UTC, datetime
from pathlib import Path

IMAGE_NAME = "ubuntu-24.04-server-cloudimg-amd64.img"
IMAGE_URL = f"https://cloud-images.ubuntu.com/releases/noble/release-20261017/{IMAGE_NAME}"
IMAGE_SHA256 = "04e8f2461a16a44e78a370284471f29616cdd9baf1893df25807b71f985b6c94"
STAGE = "/var/lib/vz/snippets"
IMAGE_PATH = f"/var/lib/vz/template/qcow/{IMAGE_NAME}"
PRIVATE = tuple(map(ipaddress.ip_network, ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")))
DENIED = (
    "0.0.0.0/8",
    "10.0.0.0/8",
    "100.64.0.0/10",
    "127.0.0.0/8",
    "169.254.0.0/16",
    "172.16.0.0/12",
    "192.0.0.0/24",
    "192.0.2.0/24",
    "192.168.0.0/16",
    "198.18.0.0/15",
    "198.51.100.0/24",
    "203.0.113.0/24",
    "224.0.0.0/4",
    "240.0.0.0/4",
)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def validate_profile(p):
    require(re.fullmatch(r"[a-z][a-z0-9-]{0,30}", p["node"]), "invalid node")
    require(p["storage"] == "local-lvm", "only authorized local-lvm storage is supported")
    require(bool(p["system_serial"].strip()), "missing system serial")
    require(re.fullmatch(r"vmbr[1-9][0-9]{0,3}", p["bridge"]), "invalid private bridge")
    require(int(p["bridge"][4:]) <= 4094, "invalid private bridge number")
    require(p["uplink"] == "vmbr0", "uplink must remain vmbr0")
    network = ipaddress.IPv4Network(p["subnet"])
    require(network.prefixlen == 24, "bootstrap subnet must be /24")
    require(any(network.subnet_of(n) for n in PRIVATE), "subnet must be RFC1918")
    gateway = ipaddress.IPv4Address(p["gateway"])
    require(gateway in network.hosts(), "gateway must be a usable subnet address")
    require(len(p["vms"]) == 3, "exactly three guests are required")
    for field in ("role", "id", "ip", "mac"):
        values = [str(v[field]).lower() for v in p["vms"]]
        require(len(set(values)) == 3, f"duplicate guest {field}")
    require({v["role"] for v in p["vms"]} == {"core", "playback", "edge"}, "invalid roles")
    for vm in p["vms"]:
        for field, minimum, maximum in (
            ("id", 100, 999999),
            ("cores", 1, 6),
            ("memory_mib", 1024, 6144),
            ("disk_gib", 16, 160),
        ):
            value = vm[field]
            require(type(value) is int and minimum <= value <= maximum, f"invalid {field}")
        address = ipaddress.IPv4Address(vm["ip"])
        require(address in network.hosts() and address != gateway, "invalid guest IP")
        require(re.fullmatch(r"(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}", vm["mac"]), "invalid MAC")
        require(int(vm["mac"][:2], 16) & 3 == 2, "MAC must be local unicast")
    for field in ("dns", "ntp"):
        require(1 <= len(p[field]) <= 3, f"invalid {field} servers")
        for value in p[field]:
            require(ipaddress.IPv4Address(value).is_global, f"{field} must use public IPv4")
    require(bool(p["blocked_egress"]), "include public management/WAN IPs in blocked_egress")
    for value in p["blocked_egress"]:
        ipaddress.IPv4Network(value)


def check_inventory(p, inventory):
    """Validate a separately collected, trusted snapshot; never collect implicitly."""
    validate_profile(p)
    observed = datetime.fromisoformat(inventory["observed_at"])
    require(observed.tzinfo is not None, "inventory timestamp needs timezone")
    age = (datetime.now(UTC) - observed).total_seconds()
    require(age >= -60, "inventory is in the future")
    require(age <= 900, "inventory is stale; collect again immediately before applying")
    for key in ("node", "system_serial", "storage"):
        require(p[key] == inventory[key], f"unexpected {key}")
    planned_ids = {v["id"] for v in p["vms"]}
    require(not planned_ids.intersection(inventory["existing_vmids"]), "VM ID already exists")
    require(p["bridge"] not in inventory["interfaces"], "private bridge already exists")
    disk = sum(v["disk_gib"] for v in p["vms"])
    require(
        inventory["storage_free_gib"] - disk >= inventory["storage_total_gib"] * 0.20,
        "insufficient thin-pool reserve (20% required)",
    )
    ram = sum(v["memory_mib"] for v in p["vms"]) / 1024
    require(inventory["memory_gib"] >= ram + 4, "insufficient memory for host and reserve")
    network = ipaddress.IPv4Network(p["subnet"])
    for value in inventory["networks"]:
        existing = ipaddress.ip_network(value)
        if existing.version == 4 and existing.prefixlen:
            require(not network.overlaps(existing), "private subnet overlaps an existing route")


def firewall(p, vm):
    peers = {v["role"]: v["ip"] for v in p["vms"]}
    lines = [
        "[OPTIONS]",
        "enable: 1",
        "policy_in: DROP",
        "policy_out: DROP",
        "macfilter: 1",
        "ipfilter: 1",
        "dhcp: 0",
        "ndp: 0",
        "radv: 0",
        "",
        "[IPSET ipfilter-net0]",
        f"{vm['ip']}/32",
        "",
        "[RULES]",
        "IN DROP -source ::/0",
        "OUT DROP -dest ::/0",
        f"IN ACCEPT -source {p['gateway']}/32 -p tcp -dport 22",
    ]
    if vm["role"] == "core":
        lines += [
            f"IN ACCEPT -source {peers['playback']}/32 -p tcp -dport 2049",
            f"OUT ACCEPT -dest {peers['playback']}/32 -p tcp -dport 8096",
        ]
    elif vm["role"] == "playback":
        lines += [
            f"IN ACCEPT -source {peers['core']}/32 -p tcp -dport 8096",
            f"OUT ACCEPT -dest {peers['core']}/32 -p tcp -dport 2049",
        ]
    # Deny before DNS/NTP too, so a management address cannot be an exception.
    lines += [f"OUT DROP -dest {n}" for n in (*DENIED, *p["blocked_egress"])]
    for address in p["dns"]:
        lines += [f"OUT ACCEPT -dest {address}/32 -p {proto} -dport 53" for proto in ("udp", "tcp")]
    lines += [f"OUT ACCEPT -dest {ip}/32 -p udp -dport 123" for ip in p["ntp"]]
    lines += ["OUT ACCEPT -dest 0.0.0.0/0 -p tcp -dport 80,443"]
    return "\n".join(lines) + "\n"


def bridge_config(p):
    lines = [
        "# Managed bootstrap fragment; management bridge is defined elsewhere.",
        f"auto {p['bridge']}",
        f"iface {p['bridge']} inet static",
        f"    address {p['gateway']}/24",
        "    bridge-ports none",
        "    bridge-stp off",
        "    bridge-fd 2",
    ]
    nat = f"-s {p['subnet']} -o {p['uplink']} -m comment --comment homelab-vm-egress -j MASQUERADE"
    rules = [("iptables", "nat", "POSTROUTING", nat)]
    for vm in p["vms"]:
        # PVE accepts ESTABLISHED before per-VM filters. Check guest-origin
        # packets before conntrack; never match traffic entering the guest.
        ingress = f"-m physdev --physdev-in tap{vm['id']}i0"
        rules += [
            ("iptables", "raw", "PREROUTING", f"{ingress} ! -s {vm['ip']}/32 -j DROP"),
            (
                "iptables",
                "raw",
                "PREROUTING",
                f"{ingress} -m mac ! --mac-source {vm['mac']} -j DROP",
            ),
            ("ip6tables", "raw", "PREROUTING", f"{ingress} -j DROP"),
            ("iptables", "raw", "PREROUTING", f"-i fwbr{vm['id']}i0 -j CT --zone 1"),
        ]
    for binary, table, chain, rule in rules:
        prefix = f"{binary} -t {table}"
        lines += [
            f"    post-up {prefix} -C {chain} {rule} || {prefix} -A {chain} {rule}",
            f"    pre-down {prefix} -D {chain} {rule} || true",
        ]
    # Legacy ebtables has no check operation (-C changes counters). Match its
    # canonical save representation instead. These rules stay outside PVEFW
    # chains and ahead of PVE hooks, covering host-bound and bridged frames.
    for vm in p["vms"]:
        mac = ":".join(f"{int(part, 16):x}" for part in vm["mac"].split(":"))
        rules = [f"-p {proto} -i tap{vm['id']}i0 -j DROP" for proto in ("802_1Q", "S-TAG")] + [
            f"-s ! {mac} -i tap{vm['id']}i0 -j DROP",
            f"-p ARP -i tap{vm['id']}i0 --arp-ip-src ! {vm['ip']} -j DROP",
            f"-p ARP -i tap{vm['id']}i0 --arp-mac-src ! {mac} -j DROP",
        ]
        for chain in ("INPUT", "FORWARD"):
            for rule in rules:
                lines += [
                    f"    post-up ebtables-save | grep -Fxq -- '-A {chain} {rule}' || "
                    f"ebtables -t filter -I {chain} 1 {rule}",
                    f"    pre-down ebtables -t filter -D {chain} {rule} || true",
                ]
    return "\n".join(lines) + "\n"


def public_key(value):
    fields = value.strip().split()
    require(len(fields) in (2, 3) and fields[0] == "ssh-ed25519", "expected ED25519 public key")
    try:
        raw = base64.b64decode(fields[1], validate=True)
        expected = struct.pack(">I", 11) + b"ssh-ed25519" + struct.pack(">I", 32)
        require(len(raw) == 51 and raw.startswith(expected), "invalid public key encoding")
    except (ValueError, TypeError) as exc:
        raise ValueError("invalid public key encoding") from exc
    return " ".join(fields[:2]) + "\n"


def commands(p):
    result = []
    for vm in p["vms"]:
        vmid = str(vm["id"])
        result.append(
            [
                "qm",
                "create",
                vmid,
                "--name",
                f"mediaserver-{vm['role']}",
                "--tags",
                "mediaserver",
                "--description",
                f"homelab-platform bootstrap owner=mediaserver role={vm['role']}",
                "--cores",
                str(vm["cores"]),
                "--sockets",
                "1",
                "--cpu",
                "x86-64-v2-AES",
                "--memory",
                str(vm["memory_mib"]),
                "--balloon",
                "0",
                "--ostype",
                "l26",
                "--scsihw",
                "virtio-scsi-pci",
                "--agent",
                "enabled=1",
                "--onboot",
                "0",
                "--ciupgrade",
                "0",
                "--net0",
                f"virtio={vm['mac']},bridge={p['bridge']},firewall=1",
            ]
        )
        result += [
            ["qm", "set", vmid, "--scsi0", f"local-lvm:0,import-from={IMAGE_PATH},discard=on"],
            ["qm", "disk", "resize", vmid, "scsi0", f"{vm['disk_gib']}G"],
            [
                "qm",
                "set",
                vmid,
                "--ide2",
                "local-lvm:cloudinit",
                "--boot",
                "order=scsi0",
                "--serial0",
                "socket",
                "--vga",
                "serial0",
                "--ciuser",
                "ubuntu",
                "--sshkeys",
                f"{STAGE}/homelab-operator.pub",
                "--ipconfig0",
                f"ip={vm['ip']}/24,gw={p['gateway']}",
                "--nameserver",
                " ".join(p["dns"]),
                "--cicustom",
                "vendor=local:snippets/homelab-vendor.yaml,"
                f"meta=local:snippets/homelab-meta-{vmid}.yaml",
            ],
        ]
    return result


def cloudinit_metadata(p, vm):
    """Pin a new guest's identity; never replace an existing guest's current ID."""
    identity = json.dumps(
        ["homelab-platform/nocloud/v1", p["system_serial"], p["node"], vm["id"]],
        separators=(",", ":"),
    )
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    return f"instance-id: homelab-{digest}\n"


def write_bundle(p, key, output):
    validate_profile(p)
    key = public_key(key)
    output.mkdir(mode=0o700, parents=False, exist_ok=False)
    vendor = {
        "ssh_pwauth": False,
        "package_update": True,
        "packages": ["qemu-guest-agent"],
        "write_files": [
            {
                "path": "/etc/systemd/timesyncd.conf.d/50-homelab.conf",
                "permissions": "0644",
                "content": "[Time]\nNTP=" + " ".join(p["ntp"]) + "\nFallbackNTP=\n",
            }
        ],
        "runcmd": [
            ["systemctl", "start", "qemu-guest-agent"],
            ["systemctl", "restart", "systemd-timesyncd"],
        ],
    }
    files = {
        "interfaces-vmbr1.conf": bridge_config(p),
        "sysctl-ipv4-forward.conf": "net.ipv4.ip_forward=1\n",
        "cluster.fw": "[OPTIONS]\nenable: 1\nebtables: 1\n",
        "host.fw": "[OPTIONS]\nenable: 0\n",
        "vendor.yaml": "#cloud-config\n" + json.dumps(vendor, indent=2) + "\n",
        "operator.pub": key,
        "plan.json": json.dumps(
            {
                "applied": False,
                "live_preflight_passed": False,
                "image_url": IMAGE_URL,
                "image_sha256": IMAGE_SHA256,
                "commands": commands(p),
            },
            indent=2,
        )
        + "\n",
    }
    files.update({f"{v['id']}.fw": firewall(p, v) for v in p["vms"]})
    files.update({f"homelab-meta-{v['id']}.yaml": cloudinit_metadata(p, v) for v in p["vms"]})
    for name, value in files.items():
        path = output / name
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(value)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profile", type=Path)
    parser.add_argument("--inventory", type=Path, help="Check a fresh snapshot, then exit")
    parser.add_argument("--public-key", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    profile = json.loads(args.profile.read_text(encoding="utf-8"))
    if args.inventory:
        require(not args.out and not args.public_key, "check and render are separate operations")
        check_inventory(profile, json.loads(args.inventory.read_text(encoding="utf-8")))
        print("Snapshot preflight passed; no commands executed. Recheck before applying.")
    else:
        require(args.out and args.public_key, "render requires --out and --public-key")
        write_bundle(profile, args.public_key.read_text(encoding="utf-8"), args.out)
        print("Review bundle rendered. No host changes; live preflight still required.")


if __name__ == "__main__":
    main()
