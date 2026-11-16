#!/usr/bin/env python3
"""Export an explicitly selected certificate expiry; no renewal or scheduling."""

import argparse
import os
import ssl
import subprocess
import tempfile
from pathlib import Path


def export_expiry(certificate: Path, output: Path, label: str) -> None:
    if label not in {"streaming", "private"}:
        raise ValueError("unsupported certificate label")
    if not certificate.is_absolute() or not output.is_absolute():
        raise ValueError("certificate and output paths must be absolute")
    if not certificate.is_file() or output.suffix != ".prom" or output.is_symlink():
        raise ValueError("invalid certificate or textfile output path")
    if certificate.resolve() == output.resolve():
        raise ValueError("certificate cannot be the output")
    result = subprocess.run(
        ["openssl", "x509", "-in", str(certificate), "-noout", "-enddate"],
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
        env={**os.environ, "LC_ALL": "C"},
    )
    value = result.stdout.strip()
    if not value.startswith("notAfter="):
        raise ValueError("certificate expiry missing")
    expires = int(ssl.cert_time_to_seconds(value.removeprefix("notAfter=")))
    metric = (
        "# HELP homelab_tls_certificate_not_after_seconds Certificate expiry as Unix seconds.\n"
        "# TYPE homelab_tls_certificate_not_after_seconds gauge\n"
        f'homelab_tls_certificate_not_after_seconds{{certificate="{label}"}} {expires}\n'
    )
    descriptor, temporary = tempfile.mkstemp(prefix="." + output.name + ".", dir=output.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="ascii", newline="\n") as handle:
            os.fchmod(handle.fileno(), 0o644)
            handle.write(metric)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, output)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--certificate-label", choices=("streaming", "private"), required=True)
    parser.add_argument("--certificate", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        export_expiry(args.certificate, args.output, args.certificate_label)
    except (OSError, ValueError, subprocess.SubprocessError):
        parser.exit(1, "Certificate expiry export failed; previous textfile preserved.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
