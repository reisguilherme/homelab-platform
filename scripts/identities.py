#!/usr/bin/env python3
"""Administer the encrypted Authelia file backend on the Linux controller."""

import argparse
import base64
import fcntl
import getpass
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import tempfile

from argon2 import PasswordHasher, Type
import yaml


ROOT = Path(__file__).resolve().parents[1]
DIRECTORY = ROOT / "infrastructure/hub/authelia"
CATALOG = DIRECTORY / "users_database.sops.yaml"
OIDC = DIRECTORY / "oidc.sops.yaml"
ESCROW_DIR = Path("/root/.local/state/homelab-identities")
SOPS = "/usr/local/bin/sops"
GROUPS = {"admins", "homelab-viewers", "media-ops", "media-users", "pve-auditors",
          "ssh-restricted", "ssh-sftp-drop"}


def run(command, data=None):
    result = subprocess.run(command, input=data, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, cwd=ROOT)
    if result.returncode:
        # Cryptographic tools can include input fragments in diagnostic messages.
        raise ValueError(f"{Path(command[0]).name} failed (exit {result.returncode})")
    return result.stdout


def decrypt(path):
    return json.loads(run([SOPS, "decrypt", "--output-type", "json", str(path)]))


def encrypt(path, contents):
    rule_path = OIDC if path.parent == ESCROW_DIR else path
    cipher = run([SOPS, "encrypt", "--filename-override", str(rule_path.relative_to(ROOT)),
                  "--input-type", "json", "--output-type", "yaml"],
                 json.dumps(contents).encode())
    envelope = yaml.safe_load(cipher)
    if not envelope.get("sops", {}).get("age") or not envelope["sops"].get("mac"):
        raise ValueError("SOPS produced no authenticated Age envelope")
    # No plaintext reaches disk. Readers always see a complete SOPS document.
    with tempfile.NamedTemporaryFile(dir=path.parent, suffix=".yaml", delete=False) as tmp:
        temp_path = Path(tmp.name)
    try:
        with temp_path.open("wb") as tmp:
            tmp.write(cipher)
            tmp.flush()
            os.fsync(tmp.fileno())
        if decrypt(temp_path) != contents:
            raise ValueError("SOPS round-trip validation failed")
        os.replace(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)


def validate(catalog):
    users = catalog["users"]
    if not isinstance(users, dict) or not users:
        raise ValueError("Empty or malformed file backend")
    for name, user in users.items():
        if not re.fullmatch(r"[a-z][a-z0-9_-]*", name):
            raise ValueError("Invalid username in catalog")
        if not isinstance(user.get("disabled", False), bool) or not user.get("displayname"):
            raise ValueError("Invalid user status or display name")
        if not isinstance(user.get("groups", []), list):
            raise ValueError("Invalid group list")
        if not re.fullmatch(r"\$argon2id\$v=19\$m=\d+,t=\d+,p=\d+\$[A-Za-z0-9+/]+\$[A-Za-z0-9+/]+",
                            user.get("password", "")):
            raise ValueError("Invalid Argon2id password digest")
    if not any(not u.get("disabled", False) and "admins" in u.get("groups", [])
               for u in users.values()):
        raise ValueError("At least one enabled administrator is required")


def digest(password):
    return PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4,
                          hash_len=32, salt_len=16, type=Type.ID).hash(password)


def oidc_material():
    def ab64(data):
        return base64.b64encode(data).decode().rstrip("=").replace("+", ".")
    secret = secrets.token_urlsafe(48)
    salt = secrets.token_bytes(16)
    hashed = hashlib.pbkdf2_hmac("sha512", secret.encode(), salt, 310000)
    key = run(["openssl", "genpkey", "-algorithm", "RSA", "-pkeyopt", "rsa_keygen_bits:3072"])
    return {"pve_client_secret": secret,
            "pve_client_digest": f"$pbkdf2-sha512$310000${ab64(salt)}${ab64(hashed)}",
            "hmac_secret": secrets.token_urlsafe(64), "signing_key": key.decode()}


def bootstrap(catalog, args):
    updated = False
    if not OIDC.exists():
        encrypt(OIDC, oidc_material())
        updated = True
    if args.username not in catalog["users"]:
        ESCROW_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
        escrow = ESCROW_DIR / f"{args.username}.sops.yaml"
        if not escrow.exists():
            encrypt(escrow, {"initial_password": secrets.token_urlsafe(36)})
        password = decrypt(escrow)["initial_password"]
        catalog["users"][args.username] = {
            "displayname": args.display_name, "disabled": False,
            "password": digest(password), "groups": sorted(set(args.groups)),
        }
        validate(catalog)
        encrypt(CATALOG, catalog)
        updated = True
    print("updated" if updated else "unchanged")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="operation", required=True)
    commands.add_parser("validate")
    for name in ("bootstrap", "add", "groups", "disable", "enable", "password"):
        sub = commands.add_parser(name)
        sub.add_argument("username")
        if name in ("add", "groups", "bootstrap"):
            sub.add_argument("--groups", nargs="+", choices=sorted(GROUPS), required=True)
        if name in ("add", "bootstrap"):
            sub.add_argument("--display-name", required=True)
        if name == "add":
            sub.add_argument("--email")
    args = parser.parse_args()
    if hasattr(args, "username") and not re.fullmatch(r"[a-z][a-z0-9_-]*", args.username):
        parser.error("Invalid username")
    os.umask(0o077)
    directory_fd = os.open(DIRECTORY, os.O_RDONLY)
    try:
        fcntl.flock(directory_fd, fcntl.LOCK_EX)
        catalog = decrypt(CATALOG)
        validate(catalog)
        if args.operation == "bootstrap":
            bootstrap(catalog, args)
        elif args.operation == "validate":
            print("valid")
        else:
            users = catalog["users"]
            name = args.username
            if args.operation == "add":
                if name in users:
                    raise ValueError("User already exists")
                users[name] = {"displayname": args.display_name, "disabled": False}
                if args.email:
                    users[name]["email"] = args.email
            elif name not in users:
                raise ValueError("User does not exist")
            if args.operation in ("add", "password"):
                if not sys.stdin.isatty():
                    raise ValueError("A trusted interactive terminal is required to enter a password")
                password = getpass.getpass()
                if not password or password != getpass.getpass("Repeat password: "):
                    raise ValueError("Empty or mismatched password")
                users[name]["password"] = digest(password)
            if args.operation in ("add", "groups"):
                users[name]["groups"] = sorted(set(args.groups))
            if args.operation in ("disable", "enable"):
                users[name]["disabled"] = args.operation == "disable"
            validate(catalog)
            encrypt(CATALOG, catalog)
            print("updated")
    finally:
        os.close(directory_fd)


if __name__ == "__main__":
    try:
        main()
    except (KeyError, ValueError, OSError) as error:
        sys.exit(f"Identity management failed: {error}")
