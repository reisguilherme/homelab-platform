"""Safety boundaries for an offline plan; these do not prove PVE isolation."""

import copy
import importlib.util
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("bootstrap", ROOT / "scripts/proxmox_bootstrap.py")
bootstrap = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bootstrap)


@pytest.fixture
def profile():
    return json.loads((ROOT / "infrastructure/proxmox/profile.example.json").read_text())


@pytest.fixture
def inventory(profile):
    return {
        "observed_at": datetime.now(UTC).isoformat(),
        "node": profile["node"],
        "system_serial": profile["system_serial"],
        "storage": "local-lvm",
        "storage_free_gib": 348.82,
        "storage_total_gib": 348.82,
        "memory_gib": 15.49,
        "existing_vmids": [],
        "interfaces": ["lo", "nic1", "vmbr0"],
        "networks": ["192.168.77.0/24"],
    }


def test_fits_actual_budget_with_reserve(profile, inventory):
    bootstrap.validate_profile(profile)
    bootstrap.check_inventory(profile, inventory)
    assert sum(v["disk_gib"] for v in profile["vms"]) == 256
    assert sum(v["memory_mib"] for v in profile["vms"]) == 11264


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("system_serial", "OTHER-DISK", "serial"),
        ("storage", "media", "storage"),
        ("node", "another-node", "node"),
        ("storage_free_gib", 280, "reserve"),
        ("memory_gib", 13, "memory"),
        ("observed_at", "2020-01-01T00:00:00+00:00", "stale"),
        ("networks", ["172.28.0.0/16"], "overlap"),
        ("interfaces", ["lo", "vmbr0", "vmbr1"], "bridge"),
    ],
)
def test_rejects_wrong_or_insufficient_host(profile, inventory, field, value, message):
    inventory[field] = value
    with pytest.raises(ValueError, match=message):
        bootstrap.check_inventory(profile, inventory)


def test_rejects_existing_vmid_and_future_inventory(profile, inventory):
    inventory["existing_vmids"] = [profile["vms"][1]["id"]]
    with pytest.raises(ValueError, match="VM ID"):
        bootstrap.check_inventory(profile, inventory)
    inventory["existing_vmids"] = []
    inventory["observed_at"] = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    with pytest.raises(ValueError, match="future"):
        bootstrap.check_inventory(profile, inventory)


@pytest.mark.parametrize("field", ["id", "ip", "mac", "role"])
def test_rejects_duplicate_guest_identity(profile, field):
    profile["vms"][1][field] = profile["vms"][0][field]
    with pytest.raises(ValueError):
        bootstrap.validate_profile(profile)


@pytest.mark.parametrize(
    ("field", "value"),
    [("bridge", "vmbr0"), ("uplink", "vmbr1; reboot"), ("node", "../host")],
)
def test_rejects_management_bridge_and_injection(profile, field, value):
    profile[field] = value
    with pytest.raises(ValueError):
        bootstrap.validate_profile(profile)


def test_rejects_gateway_guest_and_multicast_mac(profile):
    bad = copy.deepcopy(profile)
    bad["vms"][0]["ip"] = profile["gateway"]
    with pytest.raises(ValueError):
        bootstrap.validate_profile(bad)
    profile["vms"][0]["mac"] = "01:00:00:00:00:01"
    with pytest.raises(ValueError):
        bootstrap.validate_profile(profile)


def test_firewall_blocks_private_network_before_web_and_no_edge_api(profile):
    rules = bootstrap.firewall(profile, profile["vms"][2])
    assert "policy_in: DROP" in rules and "policy_out: DROP" in rules
    assert "IN DROP -source ::/0" in rules and "OUT DROP -dest ::/0" in rules
    assert "8096" not in rules and "2049" not in rules
    for network in ("10.0.0.0/8", "100.64.0.0/10", "172.16.0.0/12", "192.168.0.0/16"):
        assert rules.index(f"OUT DROP -dest {network}") < rules.index("-dport 80,443")
    assert "[IPSET ipfilter-net0]\n172.28.64.30/32" in rules
    assert "macfilter: 1" in rules and "ipfilter: 1" in rules


def test_minimal_two_sided_application_flows(profile):
    core = bootstrap.firewall(profile, profile["vms"][0])
    playback = bootstrap.firewall(profile, profile["vms"][1])
    assert "OUT ACCEPT -dest 172.28.64.20/32 -p tcp -dport 8096" in core
    assert "IN ACCEPT -source 172.28.64.10/32 -p tcp -dport 8096" in playback
    assert "OUT ACCEPT -dest 172.28.64.10/32 -p tcp -dport 2049" in playback
    assert "IN ACCEPT -source 172.28.64.20/32 -p tcp -dport 2049" in core


def test_bundle_is_review_only_and_cloudinit_has_no_credentials(profile, tmp_path):
    # Wire-format ED25519 public key fixture (not a secret).
    key = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    bootstrap.write_bundle(profile, key, tmp_path / "bundle")
    vendor = yaml.safe_load((tmp_path / "bundle/vendor.yaml").read_text())
    assert "qemu-guest-agent" in vendor["packages"]
    assert "users" not in vendor and "ssh_authorized_keys" not in vendor
    assert vendor["ssh_pwauth"] is False
    manifest = json.loads((tmp_path / "bundle/plan.json").read_text())
    assert manifest["applied"] is False and manifest["live_preflight_passed"] is False
    commands = manifest["commands"]
    assert not any(c[0] != "qm" for c in commands)
    assert not any("start" in c or "destroy" in c for c in commands)
    assert all("/dev/" not in json.dumps(c) for c in commands)
    creates = [c for c in commands if c[1] == "create"]
    assert len(creates) == 3 and all(c[c.index("--onboot") + 1] == "0" for c in creates)
    with pytest.raises(FileExistsError):
        bootstrap.write_bundle(profile, key, tmp_path / "bundle")


