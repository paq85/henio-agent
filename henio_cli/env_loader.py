"""Helpers for loading Henio .env files consistently across entrypoints."""

from __future__ import annotations

import os
from pathlib import Path


def _parse_dotenv(text: str) -> list[tuple[str, str]]:
    """Parse a minimal dotenv file into ``(key, value)`` pairs.

    This intentionally supports the small subset Henio relies on:
    ``KEY=value`` lines, optional ``export`` prefixes, quoted values, and
    inline comments after unquoted values.  Keeping the parser local avoids
    shared-state issues when test suites stub the external ``dotenv`` module.
    """
    entries: list[tuple[str, str]] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue

        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        else:
            comment_start = value.find(" #")
            if comment_start != -1:
                value = value[:comment_start].rstrip()

        entries.append((key, value))
    return entries


def _load_dotenv_with_fallback(path: Path, *, override: bool) -> None:
    for encoding in ("utf-8", "latin-1"):
        try:
            text = path.read_text(encoding=encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = path.read_text(encoding="utf-8", errors="ignore")

    for key, value in _parse_dotenv(text):
        if override or key not in os.environ:
            os.environ[key] = value


def load_henio_dotenv(
    *,
    henio_home: str | os.PathLike | None = None,
    project_env: str | os.PathLike | None = None,
) -> list[Path]:
    """Load Henio environment files with user config taking precedence.

    Behavior:
    - `~/.henio/.env` overrides stale shell-exported values when present.
    - project `.env` acts as a dev fallback and only fills missing values when
      the user env exists.
    - if no user env exists, the project `.env` also overrides stale shell vars.
    """
    loaded: list[Path] = []

    home_path = Path(henio_home or os.getenv("HENIO_HOME", Path.home() / ".henio"))
    user_env = home_path / ".env"
    project_env_path = Path(project_env) if project_env else None

    if user_env.exists():
        _load_dotenv_with_fallback(user_env, override=True)
        loaded.append(user_env)

    if project_env_path and project_env_path.exists():
        _load_dotenv_with_fallback(project_env_path, override=not loaded)
        loaded.append(project_env_path)

    return loaded
