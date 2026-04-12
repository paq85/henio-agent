---
name: google-workspace
description: Gmail, Calendar, Drive, Contacts, Sheets, and Docs integration via gws CLI. Uses OAuth2 with automatic token refresh via bridge script. Requires gws binary.
version: 2.0.0
required_credential_files:
  - path: google_token.json
    description: Google OAuth2 token created by the setup script
  - path: google_client_secret.json
    description: Google OAuth2 client credentials downloaded from Google Cloud Console
metadata:
  henio:
    tags: [Google, Gmail, Calendar, Drive, Sheets, Docs, Contacts, Email, OAuth, gws]
---

# Google Workspace

Gmail, Calendar, Drive, Contacts, Sheets, and Docs integration powered by `gws`.

## Architecture

```text
google_api.py -> gws_bridge.py -> gws CLI
```

- `scripts/setup.py` handles OAuth2 in a headless-compatible flow.
- `scripts/gws_bridge.py` refreshes the Henio token and injects it into `gws` via `GOOGLE_WORKSPACE_CLI_TOKEN`.
- `scripts/google_api.py` provides a backward-compatible CLI wrapper that delegates to `gws`.

## References

- `references/gmail-search-syntax.md` — handy Gmail search operators.

## Scripts

- `scripts/setup.py` — OAuth2 setup
- `scripts/gws_bridge.py` — token refresh bridge to `gws`
- `scripts/google_api.py` — API wrapper that delegates to `gws`