def test_private_keys_rejected_without_partial_bundle(profile, tmp_path):
    with pytest.raises(ValueError, match="public"):
        bootstrap.write_bundle(profile, "-----BEGIN OPENSSH PRIVATE KEY-----", tmp_path / "bad")
    assert not (tmp_path / "bad").exists()


def test_guest_names_and_tags_identify_the_mediaserver_owner(profile):
    commands = bootstrap.commands(profile)
    creates = [command for command in commands if command[1] == "create"]
    for vm, command in zip(profile["vms"], creates, strict=True):
        assert command[2] == str(vm["id"])
        assert command[command.index("--name") + 1] == f"mediaserver-{vm['role']}"
        assert command[command.index("--tags") + 1] == "mediaserver"
        assert command[command.index("--description") + 1] == (
            f"homelab-platform bootstrap owner=mediaserver role={vm['role']}"
        )


def test_bundle_pins_distinct_cloudinit_instance_ids_without_replacing_user_or_network(
    profile, tmp_path
):
    key = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    output = tmp_path / "bundle"
    bootstrap.write_bundle(profile, key, output)
    commands = json.loads((output / "plan.json").read_text())["commands"]
    ids = []
    for vm in profile["vms"]:
        name = f"homelab-meta-{vm['id']}.yaml"
        metadata = yaml.safe_load((output / name).read_text())
        assert set(metadata) == {"instance-id"}
        assert isinstance(metadata["instance-id"], str) and metadata["instance-id"]
        ids.append(metadata["instance-id"])
        command = next(c for c in commands if c[2] == str(vm["id"]) and "--cicustom" in c)
        custom = dict(
            item.split("=", 1) for item in command[command.index("--cicustom") + 1].split(",")
        )
        assert custom == {
            "vendor": "local:snippets/homelab-vendor.yaml",
            "meta": f"local:snippets/{name}",
        }
    assert len(set(ids)) == len(profile["vms"])
    updated = copy.deepcopy(profile)
    updated["vms"][0]["cores"] += 1
    updated["vms"][0]["ip"] = "172.28.64.11"
    updated["vms"][0]["role"], updated["vms"][1]["role"] = (
        updated["vms"][1]["role"],
        updated["vms"][0]["role"],
    )
    bootstrap.write_bundle(updated, key, tmp_path / "updated")
    for vm in profile["vms"]:
        name = f"homelab-meta-{vm['id']}.yaml"
        assert (output / name).read_bytes() == (tmp_path / "updated" / name).read_bytes()


def test_nat_has_owned_symmetric_rules_and_no_management_reset(profile):
    text = bootstrap.bridge_config(profile)
    assert "auto vmbr0" not in text and "gateway " not in text
    assert "MASQUERADE" in text and "DNAT" not in text
    assert "-C POSTROUTING" in text and "-D POSTROUTING" in text
    assert "fwbr" in text and "CT --zone 1" in text
    assert "iptables -F" not in text and "ifreload" not in text


def test_spoof_guard_precedes_conntrack_on_guest_ingress_only(profile):
    text = bootstrap.bridge_config(profile)
    for vm in profile["vms"]:
        ingress = f"-m physdev --physdev-in tap{vm['id']}i0"
        source_guard = f"{ingress} ! -s {vm['ip']}/32 -j DROP"
        mac_guard = f"{ingress} -m mac ! --mac-source {vm['mac']} -j DROP"
        zone = f"-i fwbr{vm['id']}i0 -j CT --zone 1"
        assert text.index(source_guard) < text.index(zone)
        assert text.index(mac_guard) < text.index(zone)
        assert f"ip6tables -t raw -C PREROUTING {ingress} -j DROP" in text
    # physoutdev is not assigned in PREROUTING; this flag would make guards inert.
    assert "--physdev-is-bridged" not in text


def test_tagged_frames_and_foreign_mac_are_denied_at_layer_two(profile):
    text = bootstrap.bridge_config(profile)
    for vm in profile["vms"]:
        for chain in ("INPUT", "FORWARD"):
            for proto in ("802_1Q", "S-TAG"):
                rule = f"-p {proto} -i tap{vm['id']}i0 -j DROP"
                assert f"ebtables -t filter -I {chain} 1 {rule}" in text
                assert f"ebtables -t filter -D {chain} {rule}" in text
            assert f"ebtables -t filter -I {chain} 1 -s !" in text
    assert "ebtables -t filter -C" not in text  # -C changes counters in legacy ebtables.


def test_arp_sender_cannot_poison_host_or_other_guests(profile):
    text = bootstrap.bridge_config(profile)
    for vm in profile["vms"]:
        for chain in ("INPUT", "FORWARD"):
            rule = f"-p ARP -i tap{vm['id']}i0 --arp-ip-src ! {vm['ip']} -j DROP"
            assert f"ebtables -t filter -I {chain} 1 {rule}" in text
            assert f"-i tap{vm['id']}i0 --arp-mac-src !" in text
