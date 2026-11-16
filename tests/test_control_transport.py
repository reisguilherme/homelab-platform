"""TLS configuration and redirect boundaries for the fixed upstream."""

import ssl

import httpx
import pytest

from services.control.models import ControlError, Settings
from services.control.proxmox import ProxmoxClient


def settings(tmp_path, **kwargs):
    return Settings(
        origin="https://control.test",
        pve_url="https://pve.test:8006",
        db_path=tmp_path / "state.sqlite",
        allowed_nodes=("pve01",),
        **kwargs,
    )


def test_production_transport_requires_explicit_ca_and_rejects_invalid_pem(tmp_path):
    with pytest.raises(ValueError, match="PVE_CA_PEM"):
        ProxmoxClient(settings(tmp_path))
    with pytest.raises(ssl.SSLError):
        ProxmoxClient(settings(tmp_path, pve_ca_pem="invalid PEM"))


def test_redirect_does_not_forward_human_credentials_to_another_host(tmp_path):
    calls = []

    def upstream(request):
        calls.append(request)
        return httpx.Response(307, headers={"Location": "https://evil.test/collect"})

    adapter = ProxmoxClient(settings(tmp_path), transport=httpx.MockTransport(upstream))
    with pytest.raises(ControlError):
        adapter.login("person@pve", "synthetic-password")
    assert len(calls) == 1 and calls[0].url.host == "pve.test"


def test_capacity_token_cannot_authorize_any_mutating_request(tmp_path):
    calls = []
    adapter = ProxmoxClient(
        settings(
            tmp_path, capacity_token_id="metrics@pve!collector", capacity_token_secret="fixture"
        ),
        transport=httpx.MockTransport(lambda request: calls.append(request)),
    )
    for method in ("POST", "PUT", "PATCH", "DELETE"):
        with pytest.raises(ControlError, match="capacity_unknown"):
            adapter._request(method, "nodes/pve01/qemu", budget=True)
    assert not calls


@pytest.mark.parametrize(
    "url", ["http://pve.test", "https://user:pw@pve.test", "https://pve.test/?target=evil"]
)
def test_operator_upstream_must_be_fixed_https_without_credentials_or_query(tmp_path, url):
    with pytest.raises(ValueError):
        Settings(
            origin="https://control.test",
            pve_url=url,
            db_path=tmp_path / "state.sqlite",
            allowed_nodes=("pve01",),
        )
