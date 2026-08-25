---
paths: ["backend/agent/**", "backend/tools/**"]
---

# Agent loop rules

- Tools return structured data plus a short human-readable summary. The summary
  is what gets streamed to the UI trace, the structured part is what goes back
  to the model.
- Cap every tool output. `read_file` max 400 lines, `grep` max 50 matches,
  `search_code` max 10 chunks. Truncate with an explicit marker so the model
  knows there was more.
- Budgets are enforced in the loop, not suggested in the prompt. Steps, tokens,
  wall clock, per-tool timeout. When a budget trips, the agent gets one final
  turn to answer with what it has.
- Cancellation must propagate. Check the cancel token between steps and pass it
  into anything that blocks.
- Citations are validated against the index after generation. Never trust the
  model to have gotten line numbers right.
- Prompts live in `backend/agent/prompts/` as separate files, versioned. Do not
  inline a system prompt in a function.
- Every run writes an `agent_runs` row, including failed and cancelled runs.
