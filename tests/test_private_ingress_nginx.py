"""Opt-in Nginx fixture: isolated container, synthetic TLS/backends, no published ports."""

import importlib.util
import json
import os
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
IMAGE = "nginx@sha256:a8b39bd9cf0f83869a2162827a0caf6137ddf759d50a171451b335cecc87d236"
pytestmark = pytest.mark.skipif(
    os.environ.get("HOMELAB_TEST_PRIVATE_NGINX") != "1",
    reason="requires opt-in local Docker/OpenSSL fixture; never uses the real server",
)


def command(*args, check=True):
    result = subprocess.run(args, text=True, capture_output=True, check=False, timeout=30)
    if check:
        assert result.returncode == 0, result.stderr
    return result


@pytest.fixture(scope="module")
def ingress(tmp_path_factory):
    assert shutil.which("docker") and shutil.which("openssl"), "Docker and OpenSSL required"
    command("docker", "image", "inspect", IMAGE)
    folder = tmp_path_factory.mktemp("private-ingress-nginx")
    names = [
        f"{name}.greis.dev.br"
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
        )
    ]
    command(
        "openssl",
        "req",
        "-x509",
        "-newkey",
        "rsa:2048",
        "-nodes",
        "-days",
        "1",
        "-subj",
        "/CN=private-ingress-fixture",
        "-addext",
        "subjectAltName=" + ",".join(f"DNS:{name}" for name in names + ["pve.fixture.test"]),
        "-keyout",
        str(folder / "key.pem"),
        "-out",
        str(folder / "cert.pem"),
    )
    spec = importlib.util.spec_from_file_location(
        "private_ingress_fixture", ROOT / "scripts/render_private_ingress.py"
    )
    renderer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(renderer)
    text = renderer.render(
        {
            "TAILSCALE_IP": "100.64.20.30",
            "CORE_IP": "172.28.70.10",
            "PLAYBACK_IP": "172.28.70.11",
            "PVE_IP": "192.168.77.20",
            "PVE_TLS_NAME": "pve.fixture.test",
            "TLS_CERT_PATH": "/fixture/cert.pem",
            "TLS_KEY_PATH": "/fixture/key.pem",
            "PVE_CA_PATH": "/fixture/cert.pem",
        }
    )
    # Validate the untouched production render before adapting the isolated fixture transport.
    (folder / "syntax.conf").write_text(
        "pid /tmp/nginx.pid; error_log /dev/stderr; events {} http {\n" + text + "}\n"
    )
    base = [
        "docker",
        "run",
        "--rm",
        "--network",
        "none",
        "--read-only",
        "--tmpfs",
        "/var/cache/nginx",
        "--tmpfs",
        "/tmp",
        "--mount",
        f"type=bind,src={folder},dst=/fixture,readonly",
        "--entrypoint",
        "nginx",
    ]
    command(
        *base, "--sysctl", "net.ipv4.ip_nonlocal_bind=1", IMAGE, "-t", "-c", "/fixture/syntax.conf"
    )
    text = text.replace("100.64.20.30:443", "127.0.0.1:10443")
    text = text.replace("172.28.70.10:", "127.0.0.1:")
    text = text.replace("172.28.70.11:", "127.0.0.1:")
    text = text.replace("192.168.77.20:", "127.0.0.1:")
    # Clone the rendered Proxmox vhost with an intentionally wrong expected SAN.
    pve_block = next(
        block for block in text.split("\nserver {") if "server_name proxmox.greis.dev.br;" in block
    )
    text += "\nserver {" + pve_block.replace("127.0.0.1:10443", "127.0.0.1:11443").replace(
        "proxy_ssl_name pve.fixture.test;", "proxy_ssl_name wrong-name.fixture.test;"
    )
    body = (
        '{"uri":"$request_uri","host":"$host","forwarded_for":"$http_x_forwarded_for",'
        '"origin":"$http_origin","upgrade":"$http_upgrade","length":"$http_content_length",'
        '"http_host":"$http_host","referer":"$http_referer","cookie":"$http_cookie",'
        '"authorization":"$http_authorization","emby_token":"$http_x_emby_token",'
        '"forwarded_proto":"$http_x_forwarded_proto","forwarded_port":"$http_x_forwarded_port"}'
    )
    for port in (8080, 3080, 7878, 8989, 6767, 9696, 8006, 18080):
        tls = (
            " ssl; ssl_certificate /fixture/cert.pem; ssl_certificate_key /fixture/key.pem;"
            if port == 8006
            else ";"
        )
        text += (
            f"server {{ listen 127.0.0.1:{port}{tls} access_log off; error_log /dev/null crit; "
            f"client_max_body_size 32g; location / {{ return 200 '{body}'; }} }}\n"
        )
    # Serve synthetic bytes to prove a Range request crosses both proxy hops intact.
    folder.chmod(0o755)
    (folder / "media.bin").write_bytes(bytes(range(256)) * 256)
    (folder / "media.bin").chmod(0o644)
    text += (
        "server { listen 127.0.0.1:8096; access_log off; error_log /dev/null crit; "
        "add_header X-Fixture-Authorization $http_authorization always; "
        "add_header X-Fixture-Upgrade $http_upgrade always; "
        "add_header X-Fixture-Host $host always; "
        "add_header X-Fixture-Uri $request_uri always; "
        "add_header X-Fixture-Emby-Authorization $http_x_emby_authorization always; "
        "add_header X-Fixture-Emby-Token $http_x_emby_token always; "
        "add_header X-Fixture-MediaBrowser-Token $http_x_mediabrowser_token always; "
        "location = /jellyfin/fixture-media.bin { alias /fixture/media.bin; } "
        f"location / {{ return 200 '{body}'; }} }}\n"
    )
    (folder / "runtime.conf").write_text(
        "pid /tmp/nginx.pid; error_log /dev/stderr; events {} http {\n" + text + "}\n"
    )
    (folder / "body.bin").write_bytes(b"fixture" * 10000)
    name = "homelab-private-ingress-fixture-" + uuid.uuid4().hex[:10]
    try:
        command(
            *base[:2],
            "--detach",
            "--name",
            name,
            *base[2:],
            IMAGE,
            "-c",
            "/fixture/runtime.conf",
            "-g",
            "daemon off;",
        )
        yield name
    finally:
        command("docker", "rm", "-f", name, check=False)


