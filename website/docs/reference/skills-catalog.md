---
sidebar_position: 5
title: "Bundled Skills Catalog"
description: "Catalog of the bundled skills currently seeded on fresh Henio installs"
---

# Bundled Skills Catalog

Fresh Henio installs currently seed a deliberately small bundled core copied from the repository's `skills/` directory into `~/.henio/skills/`.

:::info Existing installs may show more skills
`henio update` updates manifest-tracked bundled skills, but it does **not** purge skills you already have in `~/.henio/skills/`. If you used an older release or installed additional skills from the Hub, your local skill list may be larger than the catalog below.
:::

Looking for more? See the [Official Optional Skills Catalog](/docs/reference/optional-skills-catalog) or browse the Hub with `henio skills browse`.

## autonomous-ai-agents

Skills for spawning and orchestrating autonomous AI coding agents and multi-agent workflows — running independent agent processes, delegating tasks, and coordinating parallel workstreams.

| Skill | Description | Path |
|-------|-------------|------|
| `henio-agent` | Complete guide to using and extending Henio Agent — CLI usage, setup, configuration, spawning additional agents, gateway platforms, skills, voice, tools, profiles, and contributor workflows. | `autonomous-ai-agents/hermes-agent` |
| `opencode` | Delegate coding tasks to OpenCode CLI agent for feature implementation, refactoring, PR review, and long-running autonomous sessions. Requires the `opencode` CLI installed and authenticated. | `autonomous-ai-agents/opencode` |

## devops

DevOps and infrastructure automation skills.

| Skill | Description | Path |
|-------|-------------|------|
| `webhook-subscriptions` | Create and manage webhook subscriptions for event-driven agent activation. Use when external services should trigger agent runs automatically. | `devops/webhook-subscriptions` |

Workflow commands such as `/plan` are documented in the [Slash Commands Reference](/docs/reference/slash-commands). They are not part of the current bundled-skills seed set.
