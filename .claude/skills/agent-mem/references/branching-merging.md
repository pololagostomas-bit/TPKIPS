# Branching, Merging & Cleanup

## Diff — compare before merging

Compare a branch's context against main before merging:
```bash
amem diff try-qdrant              # summary view
amem diff try-qdrant --verbose    # show actual line changes
```

## Resolve — auto-resolve merge conflicts

After git operations that create merge conflicts in `.context/`:
```bash
amem resolve --dry-run   # Preview resolution strategy per file
amem resolve             # Auto-resolve all conflicts
```

**Resolution strategies (automatic):**
- `memory/` files — append-only merge (keep both sides, deduplicate exact matches)
- `config.yaml` — prefer-ours (keep local settings)
- Other files — keep-both (concatenate with separator)

## Forget — remove obsolete memory

Remove obsolete memory files (archived first for safety):
```bash
amem forget memory/old-notes.md
```

**Safety rules:**
- Cannot forget pinned `system/` files — run `amem unpin` first
- Cannot forget `config.yaml`
- Always archives to `archive/forgotten-YYYY-MM-DD/` before deleting