def request(ingress, host, path="/", extra=(), check=True, port=10443):
    return command(
        "docker",
        "exec",
        ingress,
        "curl",
        "--silent",
        "--show-error",
        "--max-time",
        "5",
        "--noproxy",
        "*",
        "--cacert",
        "/fixture/cert.pem",
        "--resolve",
        f"{host}:{port}:127.0.0.1",
        *extra,
        f"https://{host}:{port}{path}",
        check=check,
    )


@pytest.mark.parametrize("host", ["homelab", "grafana", "proxmox", "qbittorrent"])
def test_tls_proxy_routes_with_canonical_headers(ingress, host):
    response = request(
        ingress,
        f"{host}.greis.dev.br",
        "/fixture?token=synthetic-only",
        extra=("-H", "X-Forwarded-For: 203.0.113.70", "-H", "Origin: https://fixture.example.test"),
    )
    result = json.loads(response.stdout)
    assert result["uri"] == "/fixture?token=synthetic-only"
    assert result["host"] == f"{host}.greis.dev.br"
    assert result["forwarded_for"] == "127.0.0.1"
    assert result["origin"] == "https://fixture.example.test"


@pytest.mark.parametrize("host", ["radarr", "sonarr", "bazarr", "prowlarr"])
def test_arr_root_redirect_and_prefix_preservation(ingress, host):
    response = request(ingress, f"{host}.greis.dev.br", extra=("-D", "-", "-o", "/dev/null"))
    assert "HTTP/1.1 302" in response.stdout
    assert f"Location: https://{host}.greis.dev.br/{host}/" in response.stdout
    result = json.loads(request(ingress, f"{host}.greis.dev.br", f"/{host}/api/test").stdout)
    assert result["uri"] == f"/{host}/api/test"
    denied = request(
        ingress,
        f"{host}.greis.dev.br",
        "/wrong-prefix",
        extra=("-w", "%{http_code}", "-o", "/dev/null"),
    )
    assert denied.stdout == "404"


def test_sni_host_mismatch_is_rejected(ingress):
    result = request(
        ingress,
        "homelab.greis.dev.br",
        extra=("-H", "Host: proxmox.greis.dev.br", "-w", "%{http_code}", "-o", "/dev/null"),
    )
    assert result.stdout == "421"
    unknown = request(ingress, "unknown.greis.dev.br", check=False)
    assert unknown.returncode != 0
    assert unknown.stdout == ""


def test_pve_tls_upload_and_upgrade_headers(ingress):
    result = json.loads(
        request(
            ingress,
            "proxmox.greis.dev.br",
            "/upload",
            extra=("--data-binary", "@/fixture/body.bin"),
        ).stdout
    )
    assert result["length"] == "70000"
    result = json.loads(
        request(
            ingress,
            "proxmox.greis.dev.br",
            "/console",
            extra=("-H", "Upgrade: websocket", "-H", "Connection: Upgrade"),
        ).stdout
    )
    assert result["upgrade"] == "websocket"


