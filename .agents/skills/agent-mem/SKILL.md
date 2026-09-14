---
name: agent-mem
description: Persistent, git-backed memory across sessions. Use at session start (snapshot), after decisions/fixes/mistakes (remember/lesson), to checkpoint work (commit), before risky exploration (branch), or to check prior context (search).
argument-hint: "[command] [args] — e.g., snapshot, remember --decision <text>, lesson \"problem -> fix\", commit <msg>"
---

# agent-mem

Git-backed memory for coding sessions via the `amem` CLI.

If `$ARGUMENTS` is provided, run `agent-mem $ARGUMENTS` and show output.

## When to Use (triggers)

**Starting a session →** `amem snapshot`
Load context tree, pinned files, memory summary. Run `amem init` if no `.context/` exists.

**You chose between alternatives →** `amem remember --decision "chose X because Y"`

**You noticed a repeatable approach →** `amem remember --pattern "always do X before Y"`

**You did something wrong →** `amem remember --mistake "never do X"`

**You solved a problem after investigation →** `amem lesson "problem -> how you fixed it"`
Use the `->` shorthand, or `--problem`/`--resolution`/`--tags` flags for richer entries.

**You completed meaningful work →** `amem commit "what you did"`

**You're about to try something that might not work →** `amem branch name "purpose"`
Merge back with findings: `amem merge name "outcome"`. Even failed branches are valuable.

**You're about to make a decision that might have prior context →** `amem search "query"`

**Session is long, you've learned a lot →** `amem reflect`
Synthesizes patterns, lessons, stale entries from recent activity.

## Quick Reference

```bash
amem snapshot                          # start of session
amem remember --decision "text"        # decision / --pattern / --mistake / --note
amem lesson "problem -> resolution"    # problem you solved
amem commit "message"                  # checkpoint progress
amem branch name "purpose"             # explore uncertain idea
amem merge name "outcome"              # merge back findings
amem search "query"                    # check prior context
amem read <path>                       # read specific file
amem write <path> --content "text"     # write specific file
amem pin <path> / amem unpin <path>    # manage pinned files (system/)
amem reflect                           # gather reflection input
amem compact [--dry-run|--hard]        # archive stale context
amem status / amem config / amem help  # info commands
```

## Remember vs Lesson

**Remember** = one-liner facts: decisions, patterns, mistakes, notes.
**Lesson** = problem + resolution pair. If you investigated and fixed something, it's a lesson.

## References

- [Reflection & compaction](references/reflection-compaction.md)
- [Branching & merging](references/branching-merging.md)
- [Sub-agent patterns](references/sub-agent-patterns.md)
- [Collaboration & sharing](references/collaboration.md)
- [Coexistence with CLAUDE.md](references/coexistence.md)
