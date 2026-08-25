---
paths: ["backend/ingest/**", "backend/chunking/**"]
---

# Ingest rules

- Chunk at tree-sitter symbol boundaries. Never fixed token windows, never
  line-count splits. If you are tempted, the answer is a smaller symbol, not a
  smaller window.
- Every chunk keeps its full symbol signature even when a large body is split.
  A chunk with no signature is unretrievable in practice.
- Everything is keyed on (repo_id, sha). Re-running ingest on the same SHA must
  be a no-op, not a duplicate insert. Enforce with a unique constraint.
- Skip lists live in one place, `backend/ingest/filters.py`. Do not scatter
  path checks across the pipeline.
- File summaries are cached by file content hash, not by path. A rename must
  not trigger a re-summarize.
- Parsing must never crash the job. A file that fails to parse is logged, falls
  back to whole-file chunking, and the run continues.
- Publish a progress event at every stage boundary. The UI depends on it.
