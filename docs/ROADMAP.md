# Roadmap

Work one milestone at a time. Do not start the next one until the exit criteria
pass. Update the status markers in this file as you go.

Legend: `[ ]` not started, `[~]` in progress, `[x]` done

---

## M0. Skeleton `[x]`

Repo layout, `docker compose` for postgres + redis, `uv` project in `backend/`,
Next.js app in `web/`, Makefile, ruff, pytest, one passing test, one health
endpoint the frontend hits and renders.

**Exit:** `make dev` works from a clean clone, `make test` and `make lint` pass.

## M1. Ingest, CLI only `[x]`

No web. A command `python -m ingest <github-url>` that clones, filters, parses
with tree-sitter, chunks at symbol boundaries, embeds, and writes to Postgres.
Python and TypeScript only. Plus `python -m search "<query>"` that does hybrid
retrieval and prints path, line range, and snippet.

**Exit:** index three real repos, and manual spot checks show the retriever
finds the right file for ten obvious questions.

Result (Sep 2026): indexed pallets/click, pmndrs/zustand, fastapi/fastapi.
Spot checks: 9/10 right file in top-10 with natural phrasing, 10/10 when the
question carries the identifier (the one miss: "how is the FastAPI app class
defined" buries applications.py under docs examples that literally match
every word; it ranks #5 on "FastAPI class definition"). Known and noted for
M2, where the eval suite prices fixes instead of vibes.

Notes carried into M2:
- Embeddings are local (fastembed, bge-small-en-v1.5, 384 dims) after the
  Gemini free-tier quota blocked indexing; fp32 BERT-size models take ~1h
  per repo on CPU. Hosted/bigger models are an M2 measured swap.
- tree-sitter pinned <0.26 (runtime 0.26 corrupts 0.25-era grammar trees).
- Chunk budget is 6000 chars (~1500 tokens); oversized signatures are
  capped, and the splitter emits no duplicate line ranges.

## M2. Evals `[x]`

Fixture set of 3 repos x 20 questions with labelled ground-truth files.
`make eval` reports retrieval recall@10. This is the baseline every later
milestone is compared against. Write the number in the README.

**Exit:** `make eval` runs green and prints a table. Baseline recorded.

Result (Sep 2026): recall@10 baseline = **0.92** (click 0.95, zustand
0.85, requests 0.95), bge-small-en-v1.5, recorded in the README and
evals/results/baseline.json. CI runs `make eval --check-regression` on
every push to main; a drop > 0.02 fails the build. Re-runs vary by about
0.01 (ONNX thread nondeterminism); the tolerance absorbs it.

Notes carried into M3:
- The five baseline misses are genuine retrieval misses, not indexing
  gaps — the ground-truth files are in the index. Deep mode gets measured
  against these exact questions.
- Answer quality (LLM-as-judge, citation validity) lands with M3's
  fast-mode answerer; there was nothing to judge until now.

## M3. Agent loop `[x]`

The seven tools from the spec, the loop with step and token budgets, citation
validation. Still CLI. Add a deep-mode row to the eval output.

**Exit:** deep mode beats the M2 baseline on recall. If it does not, fix it
before moving on, that is the whole thesis of the project.

Result (Sep 2026): deep recall@10 = **0.98** vs the 0.92 baseline, and vs
0.93 for fast mode measured in the same run. Per repo (fast -> deep):
click 1.00 -> 1.00, zustand 0.85 -> 0.95, requests 0.95 -> 1.00. The gain
lands exactly where one-shot retrieval was weakest, which is the thesis.

Deep mode is measured over the union of files the agent read, via
`make eval --deep`; CI still gates on fast-mode recall only, because 60
agent runs per push is not a sane build gate.

Read that comparison with one caveat. The spec's deep metric is the
union of everything the agent read, and a single search_code call
returns up to 10 files -- roughly fast mode's whole top-10. Fast mode
saw 5.7 files per question on average; deep mode, at a median of 2
steps, sees more. So some of 0.93 -> 0.98 is breadth, not only smarter
navigation. The eval now records files-per-question alongside deep
recall so the next run makes that visible instead of implied.

Notes carried into M4:
- One miss in 60: zustand "how does shallow equality comparison work".
  The ground truth is src/shallow.ts, which is only a re-export; the
  implementation is src/vanilla/shallow.ts. The fixture is probably
  wrong, not the agent -- worth revisiting rather than tuning to it.
- Free-tier LLM quota shapes everything: gemini-3.5-flash allows 20
  requests/DAY, so the agent defaults to gemini-3.5-flash-lite (15/min).
  A full deep eval takes ~30-60 min of wall clock at that rate.
- LLM-as-judge answer quality is still not implemented; there is no
  fast-mode answerer to judge yet. Citation validity is enforced in the
  agent but not reported as an eval metric.

## M4. API `[x]`

FastAPI. SSE streaming with the typed event contract in the spec. Background
indexing via RQ with progress events. Conversations and `agent_runs` persisted.

**Exit:** `curl` an index request and a question, see well-formed event streams
for both.

Result (Sep 2026): both streams verified by curl against a live server.
`POST /index` on zustand streamed progress per stage (clone, filter,
chunk, embed, write) then done; `POST /conversations/{id}/messages`
streamed step_start/step_result for three tool calls, the answer, two
citation events, and done with steps/tokens/ms. Messages, citations,
index_runs, and agent_runs (linked to the assistant message) all
persisted.

Notes carried into M5:
- macOS kills a forked RQ work-horse the moment it touches the Obj-C
  runtime through our native deps (signal 6, before our code runs).
  worker/main.py re-execs itself once with
  OBJC_DISABLE_INITIALIZE_FORK_SAFETY set; Linux is unaffected.
- The progress stream runs its blocking Redis reads via asyncio.to_thread
  and gives up after an hour: a work-horse can die without ever updating
  its own row, which otherwise holds the stream open forever.
- token carries the validated answer in one event, not raw generation:
  citations are post-validated and stripped, so streaming raw tokens
  would stream citations we are about to delete. Real token streaming
  needs the final turn streamed separately, which M5 can revisit.

## M5. Frontend `[x]`

Split pane, streamed step trace, code viewer wired to citations, orientation
landing page, working cancel button.

**Exit:** paste a repo you have never indexed, watch it index live, ask three
questions, click a citation and land on the right lines.

Result (Sep 2026): verified against sindresorhus/ky, never indexed
before. Indexing streamed six live stages (clone, filter, chunk, embed,
write, done). Three questions answered with citations. The citation
source/utils/timeout.ts:9-32 resolves to exactly the timeout()
function, so clicking a citation lands on the right lines.

Layout diverges from the original spec and SPEC.md was updated to match:
code browser left, chat right, and the browser navigable in its own
right (tree, symbol outline, deep-linkable ranges).

Notes carried into M6:
- Free-tier rate limits are the user-visible bottleneck: one of the
  three questions took 110s, nearly all of it waiting on quota. A paid
  key removes it; nothing in the code needs to change.
- The agent sometimes calls search_code repeatedly instead of reading a
  file it has already found. The tool descriptions could push harder
  toward find_symbol then read_file, and the eval would price that.
- No frontend tests: `make lint` runs tsc only. Component tests would
  need a runner, which M6 can weigh against deploy work.

## M6. Hardening `[ ]`

Auth, rate limits, size caps, shared cache, incremental reindex on new commits
via git diff, traces page, deploy.

**Exit:** deployed and usable by someone who is not you.

---

## Deliberately later

Streaming multi-repo comparison, PR review, other languages beyond Python and
TypeScript, self-hosting docs.

### Design pass (deferred, not dropped)

The UI works and reads clearly, but its look is still Puppertino's
defaults plus Tailwind layout. Worth a deliberate pass when there is a
direction to aim at:

- A token layer of our own over Puppertino's variables, so the palette
  is a decision rather than a framework default.
- The chat and code panes have had the most iteration; home, indexing
  and the repo landing have had the least.
- Empty, error and cancelled states exist but are plain.
- Nothing has been checked below a laptop width.
