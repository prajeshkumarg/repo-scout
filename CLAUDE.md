# repo-scout

Agentic codebase Q&A. Paste a public GitHub repo URL, we index it, a tool-using
agent answers questions about it with file:line citations.

Read @docs/SPEC.md for the architecture and @docs/ROADMAP.md for what is being
built right now. Do not start work on a milestone that is not the current one.

## Stack

- Backend + agent: Python 3.12, FastAPI, `uv` for deps. Lives in `backend/`.
- Worker: same image, RQ + Redis, background indexing jobs.
- DB: Postgres 16 + pgvector, plus Postgres FTS for exact identifier search.
- Frontend: Next.js App Router + TypeScript. Puppertino
  (`@codedgar/puppertino`) for Apple-style UI components, Tailwind for layout
  and one-off utilities. Lives in `web/`.
- Local: `docker compose up` brings up postgres and redis only. App runs on host.

## Hard rules

- Never call an LLM from a request handler that is not streaming. Indexing is
  always a background job.
- Every answer the agent produces must carry citations as `path:start-end`
  resolved against a pinned commit SHA. An answer with no citation is a bug.
- Retrieval quality is measured, not vibes. Any change to chunking, embedding,
  or ranking requires running the eval suite and reporting the delta.
- No secrets in code. Config comes from env via pydantic-settings.
- Do not add a dependency without saying why in the commit message.

## Commands

- `make dev` starts api, worker, and web
- `make test` pytest
- `make eval` runs the eval suite against the fixture repos
- `make lint` ruff + tsc

## Style

- Python: ruff, type hints everywhere, no bare except.
- Prefer boring, readable code over clever code. This is a portfolio project and
  it will be read by humans.
- Small commits with real messages.
