# repo-scout

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

## Deploying

The whole stack runs on one machine — two cores and 4 GB is enough:

Create `.env.prod` (gitignored) with:

```sh
POSTGRES_PASSWORD=       # any long random string
GOOGLE_API_KEY=          # needed to answer questions; indexing works without it
PUBLIC_WEB_URL=          # e.g. http://<server-ip>:3000
PUBLIC_API_URL=          # e.g. http://<server-ip>:8000
```

Then:

```sh
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d --build
```

That builds three images (api, worker, web) and starts them alongside
Postgres with pgvector and Redis. Only the web and api ports are
published; the database is reachable only from inside the stack.

The two `PUBLIC_*` URLs are the addresses a **browser** will use, not
internal service names: `PUBLIC_API_URL` is compiled into the client
bundle at build time, so changing it means rebuilding the web image.
`PUBLIC_WEB_URL` becomes the API's allowed CORS origin.

The embedding model is baked into the backend image, so a deploy does
not begin with a download, and a cold container serves its first request
without one.

Indexing is CPU-bound. A repo becomes browsable and answerable within
seconds regardless, but the background embedding pass that sharpens
search runs at roughly 15 chunks/second per core.

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
