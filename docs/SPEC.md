# repo-scout spec

## Problem

A developer lands on an unfamiliar open source repo and wants to get oriented:
what does this do, where does X happen, how do I run it, which files do I touch
to fix issue #123. Reading the source cold is slow. Naive RAG over code is bad
because code answers need multi-hop navigation, not nearest-neighbour snippets.

## Shape of the system

Two layers: precompute at index time, agentic navigation at query time.

### Layer 1: ingest (background job, keyed on commit SHA)

1. Shallow clone the repo at the default branch. Record the SHA. Everything
   downstream is keyed on `(repo_id, sha)` so indexing is idempotent.
2. Filter files. Drop: binaries, lockfiles, `vendor/`, `node_modules/`,
   minified bundles, generated code, anything over 1 MB, anything matching
   `.gitignore`. Keep source, config, docs, CI files.
3. Parse each source file with tree-sitter. Chunk at function and class
   boundaries, never fixed token windows. If a symbol is larger than the chunk
   budget, split it but keep the signature in every piece.
4. Each chunk carries: repo_id, sha, path, language, symbol_name, symbol_kind,
   start_line, end_line, parent_symbol, imports.
5. Build a symbol table: name to definition site. Build a coarse import graph
   at file level. These power `find_symbol` and `find_references`.
6. Embed chunks. Write to pgvector. Also write a tsvector column for exact
   identifier search.
7. Summarize hierarchically: one line per file, rolled up per directory, rolled
   up into a repo overview. Cheap model, run in parallel, cache by file hash.
8. Detect entry points: `main.*`, `cmd/`, `src/index.*`, `manage.py`, Dockerfile,
   CI config, package manifests. Extract run instructions from the README.
9. Write an `orientation` record: what it does, stack, entry points, how to run
   locally, five files a newcomer should read first.

Progress for every step is published to a Redis channel and streamed to the UI
over SSE. Indexing a mid-size repo should be under three minutes.

### Layer 2: query

Two modes, both streamed.

**Fast mode.** Hybrid retrieval (vector + FTS, reciprocal rank fusion), rerank,
single LLM call with the top chunks. Sub-second target. Good for "what does
function X do".

**Deep mode.** Tool-calling agent loop. Tools:

| tool | signature | notes |
| --- | --- | --- |
| `search_code` | `(query: str, k: int = 10)` | hybrid retrieval, returns chunks with path and line range |
| `grep` | `(pattern: str, glob: str = "**")` | exact, ripgrep semantics, capped output |
| `read_file` | `(path: str, start: int, end: int)` | max 400 lines per call |
| `list_dir` | `(path: str)` | one level |
| `find_symbol` | `(name: str)` | definition sites from the symbol table |
| `find_references` | `(name: str)` | call sites, best effort |
| `git_log` | `(path: str, n: int = 10)` | for "why is this here" questions |

Loop constraints, all enforced in code and all configurable:
- max 20 steps
- max 120k tokens per run
- 20 s timeout per tool call, 180 s per run
- run is cancellable mid-flight, cancellation propagates into the tool loop

The agent must cite. The final answer is post-validated: every `path:start-end`
it emits is checked against the index for that SHA. Invalid citations are
stripped and the model is asked once to retry.

### Streaming contract

The API streams typed events over SSE. The UI renders each as a step in a
collapsible trace:

```
{"type": "step_start", "step": 3, "tool": "grep", "args": {...}}
{"type": "step_result", "step": 3, "summary": "12 matches in 4 files"}
{"type": "token", "text": "..."}
{"type": "citation", "path": "src/auth/session.py", "start": 40, "end": 118}
{"type": "done", "steps": 7, "tokens": 41200, "ms": 9400, "cost_usd": 0.031}
```

## Data model

- `repos(id, owner, name, default_branch, stars, last_indexed_sha, status)`
- `index_runs(id, repo_id, sha, status, started_at, finished_at, stats jsonb)`
- `chunks(id, repo_id, sha, path, language, symbol_name, symbol_kind, start_line, end_line, content, embedding vector, tsv tsvector)`
- `symbols(id, repo_id, sha, name, kind, path, line)`
- `file_summaries(repo_id, sha, path, summary, file_hash)`
- `orientation(repo_id, sha, payload jsonb)`
- `conversations(id, repo_id, user_id, created_at)`
- `messages(id, conversation_id, role, content, citations jsonb)`
- `agent_runs(id, message_id, mode, steps jsonb, tokens, cost_usd, latency_ms)`

`agent_runs` is not optional. It backs the traces page.

## Frontend

Styling is Puppertino (`@codedgar/puppertino`, an Apple Human Interface
Guidelines CSS framework) for components -- buttons, forms, modals, segmented
controls, cards, dark mode -- plus Tailwind for layout and one-off utilities.
Puppertino ships modular CSS, so import only the modules a route uses. The
split pane, step trace, and code viewer are custom layout and are Tailwind's
job; anything that looks like a control is Puppertino's.

Split pane. Left: the code browser. Right: chat with the streamed step trace
above each answer, each step collapsible, showing tool name and a one-line
result summary. Top: repo header with SHA, index freshness, reindex button.

(The panes are code-left/chat-right: reading code is the wider, more
persistent surface, and the eye lands on it first.)

The code browser is navigable in its own right, not only a citation
target: a file tree, a symbol outline for the open file (from the symbol
table), and a viewer with line numbers that deep-links to
`?path=...&lines=99-100`. Clicking a citation in chat opens the file,
scrolls to the range, and highlights it.

Home is a single centered repo-URL input, with a short numbered
explanation of how the system works beneath it, and a couple of example
repos. Nothing else competes with the input.

Landing state for a freshly pasted repo is the `orientation` payload,
rendered as a page, with suggested starter questions. The user should get
value before typing anything.

Orientation is **derived, not generated**: entry points by filename,
stack from package manifests, languages and key files from the symbol
table, README as-is, and starter questions built from real symbol names.
Opening a repo costs zero model calls. Per-file summarization (the
original ingest step 7) is dropped: it never fed retrieval, only this
page, and one cached overview call would serve it better if prose is
ever wanted.

## Evals

`evals/` holds a fixture set: 3 repos, 20 questions each, with a labelled
ground-truth file set per question.

Two metrics, reported separately:
- **Retrieval recall@k**: did the ground-truth files appear in what the system
  read at all. Measured for fast mode retrieval and for the union of everything
  the agent read in deep mode.
- **Answer quality**: LLM-as-judge against a reference answer, plus a hard
  citation-validity check.

`make eval` prints a table and writes JSON to `evals/results/`. Runs in CI on
every push to main. Regressions in recall are a failing build.

## Non-goals

Private repos. Write access to any repo. Multi-repo search. IDE plugins.
Anything beyond public GitHub read-only.

## Cost and abuse controls

Per-repo file count cap and total-bytes cap, reject above it with a clear
message. Per-IP rate limit on index requests. Shared cache: if a repo is already
indexed at that SHA, reuse it. Popular repos get indexed once for everyone.