def test_raw_synthetic_token_does_not_reach_container_logs(ingress):
    request(ingress, "homelab.greis.dev.br", "/fixture?secret=SYNTHETIC_LOG_PROBE")
    logs = command("docker", "logs", ingress)
    assert "SYNTHETIC_LOG_PROBE" not in logs.stdout + logs.stderr


def test_pve_certificate_name_mismatch_blocks_backend(ingress):
    result = request(
        ingress,
        "proxmox.greis.dev.br",
        extra=("-w", "%{http_code}", "-o", "/dev/null"),
        port=11443,
    )
    assert result.stdout == "502"


def test_qbit_preserves_native_csrf_and_cookie_inputs(ingress):
    result = json.loads(
        request(
            ingress,
            "qbittorrent.greis.dev.br",
            "/api/v2/app/version",
            extra=(
                "-H",
                "Host: qbittorrent.greis.dev.br:443",
                "-H",
                "Origin: https://qbittorrent.greis.dev.br",
                "-H",
                "Referer: https://qbittorrent.greis.dev.br/",
                "-H",
                "Cookie: SID=SYNTHETIC_QBIT_COOKIE",
            ),
        ).stdout
    )
    assert result["http_host"] == "qbittorrent.greis.dev.br:443"
    assert result["origin"] == "https://qbittorrent.greis.dev.br"
    assert result["referer"] == "https://qbittorrent.greis.dev.br/"
    assert result["cookie"] == "SID=SYNTHETIC_QBIT_COOKIE"
    assert result["uri"] == "/api/v2/app/version"


def test_jellyfin_redirects_and_private_auth_headers(ingress):
    host = "jellyfin.greis.dev.br"
    for path, expected in (("/", "302"), ("/jellyfin", "308")):
        response = request(ingress, host, path, extra=("-D", "-", "-o", "/dev/null"))
        assert f"HTTP/1.1 {expected}" in response.stdout
        assert f"Location: https://{host}/jellyfin/" in response.stdout
    response = request(
        ingress,
        host,
        "/jellyfin/System/Configuration",
        extra=(
            "-H",
            "Authorization: MediaBrowser Token=SYNTHETIC_HEADER",
            "-H",
            "X-Emby-Token: SYNTHETIC_EMBY",
        ),
    )
    value = json.loads(response.stdout)
    assert value["uri"] == "/jellyfin/System/Configuration"
    assert value["authorization"] == "MediaBrowser Token=SYNTHETIC_HEADER"
    assert value["emby_token"] == "SYNTHETIC_EMBY"
    assert value["host"] == host
    assert value["forwarded_proto"] == "https"
    assert value["forwarded_port"] == "443"
    denied = request(
        ingress, host, "/System/Configuration", extra=("-w", "%{http_code}", "-o", "/dev/null")
    )
    assert denied.stdout == "404"


def test_jellyfin_range_returns_partial_synthetic_bytes(ingress):
    response = request(
        ingress,
        "jellyfin.greis.dev.br",
        "/jellyfin/fixture-media.bin",
        extra=("-H", "Range: bytes=32-63", "-D", "-"),
    )
    headers, body = response.stdout.split("\n\n", 1)
    assert "HTTP/1.1 206" in headers
    assert "Content-Range: bytes 32-63/65536" in headers
    assert body == bytes(range(32, 64)).decode("ascii")


def test_jellyfin_preserves_websocket_upgrade_headers(ingress):
    response = request(
        ingress,
        "jellyfin.greis.dev.br",
        "/jellyfin/socket?ApiKey=SYNTHETIC_WS",
        extra=("-H", "Upgrade: websocket", "-H", "Connection: Upgrade"),
    )
    value = json.loads(response.stdout)
    assert value["uri"] == "/jellyfin/socket?ApiKey=SYNTHETIC_WS"
    assert value["upgrade"] == "websocket"
    logs = command("docker", "logs", ingress)
    assert "SYNTHETIC_WS" not in logs.stdout + logs.stderr


def response_headers(response):
    return {
        key.lower(): value.strip()
        for line in response.stdout.splitlines()
        if ":" in line
        for key, value in [line.split(":", 1)]
    }


@pytest.mark.parametrize(
    "path",
    [
        "/jellyfin/socket",
        "/jellyfin/Items/0123456789abcdef0123456789abcdef/Download",
        "/jellyfin/Items/01234567-89AB-cdef-0123-456789abcdef/Download",
    ],
)
def test_jellyfin_legacy_bundle_paths_receive_modern_authorization(ingress, path):
    response = request(
        ingress,
        "jellyfin.greis.dev.br",
        path + "?api_key=SYNTHETIC.legacy_~-9",
        extra=("-D", "-", "-o", "/dev/null", "-H", "Upgrade: websocket"),
    )
    headers = response_headers(response)
    assert "HTTP/1.1 200" in response.stdout
    assert headers["x-fixture-authorization"] == 'MediaBrowser Token="SYNTHETIC.legacy_~-9"'
    assert headers["x-fixture-upgrade"] == "websocket"
    assert headers["x-fixture-host"] == "jellyfin.greis.dev.br"
    assert headers["x-fixture-uri"] == path + "?api_key=SYNTHETIC.legacy_~-9"


