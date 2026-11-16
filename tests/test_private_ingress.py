"""Offline private ingress safety checks; never connect to real backends."""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/render_private_ingress.py"


def renderer():
    assert SCRIPT.is_file(), "private ingress renderer is not implemented"
    spec = importlib.util.spec_from_file_location("private_ingress", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def profile():
    return {
        "TAILSCALE_IP": "100.64.20.30",
        "CORE_IP": "172.28.70.10",
        "PLAYBACK_IP": "172.28.70.11",
        "PVE_IP": "192.168.77.20",
        "PVE_TLS_NAME": "pve-fixture.example.test",
        "TLS_CERT_PATH": "/tmp/private-ingress-fixture/fullchain.pem",
        "TLS_KEY_PATH": "/tmp/private-ingress-fixture/privkey.pem",
        "PVE_CA_PATH": "/tmp/private-ingress-fixture/pve-ca.pem",
    }


def test_render_uses_only_specific_tailnet_listener_and_fixed_hosts(profile):
    text = renderer().render(profile)
    listeners = [line.strip() for line in text.splitlines() if line.strip().startswith("listen ")]
    assert len(listeners) == 10
    assert all(line.startswith("listen 100.64.20.30:443 ssl") for line in listeners)
    assert "default_server" in listeners[0]
    for name in (
        "homelab",
        "grafana",
        "proxmox",
        "radarr",
        "sonarr",
        "bazarr",
        "prowlarr",
        "qbittorrent",
        "jellyfin",
    ):
        assert f"server_name {name}.greis.dev.br;" in text
        assert f'if ($ssl_server_name != "{name}.greis.dev.br")' in text
    assert "ssl_reject_handshake on;" in text
    assert text.count("ssl_protocols TLSv1.2 TLSv1.3;") == 10
    assert "return 444;" in text
    assert "@@" not in text


@pytest.mark.parametrize(
    "field,value",
    [
        ("TAILSCALE_IP", "0.0.0.0"),
        ("TAILSCALE_IP", "127.0.0.1"),
        ("TAILSCALE_IP", "192.168.77.2"),
        ("TAILSCALE_IP", "100.100.100.100"),
        ("TAILSCALE_IP", "::"),
        ("TAILSCALE_IP", "100.64.20.30; listen 0.0.0.0:443"),
        ("CORE_IP", "8.8.8.8"),
        ("CORE_IP", "127.0.0.1"),
        ("PVE_IP", "example.com"),
        ("PVE_IP", "169.254.169.254"),
        ("PLAYBACK_IP", "8.8.8.8"),
        ("PLAYBACK_IP", "169.254.169.254"),
        ("PLAYBACK_IP", "172.28.70.11; listen 0.0.0.0:443"),
        ("PVE_TLS_NAME", "pve; proxy_ssl_verify off"),
        ("PVE_TLS_NAME", "*.example.test"),
        ("PVE_TLS_NAME", "pve\nssl_verify_client off"),
        ("TLS_CERT_PATH", "relative.pem"),
        ("TLS_CERT_PATH", "/tmp/../etc/cert.pem"),
        ("TLS_KEY_PATH", "/tmp/private key.pem"),
        ("TLS_KEY_PATH", "/tmp/key.pem; access_log /tmp/raw.log"),
        ("PVE_CA_PATH", "/tmp/$request_uri.pem"),
    ],
)
def test_rejects_untrusted_destinations_and_configuration_injection(profile, field, value):
    profile[field] = value
    with pytest.raises(ValueError):
        renderer().render(profile)


def test_rejects_missing_and_unknown_fields(profile):
    profile["UNREVIEWED_HOST"] = "streaming.greis.dev.br"
    with pytest.raises(ValueError):
        renderer().render(profile)
    del profile["UNREVIEWED_HOST"]
    del profile["TAILSCALE_IP"]
    with pytest.raises(ValueError):
        renderer().render(profile)


def test_preserves_private_backends_tls_validation_and_arr_prefixes(profile):
    text = renderer().render(profile)
    assert "proxy_pass http://127.0.0.1:8080;" in text
    assert "proxy_pass http://127.0.0.1:3080;" in text
    assert "proxy_pass https://192.168.77.20:8006;" in text
    assert "proxy_ssl_verify on;" in text
    assert "proxy_ssl_server_name on;" in text
    assert "proxy_ssl_name pve-fixture.example.test;" in text
    assert "proxy_ssl_trusted_certificate /tmp/private-ingress-fixture/pve-ca.pem;" in text
    assert "proxy_request_buffering off;" in text
    assert "client_max_body_size 32g;" in text
    assert "proxy_set_header Upgrade $http_upgrade;" in text
    for name, port in (("radarr", 7878), ("sonarr", 8989), ("bazarr", 6767), ("prowlarr", 9696)):
        assert f"return 302 https://{name}.greis.dev.br/{name}/;" in text
        assert f"location /{name}/ {{" in text
        assert f"proxy_pass http://172.28.70.10:{port};" in text
    assert "proxy_pass http://172.28.70.10:7878/;" not in text
    assert "proxy_pass http://172.28.70.10:18080;" in text
    assert "proxy_pass http://172.28.70.10:8080;" not in text
    assert "proxy_set_header Host $http_host;" in text


def test_jellyfin_uses_direct_private_playback_with_unchanged_base_path(profile):
    text = renderer().render(profile)
    block = next(
        part for part in text.split("\nserver {") if "server_name jellyfin.greis.dev.br;" in part
    )
    assert "return 302 https://jellyfin.greis.dev.br/jellyfin/;" in block
    assert "return 308 https://jellyfin.greis.dev.br/jellyfin/;" in block
    assert "location /jellyfin/ {" in block
    assert "proxy_pass http://172.28.70.11:8096;" in block
    assert "proxy_pass http://172.28.70.11:8096/;" not in block
    assert "location / { return 404; }" in block
    assert "proxy_buffering off;" in block
    assert "proxy_request_buffering off;" in block
    assert "proxy_set_header Upgrade $http_upgrade;" in block
    assert "proxy_set_header Authorization $homelab_jellyfin_authorization;" in block
    assert "auth_request" not in block


def test_no_raw_request_logs_and_no_public_or_legacy_listener(profile):
    text = renderer().render(profile)
    assert "$request_uri" not in text
    assert "log_format" not in text
    assert "$http_cookie" not in text
    assert "access_log off;" in text
    assert "error_log /dev/null crit;" in text
    assert ":8443" not in text
    assert "streaming.greis.dev.br" not in text
    assert "proxy_set_header X-Forwarded-For $remote_addr;" in text


def test_cli_writes_new_file_only_and_does_not_modify_input(profile, tmp_path):
    renderer()
    source = tmp_path / "input.json"
    source.write_text(json.dumps(profile), encoding="utf-8")
    original = source.read_bytes()
    output = tmp_path / "private.conf"
    command = [sys.executable, str(SCRIPT), "--config", str(source), "--output", str(output)]
    first = subprocess.run(command, capture_output=True, text=True, check=False)
    assert first.returncode == 0, first.stderr
    rendered = output.read_bytes()
    assert b"listen 100.64.20.30:443 ssl" in rendered
    second = subprocess.run(command, capture_output=True, text=True, check=False)
    assert second.returncode != 0
    assert output.read_bytes() == rendered
    assert source.read_bytes() == original


def test_cli_rejects_duplicate_json_keys_without_creating_output(profile, tmp_path):
    renderer()
    source = tmp_path / "input.json"
    source.write_text(json.dumps(profile)[:-1] + ', "TAILSCALE_IP": "0.0.0.0"}', encoding="utf-8")
    output = tmp_path / "private.conf"
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--config", str(source), "--output", str(output)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert not output.exists()
