# Sub-Agent Patterns

## Spawn Template

Embed amem calls as workflow steps (not a separate block). Agents skip separate instruction blocks but follow numbered steps.

```
STEP 1: Run amem snapshot — read the output, this is your starting context.
STEP 2: [First item of actual work]. Then run: amem remember --note "<what you found>"
STEP 3: [Next item]. Then run: amem remember --note "<what you found>"
...continue pattern: do work → save finding...
STEP N (every 3 items): Run amem commit "checkpoint: items 1-3 done"
FINAL STEP: Write output file, then run: amem commit "done: <summary>"
```

**Key principle:** Interleave amem into the task flow. Make `remember` the step right after each research item, not a separate section the agent can skip.

## Retry/Resume Template

For sub-agents retrying a timed-out task:

```
STEP 1: Run amem snapshot — review what the previous run saved.
STEP 2: Run amem read memory/notes.md — these are completed items, skip them.
STEP 3: Continue from the first item NOT in notes.md.
```

## Splitting Large Tasks

Never spawn one agent for 15+ sequential operations. Split instead:

**Bad:** 1 agent x 20 items x (search + fetch + analyze) = timeout

**Good:** 4 agents x 5 items each = parallel, each checkpoints independently

```bash
# Each sub-agent gets its own branch:
amem branch batch-1 "items 1-5"
amem branch batch-2 "items 6-10"

# After all complete, merge branches:
amem merge batch-1 "findings from items 1-5"
amem merge batch-2 "findings from items 6-10"
amem commit "consolidated all research"
```

## Timeout Recommendations

| Task type | Recommended timeout |
|-----------|-------------------|
| Simple (1-3 tool calls) | 120-300s |
| Research (5-10 searches) | 600s |
| Deep research (10+ searches) | 900s |
| Code review | 600s |
| Browser automation | 300-600s |

## Model Selection for Sub-Agents

- **Sonnet/Haiku** for research tasks — faster, cheaper, less likely to timeout
- **Opus** for complex reasoning, code architecture decisions
