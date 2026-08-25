---
description: Verify a change end to end before considering it done
---

Do not tell me something works until all of these pass:

1. `make lint` and `make test` are green.
2. If retrieval, chunking, ranking, tools, or the agent loop changed, launch the
   `eval-runner` subagent and report the delta.
3. If `backend/ingest`, `backend/chunking`, or `backend/tools/search` changed,
   launch the `retrieval-critic` subagent.
4. If `web/` changed, launch the `frontend-reviewer` subagent.
5. Exercise the actual path a user takes, not just the unit test. Index a small
   real repo, ask a question, check that a citation resolves to the right lines.

Report what you ran and what it output. If you skipped a step, say which and
why. Never claim verification you did not perform.
