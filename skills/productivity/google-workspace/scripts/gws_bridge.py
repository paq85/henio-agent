#!/usr/bin/env python3
"""Bridge between the Henio OAuth token and gws CLI."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


def get_henio_home() -> Path:
    return Path(os.environ.get("HENIO_HOME", Path.home() / ".henio"))


def get_token_path() -> Path:
    return get_henio_home() / "google_token.json"


def refresh_token(token_data: dict) -> dict:
    import urllib.error
    import urllib.parse
    import urllib.request

    params = urllib.parse.urlencode({
        "client_id": token_data["client_id"],
        "client_secret": token_data["client_secret"],
        "refresh_token": token_data["refresh_token"],
        "grant_type": "refresh_token",
    }).encode()

    req = urllib.request.Request(token_data["token_uri"], data=params)
    try:
        with urllib.request.urlopen(req) as resp:
            result = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        print(f"ERROR: Token refresh failed (HTTP {exc.code}): {body}", file=sys.stderr)
        print("Re-run setup.py to re-authenticate.", file=sys.stderr)
        sys.exit(1)

    token_data["token"] = result["access_token"]
    token_data["expiry"] = (datetime.now(timezone.utc) + timedelta(seconds=result["expires_in"])).isoformat()
    get_token_path().write_text(json.dumps(token_data, indent=2))
    return token_data


def get_valid_token() -> str:
    token_path = get_token_path()
    if not token_path.exists():
        print("ERROR: No Google token found. Run setup.py --auth-url first.", file=sys.stderr)
        sys.exit(1)
    token_data = json.loads(token_path.read_text())
    expiry = token_data.get("expiry", "")
    if expiry:
        exp_dt = datetime.fromisoformat(expiry.replace("Z", "+00:00"))
        if datetime.now(timezone.utc) >= exp_dt:
            token_data = refresh_token(token_data)
    return token_data["token"]


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: gws_bridge.py <gws args...>", file=sys.stderr)
        sys.exit(1)
    access_token = get_valid_token()
    env = os.environ.copy()
    env["GOOGLE_WORKSPACE_CLI_TOKEN"] = access_token
    result = subprocess.run(["gws", *sys.argv[1:]], env=env)
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
