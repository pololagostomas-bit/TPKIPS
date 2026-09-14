# Coexistence with CLAUDE.md

If the project has a CLAUDE.md:
- `agent-mem init --from-claude` imports it into `memory/imported-claude-md.md`
- `.context/system/` becomes the living version of project conventions
- CLAUDE.md can reference `.context/` for dynamic context
- Both can coexist — CLAUDE.md for agent instructions, `.context/` for versioned memory

## Syncing to IDE rule files

Export `.context/` content to IDE rule files:
```bash
amem sync --claude    # CLAUDE.md
amem sync --codex     # AGENTS.md
amem sync --cursor    # .cursorrules
amem sync --windsurf  # .windsurfrules
amem sync --gemini    # GEMINI.md
amem sync --all       # all of the above
```
