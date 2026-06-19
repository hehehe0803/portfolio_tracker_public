# Worktree Helper Guide (Minimal)

This guide documents the minimal worktree helpers for creating, listing, and navigating worktrees.

## Setup

Source the helpers once per shell:
```
source docs/worktree-codex.bashsource
```

To make this permanent, add the line to `~/.bashrc`.

## Commands

- Create a new worktree + branch: `gwa <todo-id> [base]`
- Remove the current worktree + branch: `gwd`
- List worktrees: `gwl`
- Navigate to a worktree: `gwcd <todo-id>`
- Return to main repo root: `gwcd`

Worktrees are stored under `../<repo-name>.worktrees/<branch>`.

## Example
```
# From the main repo root

gwa ingest-xtb-001

gwcd ingest-xtb-001
# ...do work...

gwcd

gwl
```
