---
sidebar_position: 11
title: "ACP Editor Integration"
description: "Use Henio Agent inside ACP-compatible editors such as VS Code, Zed, and JetBrains"
---

# ACP Editor Integration

Henio Agent can run as an ACP server, letting ACP-compatible editors talk to Henio over stdio and render:

- chat messages
- tool activity
- file diffs
- terminal commands
- approval prompts
- streamed thinking / response chunks

ACP is a good fit when you want Henio to behave like an editor-native coding agent instead of a standalone CLI or messaging bot.

## What Henio exposes in ACP mode

Henio runs with a curated `henio-acp` toolset designed for editor workflows. It includes:

- file tools: `read_file`, `write_file`, `patch`, `search_files`
- terminal tools: `terminal`, `process`
- web/browser tools
- memory, todo, session search
- skills
- execute_code and delegate_task
- vision

It intentionally excludes things that do not fit typical editor UX, such as messaging delivery and cronjob management.

## Installation

Install Henio normally, then add the ACP extra:

```bash
pip install -e '.[acp]'
```

This installs the `agent-client-protocol` dependency and enables:

- `henio acp`
- `henio-acp`
- `python -m acp_adapter`

## Launching the ACP server

Any of the following starts Henio in ACP mode:

```bash
henio acp
```

```bash
henio-acp
```

```bash
python -m acp_adapter
```

Henio logs to stderr so stdout remains reserved for ACP JSON-RPC traffic.

## Editor setup

### VS Code

Install an ACP client extension, then point it at the repo's `acp_registry/` directory.

Example settings snippet:

```json
{
  "acpClient.agents": [
    {
      "name": "henio-agent",
      "registryDir": "/path/to/henio-agent/acp_registry"
    }
  ]
}
```

### Zed

Example settings snippet:

```json
{
  "agent_servers": {
    "henio-agent": {
      "type": "custom",
      "command": "henio",
      "args": ["acp"],
    },
  },
}
```

### JetBrains

Use an ACP-compatible plugin and point it at:

```text
/path/to/henio-agent/acp_registry
```

## Registry manifest

The ACP registry manifest lives at:

```text
acp_registry/agent.json
```

It advertises a command-based agent whose launch command is:

```text
henio acp
```

## Configuration and credentials

ACP mode uses the same Henio configuration as the CLI:

- `~/.henio/.env`
- `~/.henio/config.yaml`
- `~/.henio/skills/`
- `~/.henio/state.db`

Provider resolution uses Henio' normal runtime resolver, so ACP inherits the currently configured provider and credentials.

## Session behavior

ACP sessions are tracked by the ACP adapter's in-memory session manager while the server is running.

Each session stores:

- session ID
- working directory
- selected model
- current conversation history
- cancel event

The underlying `AIAgent` still uses Henio' normal persistence/logging paths, but ACP `list/load/resume/fork` are scoped to the currently running ACP server process.

## Working directory behavior

ACP sessions bind the editor's cwd to the Henio task ID so file and terminal tools run relative to the editor workspace, not the server process cwd.

## Approvals

Dangerous terminal commands can be routed back to the editor as approval prompts. ACP approval options are simpler than the CLI flow:

- allow once
- allow always
- deny

On timeout or error, the approval bridge denies the request.

## Troubleshooting

### ACP agent does not appear in the editor

Check:

- the editor is pointed at the correct `acp_registry/` path
- Henio is installed and on your PATH
- the ACP extra is installed (`pip install -e '.[acp]'`)

### ACP starts but immediately errors

Try these checks:

```bash
henio doctor
henio status
henio acp
```

### Missing credentials

ACP mode does not have its own login flow. It uses Henio' existing provider setup. Configure credentials with:

```bash
henio model
```

or by editing `~/.henio/.env`.

## See also

- [ACP Internals](../../developer-guide/acp-internals.md)
- [Provider Runtime Resolution](../../developer-guide/provider-runtime.md)
- [Tools Runtime](../../developer-guide/tools-runtime.md)