@pytest.mark.parametrize(
    "name,value,echo",
    [
        ("Authorization", 'MediaBrowser Token="EXPLICIT"', "x-fixture-authorization"),
        ("Authorization", "invalid-explicit", "x-fixture-authorization"),
        ("X-Emby-Authorization", "invalid-explicit", "x-fixture-emby-authorization"),
        ("X-Emby-Token", "invalid-explicit", "x-fixture-emby-token"),
        ("X-MediaBrowser-Token", "invalid-explicit", "x-fixture-mediabrowser-token"),
    ],
)
def test_jellyfin_explicit_auth_prevents_legacy_fallback(ingress, name, value, echo):
    response = request(
        ingress,
        "jellyfin.greis.dev.br",
        "/jellyfin/socket?api_key=SYNTHETIC_LEGACY",
        extra=("-D", "-", "-o", "/dev/null", "-H", f"{name}: {value}"),
    )
    headers = response_headers(response)
    assert headers[echo] == value
    assert headers.get("x-fixture-authorization", "") == (value if name == "Authorization" else "")


@pytest.mark.parametrize("canonical", ["ApiKey=CANONICAL", "ApiKey=", "apikey=invalid"])
def test_jellyfin_canonical_query_prevents_legacy_fallback(ingress, canonical):
    response = request(
        ingress,
        "jellyfin.greis.dev.br",
        "/jellyfin/socket?api_key=SYNTHETIC_LEGACY&" + canonical,
        extra=("-D", "-", "-o", "/dev/null"),
    )
    assert response_headers(response).get("x-fixture-authorization", "") == ""
    assert response_headers(response)["x-fixture-uri"].endswith(canonical)


@pytest.mark.parametrize(
    "query",
    [
        "api_key=",
        "api_key=bad%0d%0aX-Injected:yes",
        "api_key=bad%22quoted",
        "api_key=bad/slash",
        "api_key=" + "x" * 4097,
        "api_key=FIRST&api_key=SECOND",
        "api_key=FIRST&other=value&API_KEY=SECOND",
        "api_key=FIRST&%41piKey=INVALID",
        "api_key=FIRST&Api%4Bey=INVALID",
        "api_key=FIRST&api%5fkey=SECOND",
    ],
)
def test_jellyfin_bad_or_duplicate_legacy_tokens_are_rejected(ingress, query):
    response = request(
        ingress,
        "jellyfin.greis.dev.br",
        "/jellyfin/socket?" + query,
        extra=("-D", "-", "-o", "/dev/null"),
    )
    assert "HTTP/1.1 400" in response.stdout
    assert "x-fixture-authorization" not in response_headers(response)
    assert "x-injected" not in response_headers(response)


def test_jellyfin_legacy_adapter_preserves_encoded_non_auth_values(ingress):
    response = request(
        ingress,
        "jellyfin.greis.dev.br",
        "/jellyfin/socket?api_key=SYNTHETIC_LEGACY&deviceId=browser%20client",
        extra=("-D", "-", "-o", "/dev/null"),
    )
    assert response_headers(response)["x-fixture-authorization"] == (
        'MediaBrowser Token="SYNTHETIC_LEGACY"'
    )


@pytest.mark.parametrize(
    "path",
    [
        "/jellyfin/Items/0123456789abcdef0123456789abcdef/Images/Primary",
        "/jellyfin/Videos/0123456789abcdef0123456789abcdef/stream",
        "/jellyfin/socket/extra",
        "/jellyfin/Items/invalid/Download",
        "/jellyfin/Items/0123456789abcdef-0123456789abcdef/Download",
    ],
)
def test_jellyfin_legacy_adaptation_does_not_cover_other_routes(ingress, path):
    response = request(
        ingress,
        "jellyfin.greis.dev.br",
        path + "?api_key=SYNTHETIC_LEGACY",
        extra=("-D", "-", "-o", "/dev/null"),
    )
    assert response_headers(response).get("x-fixture-authorization", "") == ""


def test_jellyfin_legacy_adaptation_does_not_affect_other_vhosts(ingress):
    result = json.loads(
        request(
            ingress,
            "homelab.greis.dev.br",
            "/jellyfin/socket?api_key=SYNTHETIC_LEGACY",
        ).stdout
    )
    assert result["authorization"] == ""
