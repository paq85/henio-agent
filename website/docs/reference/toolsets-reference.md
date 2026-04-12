---
sidebar_position: 4
title: "Toolsets Reference"
description: "Reference for Henio core, composite, platform, and dynamic toolsets"
---

# Toolsets Reference

Toolsets are named bundles of tools that control what the agent can do. They're the primary mechanism for configuring tool availability per platform, per session, or per task.

## How Toolsets Work

Every tool belongs to exactly one toolset. When you enable a toolset, all tools in that bundle become available to the agent. Toolsets come in three kinds:

- **Core** — A single logical group of related tools (e.g., `file` bundles `read_file`, `write_file`, `patch`, `search_files`)
- **Composite** — Combines multiple core toolsets for a common scenario (e.g., `debugging` bundles file, terminal, and web tools)
- **Platform** — A complete tool configuration for a specific deployment context (e.g., `henio-cli` is the default for interactive CLI sessions)

## Configuring Toolsets

### Per-session (CLI)

```bash
henio chat --toolsets web,file,terminal
henio chat --toolsets debugging        # composite — expands to file + terminal + web
henio chat --toolsets all              # everything
```

### Per-platform (config.yaml)

```yaml
toolsets:
  - henio-cli          # default for CLI
  # - henio-telegram   # override for Telegram gateway
```

### Interactive management

```bash
henio tools                            # curses UI to enable/disable per platform
```

Or in-session:

```
/tools list
/tools disable browser
/tools enable web
```

## Core Toolsets

| Toolset | Tools | Purpose |
|---------|-------|---------|
| `browser` | `browser_back`, `browser_click`, `browser_console`, `browser_get_images`, `browser_navigate`, `browser_press`, `browser_scroll`, `browser_snapshot`, `browser_type`, `browser_vision`, `web_search` | Full browser automation. Includes `web_search` as a fallback for quick lookups. |
| `clarify` | `clarify` | Ask the user a question when the agent needs clarification. |
| `code_execution` | `execute_code` | Run Python scripts that call Henio tools programmatically. |
| `cronjob` | `cronjob` | Schedule and manage recurring tasks. |
| `delegation` | `delegate_task` | Spawn isolated subagent instances for parallel work. |
| `file` | `patch`, `read_file`, `search_files`, `write_file` | File reading, writing, searching, and editing. |
| `homeassistant` | `ha_call_service`, `ha_get_state`, `ha_list_entities`, `ha_list_services` | Smart home control via Home Assistant. Only available when `HASS_TOKEN` is set. |
| `image_gen` | `image_generate` | Text-to-image generation via FAL.ai. |
| `memory` | `memory` | Persistent cross-session memory management. |
| `messaging` | `send_message` | Send messages to other platforms (Telegram, Discord, etc.) from within a session. |
| `moa` | `mixture_of_agents` | Multi-model consensus via Mixture of Agents. |
| `search` | `web_search` | Web search only (without extract). |
| `session_search` | `session_search` | Search past conversation sessions. |
| `skills` | `skill_manage`, `skill_view`, `skills_list` | Skill CRUD and browsing. |
| `terminal` | `process`, `terminal` | Shell command execution and background process management. |
| `todo` | `todo` | Task list management within a session. |
| `tts` | `text_to_speech` | Text-to-speech audio generation. |
| `vision` | `vision_analyze` | Image analysis via vision-capable models. |
| `web` | `web_extract`, `web_search` | Web search and page content extraction. |

## Composite Toolsets

These expand to multiple core toolsets, providing a convenient shorthand for common scenarios:

| Toolset | Expands to | Use case |
|---------|-----------|----------|
| `debugging` | `patch`, `process`, `read_file`, `search_files`, `terminal`, `web_extract`, `web_search`, `write_file` | Debug sessions — file access, terminal, and web research without browser or delegation overhead. |
| `safe` | `image_generate`, `mixture_of_agents`, `vision_analyze`, `web_extract`, `web_search` | Read-only research and media generation. No file writes, no terminal access, no code execution. Good for untrusted or constrained environments. |

## Platform Toolsets

Platform toolsets define the complete tool configuration for a deployment target. Most messaging platforms use the same set as `henio-cli`:

| Toolset | Differences from `henio-cli` |
|---------|-------------------------------|
| `henio-cli` | Full toolset — all 38 tools including `clarify`. The default for interactive CLI sessions. |
| `henio-acp` | Drops `clarify`, `cronjob`, `image_generate`, `mixture_of_agents`, `send_message`, `text_to_speech`, homeassistant tools. Focused on coding tasks in IDE context. |
| `henio-api-server` | Drops `clarify`, `send_message`, and `text_to_speech`. Adds everything else — suitable for programmatic access where user interaction isn't possible. |
| `henio-telegram` | Same as `henio-cli`. |
| `henio-discord` | Same as `henio-cli`. |
| `henio-slack` | Same as `henio-cli`. |
| `henio-whatsapp` | Same as `henio-cli`. |
| `henio-signal` | Same as `henio-cli`. |
| `henio-matrix` | Same as `henio-cli`. |
| `henio-mattermost` | Same as `henio-cli`. |
| `henio-email` | Same as `henio-cli`. |
| `henio-dingtalk` | Same as `henio-cli`. |
| `henio-feishu` | Same as `henio-cli`. |
| `henio-wecom` | Same as `henio-cli`. |
| `henio-wecom-callback` | WeCom callback toolset — enterprise self-built app messaging (full access). |
| `henio-weixin` | Same as `henio-cli`. |
| `henio-bluebubbles` | Same as `henio-cli`. |
| `henio-homeassistant` | Same as `henio-cli`. |
| `henio-webhook` | Same as `henio-cli`. |
| `henio-gateway` | Union of all messaging platform toolsets. Used internally when the gateway needs the broadest possible tool set. |

## Dynamic Toolsets

### MCP server toolsets

Each configured MCP server generates a `mcp-<server>` toolset at runtime. For example, if you configure a `github` MCP server, a `mcp-github` toolset is created containing all tools that server exposes.

```yaml
# config.yaml
mcp:
  servers:
    github:
      command: npx
      args: ["-y", "@modelcontextprotocol/server-github"]
```

This creates a `mcp-github` toolset you can reference in `--toolsets` or platform configs.

### Plugin toolsets

Plugins can register their own toolsets via `ctx.register_tool()` during plugin initialization. These appear alongside built-in toolsets and can be enabled/disabled the same way.

### Custom toolsets

Define custom toolsets in `config.yaml` to create project-specific bundles:

```yaml
toolsets:
  - henio-cli
custom_toolsets:
  data-science:
    - file
    - terminal
    - code_execution
    - web
    - vision
```

### Wildcards

- `all` or `*` — expands to every registered toolset (built-in + dynamic + plugin)

## Relationship to `henio tools`

The `henio tools` command provides a curses-based UI for toggling individual tools on or off per platform. This operates at the tool level (finer than toolsets) and persists to `config.yaml`. Disabled tools are filtered out even if their toolset is enabled.

See also: [Tools Reference](./tools-reference.md) for the complete list of individual tools and their parameters.
