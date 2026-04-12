#!/usr/bin/env python3
"""Google Workspace OAuth2 setup for Henio Agent.

Fully non-interactive and friendly to agent-driven workflows.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

try:
    from henio_constants import display_henio_home, get_henio_home
except ModuleNotFoundError:
    HENIO_AGENT_ROOT = Path(__file__).resolve().parents[4]
    if HENIO_AGENT_ROOT.exists():
        sys.path.insert(0, str(HENIO_AGENT_ROOT))
    from henio_constants import display_henio_home, get_henio_home

HENIO_HOME = get_henio_home()
TOKEN_PATH = HENIO_HOME / "google_token.json"
CLIENT_SECRET_PATH = HENIO_HOME / "google_client_secret.json"
PENDING_AUTH_PATH = HENIO_HOME / "google_oauth_pending.json"

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/contacts.readonly",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/documents.readonly",
]

REQUIRED_PACKAGES = [
    "google-api-python-client",
    "google-auth-oauthlib",
    "google-auth-httplib2",
]

REDIRECT_URI = "http://localhost:1"


def _load_token_payload(path: Path = TOKEN_PATH) -> dict:
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def _missing_scopes_from_payload(payload: dict) -> list[str]:
    raw = payload.get("scopes") or payload.get("scope")
    if not raw:
        return []
    granted = {scope.strip() for scope in (raw.split() if isinstance(raw, str) else raw) if scope.strip()}
    return sorted(scope for scope in SCOPES if scope not in granted)


def install_deps() -> bool:
    try:
        import googleapiclient  # noqa: F401
        import google_auth_oauthlib  # noqa: F401
        print("Dependencies already installed.")
        return True
    except ImportError:
        pass
    print("Installing Google API dependencies...")
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "--quiet", *REQUIRED_PACKAGES], stdout=subprocess.DEVNULL)
        print("Dependencies installed.")
        return True
    except subprocess.CalledProcessError as exc:
        print(f"ERROR: Failed to install dependencies: {exc}")
        print(f"Try manually: {sys.executable} -m pip install {' '.join(REQUIRED_PACKAGES)}")
        return False


def _ensure_deps() -> None:
    try:
        import googleapiclient  # noqa: F401
        import google_auth_oauthlib  # noqa: F401
    except ImportError:
        if not install_deps():
            sys.exit(1)


def store_client_secret(path: str) -> None:
    src = Path(path).expanduser().resolve()
    if not src.exists():
        print(f"ERROR: File not found: {src}")
        sys.exit(1)
    try:
        data = json.loads(src.read_text())
    except json.JSONDecodeError:
        print("ERROR: File is not valid JSON.")
        sys.exit(1)
    if "installed" not in data and "web" not in data:
        print("ERROR: Not a Google OAuth client secret file (missing 'installed' key).")
        sys.exit(1)
    CLIENT_SECRET_PATH.write_text(json.dumps(data, indent=2))
    print(f"OK: Client secret saved to {CLIENT_SECRET_PATH}")


def _save_pending_auth(*, state: str, code_verifier: str) -> None:
    PENDING_AUTH_PATH.write_text(json.dumps({
        "state": state,
        "code_verifier": code_verifier,
        "redirect_uri": REDIRECT_URI,
    }, indent=2))


def _load_pending_auth() -> dict:
    if not PENDING_AUTH_PATH.exists():
        print("ERROR: No pending OAuth session found. Run --auth-url first.")
        sys.exit(1)
    try:
        data = json.loads(PENDING_AUTH_PATH.read_text())
    except Exception as exc:
        print(f"ERROR: Could not read pending OAuth session: {exc}")
        print("Run --auth-url again to start a fresh OAuth session.")
        sys.exit(1)
    if not data.get("state") or not data.get("code_verifier"):
        print("ERROR: Pending OAuth session is missing PKCE data.")
        print("Run --auth-url again to start a fresh OAuth session.")
        sys.exit(1)
    return data


def _extract_code_and_state(code_or_url: str) -> tuple[str, str | None]:
    if not code_or_url.startswith("http"):
        return code_or_url, None
    from urllib.parse import parse_qs, urlparse
    parsed = urlparse(code_or_url)
    params = parse_qs(parsed.query)
    if "code" not in params:
        print("ERROR: No 'code' parameter found in URL.")
        sys.exit(1)
    state = params.get("state", [None])[0]
    return params["code"][0], state


def get_auth_url() -> None:
    if not CLIENT_SECRET_PATH.exists():
        print("ERROR: No client secret stored. Run --client-secret first.")
        sys.exit(1)
    _ensure_deps()
    from google_auth_oauthlib.flow import Flow
    flow = Flow.from_client_secrets_file(
        str(CLIENT_SECRET_PATH),
        scopes=SCOPES,
        redirect_uri=REDIRECT_URI,
        autogenerate_code_verifier=True,
    )
    auth_url, state = flow.authorization_url(access_type="offline", prompt="consent")
    _save_pending_auth(state=state, code_verifier=flow.code_verifier)
    print(auth_url)


def exchange_auth_code(code: str) -> None:
    if not CLIENT_SECRET_PATH.exists():
        print("ERROR: No client secret stored. Run --client-secret first.")
        sys.exit(1)
    pending_auth = _load_pending_auth()
    original_input = code
    code, returned_state = _extract_code_and_state(code)
    if returned_state and returned_state != pending_auth["state"]:
        print("ERROR: OAuth state mismatch. Run --auth-url again to start a fresh session.")
        sys.exit(1)
    _ensure_deps()
    from google_auth_oauthlib.flow import Flow
    from urllib.parse import parse_qs, urlparse

    granted_scopes = SCOPES
    if isinstance(original_input, str) and original_input.startswith("http"):
        params = parse_qs(urlparse(original_input).query)
        if "scope" in params:
            granted_scopes = params["scope"][0].split()

    flow = Flow.from_client_secrets_file(
        str(CLIENT_SECRET_PATH),
        scopes=granted_scopes,
        redirect_uri=pending_auth.get("redirect_uri", REDIRECT_URI),
        state=pending_auth["state"],
        code_verifier=pending_auth["code_verifier"],
    )
    try:
        os.environ["OAUTHLIB_RELAX_TOKEN_SCOPE"] = "1"
        flow.fetch_token(code=code)
    except Exception as exc:
        print(f"ERROR: Token exchange failed: {exc}")
        print("The code may have expired. Run --auth-url to get a fresh URL.")
        sys.exit(1)

    creds = flow.credentials
    token_payload = json.loads(creds.to_json())
    actually_granted = list(creds.granted_scopes or []) if hasattr(creds, "granted_scopes") and creds.granted_scopes else []
    if actually_granted:
        token_payload["scopes"] = actually_granted
    elif granted_scopes != SCOPES:
        token_payload["scopes"] = granted_scopes

    missing_scopes = _missing_scopes_from_payload(token_payload)
    if missing_scopes:
        print(f"WARNING: Token missing some Google Workspace scopes: {', '.join(missing_scopes)}")
        print("Some services may not be available.")

    TOKEN_PATH.write_text(json.dumps(token_payload, indent=2))
    PENDING_AUTH_PATH.unlink(missing_ok=True)
    print(f"OK: Authenticated. Token saved to {TOKEN_PATH}")
    print(f"Profile-scoped token location: {display_henio_home()}/google_token.json")


def check_auth() -> bool:
    if not TOKEN_PATH.exists():
        print(f"NOT_AUTHENTICATED: No token at {TOKEN_PATH}")
        return False
    return True


def revoke() -> None:
    TOKEN_PATH.unlink(missing_ok=True)
    PENDING_AUTH_PATH.unlink(missing_ok=True)
    print(f"Deleted {TOKEN_PATH}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Google Workspace OAuth setup for Henio")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true")
    group.add_argument("--client-secret", metavar="PATH")
    group.add_argument("--auth-url", action="store_true")
    group.add_argument("--auth-code", metavar="CODE")
    group.add_argument("--revoke", action="store_true")
    group.add_argument("--install-deps", action="store_true")
    args = parser.parse_args()

    if args.check:
        sys.exit(0 if check_auth() else 1)
    if args.client_secret:
        store_client_secret(args.client_secret)
    elif args.auth_url:
        get_auth_url()
    elif args.auth_code:
        exchange_auth_code(args.auth_code)
    elif args.revoke:
        revoke()
    elif args.install_deps:
        sys.exit(0 if install_deps() else 1)


if __name__ == "__main__":
    main()
