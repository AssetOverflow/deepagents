#!/usr/bin/env python
"""Bootstrap local directories and configuration for Deephaven + MCP + Redis stack.

Creates:
  local/
    deephaven/{data,cache}
    mcp/config/deephaven_mcp.json
    redis/data
    secrets/psk.txt
Optionally writes a project-level .env file exporting DEEPHAVEN_PSK.

Idempotent: re-running will not overwrite existing secret/config unless --force is supplied.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import secrets

ROOT = Path(__file__).resolve().parent.parent
LOCAL = ROOT / "local"
ENV_FILE = ROOT / ".env"

DEE_PATH = LOCAL / "deephaven"
MCP_PATH = LOCAL / "mcp" / "config"
REDIS_PATH = LOCAL / "redis" / "data"
SECRETS_PATH = LOCAL / "secrets"
PSK_FILE = SECRETS_PATH / "psk.txt"
MCP_CONFIG_FILE = MCP_PATH / "deephaven_mcp.json"

DEFAULT_PSK = "dev-psk"

MCP_CONFIG_TEMPLATE = {
    "community": {
        "sessions": {
            "local": {
                "host": "deephaven",
                "port": 10000,
                "auth_type": "io.deephaven.authentication.psk.PskAuthenticationHandler",
                "auth_token": "${DEEPHAVEN_PSK}"  # populated at runtime via env or psk file
            }
        }
    }
}

def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def write_file(path: Path, content: str, *, force: bool = False, mode: int | None = None) -> None:
    if path.exists() and not force:
        return
    path.write_text(content, encoding="utf-8")
    if mode is not None:
        try:
            os.chmod(path, mode)
        except OSError:  # Windows may ignore chmod
            pass


def update_env_file(psk: str, force: bool) -> None:
    """Append or update DEEPHAVEN_PSK in project .env file."""
    lines: list[str] = []
    if ENV_FILE.exists():
        existing = ENV_FILE.read_text(encoding="utf-8").splitlines()
        replaced = False
        for line in existing:
            if line.startswith("DEEPHAVEN_PSK="):
                if not force:
                    # Keep existing unless force
                    lines.append(line)
                else:
                    lines.append(f"DEEPHAVEN_PSK={psk}")
                replaced = True
            else:
                lines.append(line)
        if not replaced:
            lines.append(f"DEEPHAVEN_PSK={psk}")
    else:
        lines.append(f"DEEPHAVEN_PSK={psk}")
    ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="Overwrite existing config + secret + .env variable")
    parser.add_argument("--random-psk", action="store_true", help="Generate random PSK instead of default")
    parser.add_argument("--write-env", action="store_true", help="Write/update project .env with DEEPHAVEN_PSK")
    args = parser.parse_args()

    # Directories
    for d in [DEE_PATH / "data", DEE_PATH / "cache", MCP_PATH, REDIS_PATH, SECRETS_PATH]:
        ensure_dir(d)

    # PSK secret
    if args.random_psk:
        psk_value = secrets.token_urlsafe(32)
    else:
        psk_value = DEFAULT_PSK
    write_file(PSK_FILE, psk_value + "\n", force=args.force, mode=0o600)

    # MCP config
    cfg = json.dumps(MCP_CONFIG_TEMPLATE, indent=2) + "\n"
    write_file(MCP_CONFIG_FILE, cfg, force=args.force, mode=0o600)

    if args.write_env:
        update_env_file(psk_value, args.force)

    print("Local stack prepared:")
    print(f"  Deephaven data: {DEE_PATH / 'data'}")
    print(f"  Deephaven cache: {DEE_PATH / 'cache'}")
    print(f"  MCP config: {MCP_CONFIG_FILE}")
    print(f"  Redis data: {REDIS_PATH}")
    print(f"  PSK secret: {PSK_FILE}")
    if args.write_env:
        print(f"  .env updated: {ENV_FILE}")
    print("Next:")
    if args.write_env:
        print("  docker compose up --build -d")
    else:
        print("  Set DEEPHAVEN_PSK then: docker compose up --build -d")


if __name__ == "__main__":
    main()
