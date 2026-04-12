"""Tests for henio_constants module."""

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from henio_constants import get_default_henio_root


class TestGetDefaultHenioRoot:
    """Tests for get_default_henio_root() — Docker/custom deployment awareness."""

    def test_no_henio_home_returns_native(self, tmp_path, monkeypatch):
        """When HENIO_HOME is not set, returns ~/.henio."""
        monkeypatch.delenv("HENIO_HOME", raising=False)
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        assert get_default_henio_root() == tmp_path / ".henio"

    def test_henio_home_is_native(self, tmp_path, monkeypatch):
        """When HENIO_HOME = ~/.henio, returns ~/.henio."""
        native = tmp_path / ".henio"
        native.mkdir()
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        monkeypatch.setenv("HENIO_HOME", str(native))
        assert get_default_henio_root() == native

    def test_henio_home_is_profile(self, tmp_path, monkeypatch):
        """When HENIO_HOME is a profile under ~/.henio, returns ~/.henio."""
        native = tmp_path / ".henio"
        profile = native / "profiles" / "coder"
        profile.mkdir(parents=True)
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        monkeypatch.setenv("HENIO_HOME", str(profile))
        assert get_default_henio_root() == native

    def test_henio_home_is_docker(self, tmp_path, monkeypatch):
        """When HENIO_HOME points outside ~/.henio (Docker), returns HENIO_HOME."""
        docker_home = tmp_path / "opt" / "data"
        docker_home.mkdir(parents=True)
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        monkeypatch.setenv("HENIO_HOME", str(docker_home))
        assert get_default_henio_root() == docker_home

    def test_henio_home_is_custom_path(self, tmp_path, monkeypatch):
        """Any HENIO_HOME outside ~/.henio is treated as the root."""
        custom = tmp_path / "my-henio-data"
        custom.mkdir()
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        monkeypatch.setenv("HENIO_HOME", str(custom))
        assert get_default_henio_root() == custom

    def test_docker_profile_active(self, tmp_path, monkeypatch):
        """When a Docker profile is active (HENIO_HOME=<root>/profiles/<name>),
        returns the Docker root, not the profile dir."""
        docker_root = tmp_path / "opt" / "data"
        profile = docker_root / "profiles" / "coder"
        profile.mkdir(parents=True)
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        monkeypatch.setenv("HENIO_HOME", str(profile))
        assert get_default_henio_root() == docker_root
