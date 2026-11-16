"""Human authentication boundaries; no real PVE or user credentials."""

import time
from urllib.parse import parse_qs

import httpx
import pytest
from fastapi.testclient import TestClient

from services.control.app import create_app
from services.control.models import Settings
from services.control.proxmox import ProxmoxClient

ORIGIN = "https://control.test"


def ticket(user="operator@pve"):
    return f"PVE:{user}:{int(time.time()):08X}::synthetic-signature"


@pytest.fixture
def harness(tmp_path):
    calls = []
    replies = []

    def upstream(request):
        calls.append(request)
        if replies:
            return httpx.Response(200, json={"data": replies.pop(0)})
        return httpx.Response(
            200,
            json={
                "data": {
                    "username": "operator@pve",
                    "ticket": ticket(),
                    "CSRFPreventionToken": "upstream-secret",
                }
            },
        )

    settings = Settings(
        origin=ORIGIN,
        pve_url="https://pve.test:8006",
        db_path=tmp_path / "audit.sqlite",
        allowed_nodes=("pve01",),
    )
    adapter = ProxmoxClient(settings, transport=httpx.MockTransport(upstream))
    app = create_app(settings, adapter)
    with TestClient(app, base_url=ORIGIN) as client:
        yield client, app, calls, replies


def login(client):
    return client.post(
        "/api/v1/session",
        headers={"Origin": ORIGIN},
        json={"username": "operator@pve", "password": "test-only-password"},
    )


def test_cross_origin_login_is_denied(harness):
    client, _, calls, _ = harness
    response = client.post(
        "/api/v1/session",
        headers={"Origin": "https://evil.test"},
        json={"username": "operator@pve", "password": "not-sent"},
    )
    assert response.status_code == 403
    assert not calls


def test_session_cookie_is_secure_and_never_returns_upstream_credentials(harness):
    client, _, _, _ = harness
    response = login(client)
    assert response.status_code == 200
    cookie = response.headers["set-cookie"]
    assert all(value in cookie for value in ("Secure", "HttpOnly", "SameSite=strict", "Path=/"))
    assert response.json()["authenticated"] is True
    assert len(response.json()["csrfToken"]) >= 43
    assert "upstream-secret" not in response.text and "synthetic-signature" not in response.text
    assert client.delete("/api/v1/session", headers={"Origin": ORIGIN}).status_code == 403


def test_tfa_is_not_a_session(harness):
    client, _, calls, replies = harness
    challenge_ticket = "PVE:!tfa!%7B%22totp%22%3Atrue%7D:01234567::signed-challenge"
    replies.append(
        {
            "username": "operator@pve",
            "ticket": challenge_ticket,
            "NeedTFA": 1,
            "CSRFPreventionToken": "not-an-authenticated-session",
        }
    )
    response = login(client)
    assert response.json()["authenticated"] is False
    assert "set-cookie" not in response.headers
    challenge = response.json()["challenge"]
    assert challenge["kind"] == "totp" and "signed-challenge" not in response.text
    assert client.get("/api/v1/vms").status_code == 401
    response = client.post(
        "/api/v1/session/tfa",
        headers={"Origin": ORIGIN},
        json={"challengeId": challenge["id"], "code": "123456"},
    )
    assert response.json()["authenticated"] is True
    sent = parse_qs(calls[-1].content.decode())
    assert sent["password"] == ["totp:123456"]
    assert sent["tfa-challenge"] == [challenge_ticket]
    assert "otp" not in sent


def test_expired_ticket_cannot_mutate(harness):
    client, app, calls, _ = harness
    response = login(client)
    csrf = response.json()["csrfToken"]
    app.state.sessions.clock = lambda: time.time() + 7201
    before = len(calls)
    response = client.post(
        "/api/v1/vms/900/actions",
        json={"action": "start", "expectedDigest": "a" * 40},
        headers={"Origin": ORIGIN, "X-CSRF-Token": csrf, "Idempotency-Key": "operation-key-1234"},
    )
    assert response.status_code == 401 and len(calls) == before


def test_validation_response_does_not_echo_password(harness):
    client, _, _, _ = harness
    response = client.post(
        "/api/v1/session",
        headers={"Origin": ORIGIN},
        json={"username": "invalid", "password": "secret-to-hide", "extra": 1},
    )
    assert response.status_code == 422
    assert "secret-to-hide" not in response.text


def test_operator_console_link_can_use_https_subpath_but_api_origin_cannot(tmp_path):
    settings = Settings(
        origin=ORIGIN,
        pve_url="https://pve.test:8006",
        db_path=tmp_path / "audit.sqlite",
        allowed_nodes=("pve01",),
        grafana_url=ORIGIN + "/grafana/",
    )
    assert settings.grafana_url.endswith("/grafana/")
    with pytest.raises(ValueError):
        Settings(
            origin=ORIGIN + "/unexpected",
            pve_url="https://pve.test:8006",
            db_path=tmp_path / "audit.sqlite",
            allowed_nodes=("pve01",),
        )
