---
paths: ["backend/api/**"]
---

# API rules

- No LLM call inside a non-streaming request handler. Anything slow is either
  streamed or queued.
- SSE events follow the typed contract in docs/SPEC.md exactly. If you need a
  new event type, add it to the spec in the same commit.
- Pydantic models for every request and response body. No raw dicts crossing
  the boundary.
- Errors are structured: code, message, and whether the client should retry.
  A stream that dies must emit an error event before closing.
