#!/bin/bash
# Docker entrypoint: bootstrap config files into the mounted volume, then run henio.
set -e

HENIO_HOME="/opt/data"
INSTALL_DIR="/opt/henio"

# --- Privilege dropping via gosu ---
# When started as root (the default), optionally remap the henio user/group
# to match host-side ownership, fix volume permissions, then re-exec as henio.
if [ "$(id -u)" = "0" ]; then
    if [ -n "$HENIO_UID" ] && [ "$HENIO_UID" != "$(id -u henio)" ]; then
        echo "Changing henio UID to $HENIO_UID"
        usermod -u "$HENIO_UID" henio
    fi

    if [ -n "$HENIO_GID" ] && [ "$HENIO_GID" != "$(id -g henio)" ]; then
        echo "Changing henio GID to $HENIO_GID"
        groupmod -g "$HENIO_GID" henio
    fi

    actual_henio_uid=$(id -u henio)
    if [ "$(stat -c %u "$HENIO_HOME" 2>/dev/null)" != "$actual_henio_uid" ]; then
        echo "$HENIO_HOME is not owned by $actual_henio_uid, fixing"
        chown -R henio:henio "$HENIO_HOME"
    fi

    echo "Dropping root privileges"
    exec gosu henio "$0" "$@"
fi

# --- Running as henio from here ---
source "${INSTALL_DIR}/.venv/bin/activate"

# Create essential directory structure.  Cache and platform directories
# (cache/images, cache/audio, platforms/whatsapp, etc.) are created on
# demand by the application — don't pre-create them here so new installs
# get the consolidated layout from get_henio_dir().
# The "home/" subdirectory is a per-profile HOME for subprocesses (git,
# ssh, gh, npm …).  Without it those tools write to /root which is
# ephemeral and shared across profiles.  See issue #4426.
mkdir -p "$HENIO_HOME"/{cron,sessions,logs,hooks,memories,skills,skins,plans,workspace,home}

# .env
if [ ! -f "$HENIO_HOME/.env" ]; then
    cp "$INSTALL_DIR/.env.example" "$HENIO_HOME/.env"
fi

# config.yaml
if [ ! -f "$HENIO_HOME/config.yaml" ]; then
    cp "$INSTALL_DIR/cli-config.yaml.example" "$HENIO_HOME/config.yaml"
fi

# SOUL.md
if [ ! -f "$HENIO_HOME/SOUL.md" ]; then
    cp "$INSTALL_DIR/docker/SOUL.md" "$HENIO_HOME/SOUL.md"
fi

# Sync bundled skills (manifest-based so user edits are preserved)
if [ -d "$INSTALL_DIR/skills" ]; then
    python3 "$INSTALL_DIR/tools/skills_sync.py"
fi

exec henio "$@"
