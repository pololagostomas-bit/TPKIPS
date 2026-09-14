# Reflection & Compaction

## When to Reflect

Reflection synthesizes what you've learned across multiple commits into structured insights.

**Always reflect:**
- After completing a multi-step feature (5+ commits)
- Before ending a long session
- When you notice you keep re-discovering the same things

**Consider reflecting:**
- After merging an exploration branch
- After a debugging session that taught you something
- When switching between very different problem domains

### The Reflect Cycle

```bash
# Step 1: Gather context (CLI reads git history + memory state)
amem reflect

# Step 2: Think about:
#   - What patterns emerged?
#   - Do any memories contradict each other?
#   - What knowledge is missing? What's outdated?

# Step 3: Save your reflection with structured output
amem reflect save --content "## Patterns Identified
- WebSocket reconnection needs state validation

## Decisions Validated
- PKCE for mobile OAuth confirmed as correct

## Contradictions Found
- Earlier said REST-only, now using WebSocket for streaming. Resolution: REST for CRUD, WS for real-time.

## Stale Entries
- memory/patterns.md: Use REST for all API endpoints

## Gaps Filled
- type: pattern
  text: Always validate WebSocket readiness state, not just connection status
- type: decision
  text: REST for CRUD operations, WebSocket for streaming

## Themes
- Real-time architecture is the dominant concern

## Summary
Focused on real-time reliability. Key insight: connection != readiness."
```

### Reflection Output Format

Include these sections (omit empty ones):
- `## Patterns Identified` — recurring approaches that work
- `## Lessons Learned` — problems solved: use `type: lesson`, `text:`, `problem:`, `resolution:` fields
- `## Decisions Validated` — earlier decisions confirmed by recent work
- `## Contradictions Found` — memory entries that conflict (include resolution)
- `## Stale Entries` — entries to flag as outdated (format: `file: entry text`)
- `## Gaps Filled` — new entries to add (use `type:` and `text:` sub-fields)
- `## Themes` — overarching directions
- `## Summary` — 2-3 sentences

### Reflection History

```bash
amem reflect history          # See past reflections + recurring themes
amem reflect history --last 3 # Last 3 only
```

### Memory Defrag

When memory files get large or stale:
```bash
amem reflect defrag --dry-run  # Analyze memory health (read-only)
amem reflect defrag            # Apply stale markers (non-destructive)
# Then clean up manually
amem write memory/patterns.md "<cleaned content>"
amem commit "defrag: consolidated patterns"
```

## When to Compact

Compact when your context is bloated and you want to continue with less noise.

```bash
amem compact --dry-run   # Preview what would be archived
amem compact             # Default: archive stale entries, keep pins + last 7 days
amem compact --hard      # Keep only pinned files, archive everything else
```

**Use compact when:**
- Context window is filling up mid-task
- You want lower noise without losing critical decisions
- Switching focus within the same session

**Compact always:**
- Auto-commits before running (safety net)
- Archives to `.context/archive/compact-YYYY-MM-DD/` (never deletes)
- Reports byte size before/after

**Compact vs Reflect:** Compact is a pruner (removes noise). Reflect is a synthesizer (extracts insights). Different tools, clean separation.
