# uk-property-mcp Skills

Agent skills for the uk-property-mcp server. These follow the [agentskills.io](https://agentskills.io) specification and are discovered automatically when Claude Code is opened in this repo.

## Available Skills

| Skill | Description |
|---|---|
| [property-report](property-report/) | Analyse a specific UK property or area — comps, EPC, rental yield, stamp duty |
| [property-search](property-search/) | Find UK properties matching investment criteria — budget, area, yield target |

## Planned Skills

| Skill | Status | Dependency |
|---|---|---|
| block-buy | Planned | Requires `property_blocks` MCP tool (service exists in `property_core/block_service.py`, not yet exposed) |

## Installation

Skills are auto-discovered when Claude Code is opened in this repository.

To make skills available across all projects, copy or symlink to your user skills directory:

```bash
# Copy (snapshot — won't update with repo)
cp -r .agents/skills/property-report ~/.agents/skills/
cp -r .agents/skills/property-search ~/.agents/skills/

# Symlink (stays in sync with repo)
ln -s $(pwd)/.agents/skills/property-report ~/.agents/skills/property-report
ln -s $(pwd)/.agents/skills/property-search ~/.agents/skills/property-search
```

For Claude Code specifically, the user skills directory is `~/.claude/skills/`:

```bash
ln -s $(pwd)/.agents/skills/property-report ~/.claude/skills/property-report
ln -s $(pwd)/.agents/skills/property-search ~/.claude/skills/property-search
```
