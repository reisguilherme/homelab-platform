import os
import shutil
import ssl
import subprocess
import sys
import time
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/export_tls_expiry.py"


@pytest.fixture
def certificate(tmp_path):
    if not shutil.which("openssl"):
        pytest.skip("OpenSSL required for disposable certificate")
    cert = tmp_path / "certificate.pem"
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-keyout",
            str(tmp_path / "fixture.key"),
            "-out",
            str(cert),
            "-days",
            "2",
            "-subj",
            "/CN=fixture.invalid",
        ],
        check=True,
        capture_output=True,
        timeout=30,
    )
    return cert


def test_exports_verified_absolute_expiry_and_atomic_readable_file(certificate, tmp_path):
    assert SCRIPT.is_file(), "TLS expiry exporter is not implemented"
    output = tmp_path / "tls.prom"
    output.write_text("old fixture\n")
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--certificate-label",
            "streaming",
            "--certificate",
            str(certificate),
            "--output",
            str(output),
        ],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    enddate = (
        subprocess.check_output(
            ["openssl", "x509", "-in", str(certificate), "-noout", "-enddate"], text=True
        )
        .strip()
        .split("=", 1)[1]
    )
    expected = int(ssl.cert_time_to_seconds(enddate))
    assert expected > time.time()
    metric = f'homelab_tls_certificate_not_after_seconds{{certificate="streaming"}} {expected}\n'
    assert metric in output.read_text()
    if os.name == "posix":
        assert output.stat().st_mode & 0o777 == 0o644
    assert not list(tmp_path.glob(".tls.prom.*"))


def test_invalid_input_preserves_previous_metric(tmp_path):
    assert SCRIPT.is_file(), "TLS expiry exporter is not implemented"
    bad = tmp_path / "bad.pem"
    bad.write_text("not a certificate")
    output = tmp_path / "tls.prom"
    output.write_text("preserved\n")
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--certificate-label",
            "private",
            "--certificate",
            str(bad),
            "--output",
            str(output),
        ],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode != 0
    assert output.read_text() == "preserved\n"


@pytest.mark.parametrize(
    "arguments",
    [
        [],
        ["--certificate-label", "anything"],
        [
            "--certificate-label",
            "private",
            "--certificate",
            "relative.pem",
            "--output",
            "/tmp/tls.prom",
        ],
    ],
)
def test_cli_requires_explicit_label_and_absolute_paths(arguments):
    assert SCRIPT.is_file(), "TLS expiry exporter is not implemented"
    result = subprocess.run(
        [sys.executable, str(SCRIPT), *arguments], capture_output=True, text=True, timeout=10
    )
    assert result.returncode != 0
