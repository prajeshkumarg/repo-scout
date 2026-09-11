# repo-scout

**Live: [repo-scout.live](https://repo-scout.live)**

Agentic codebase Q&A. Paste a public GitHub repo URL, we index it, a tool-using
agent answers questions about it with `file:line` citations.

See [docs/SPEC.md](docs/SPEC.md) for architecture and
[docs/ROADMAP.md](docs/ROADMAP.md) for current status.

## Local setup

Requires Docker, `uv`, and Node 20+.

```sh
cp .env.example .env
make dev
```

`make dev` brings up postgres and redis in Docker, then runs the api, worker,
and web processes on the host.

- API: http://127.0.0.1:8000 (health at `/health`)
- Web: http://localhost:3000

## Commands

| command | what it does |
| --- | --- |
| `make dev` | starts api, worker, and web |
| `make test` | pytest |
| `make eval` | runs the eval suite against the fixture repos |
| `make lint` | ruff + tsc |

## Retrieval baseline

Retrieval recall@10, measured by `make eval` over the fixture set
(3 repos x 20 questions, ground-truth files pinned to commit SHAs):

| repo | recall@10 |
| --- | --- |
| pallets/click | 0.95 |
| pmndrs/zustand | 0.85 |
| psf/requests | 0.95 |
| **overall** | **0.92** |

Model: BAAI/bge-small-en-v1.5 (384 dims), recorded 2026-09-02. Every
change to chunking, embedding, or ranking must re-run `make eval` and
report the delta; a regression below this baseline fails CI.

### Deep mode (agent loop)

`make eval --deep` also measures the agent, over the union of every file
it read across its tool calls:

| repo | fast recall@10 | deep recall@10 |
| --- | --- | --- |
| pallets/click | 1.00 | 1.00 |
| pmndrs/zustand | 0.85 | 0.95 |
| psf/requests | 0.95 | 1.00 |
| **overall** | **0.93** | **0.98** |

Multi-hop navigation beats one-shot retrieval, and by the most where
one-shot retrieval was weakest. Deep mode is not in CI: 60 agent runs
per push is not a sane build gate.
