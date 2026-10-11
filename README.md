# SourceLedger / 源证

**Verifiable RAG Runtime for enterprise document workflows**

SourceLedger is a production-shaped RAG runtime: hybrid retrieval, evidence packing with validated citations, prompt-injection guards, resilience policies, PostgreSQL checkpoints and a six-tab operational console in one runnable system.

## Demo

![SourceLedger Ops Console walkthrough](docs/demo/walkthrough.gif)

Every frame above is a real request against the local runtime: a grounded answer with `[C1]`
citations, a Vector / BM25 / RRF comparison, an evidence pack under a token budget, retry and
fallback policies, an injection attempt blocked, and a PostgreSQL checkpoint recovery.

Per-tab clips: [Query](docs/demo/query.gif) | [Retrieval](docs/demo/retrieval.gif) | [Context](docs/demo/context.gif) | [Resilience](docs/demo/resilience.gif) | [Security](docs/demo/security.gif) | [Runtime](docs/demo/runtime.gif)

Full-page captures: [Query](docs/demo/query-full.png) | [Retrieval](docs/demo/retrieval-full.png) | [Context](docs/demo/context-full.png) | [Resilience](docs/demo/resilience-full.png) | [Security](docs/demo/security-full.png) | [Runtime](docs/demo/runtime-full.png)

## Review This Repo In 3 Minutes

| What you want to check | Where to look |
| --- | --- |
| It actually runs | Quick Start below, then `GET /health` and `GET /ready` |
| Not a demo-grade RAG | `Retrieval` and `Context` tabs + `docs/baseline-evaluation-report.md` |
| Real engineering, not glue code | `Resilience` and `Runtime` tabs + `runtime/resilience/`, `runtime/db/` |
| Safety is handled, not promised | `Security` tab + `runtime/security/` + security regression 5/5 |
| Numbers are reproducible | `python -m runtime.C07_capability_regression` returns 12/12 |
| Honest about limits | Known Limitations at the bottom |

## What This Project Demonstrates

- Real advanced RAG pipeline: Query Rewrite -> Vector + BM25 -> RRF -> conditional Rerank -> Context Packing -> DeepSeek generation.
- Evidence-first answers with `[C1]` citations and no-evidence abstention.
- PostgreSQL-backed run state, checkpoints and cross-process recovery.
- Redis-backed rate limiting, distributed locking and request idempotency.
- Retry, backoff, fallback and circuit breaker policies.
- Prompt-injection detection, untrusted context handling and dangerous-tool safeguards.
- A six-tab Ops Console: Query, Retrieval, Context, Resilience, Security, Runtime.
- Reproducible evaluation reports for retrieval, context, security, fault injection and load tests.

## Ops Console

Six tabs. Each one is a claim you can verify by clicking, not a mock screen:

| Tab | What you see | What it proves | Capability / evidence |
| --- | --- | --- | --- |
| Query | Grounded answer, `[C1]` citations, token usage, latency, RunTrace timeline | Retrieval really feeds generation, and answers cite real evidence | `POST /ask`, `GET /runs/{run_id}/trace` |
| Retrieval | Vector, BM25 and RRF candidates with rank and score | Hybrid retrieval is measured, not assumed | `retrieval_hybrid`, `rerank_comparison` |
| Context | Deduplication, token budget, source diversity, conflicts, injection flags | Context is packed under a budget, and version conflicts are disclosed | `context_packing` |
| Resilience | Retry, fallback, circuit breaker, rate limit, lock, idempotency, recovery | Failures are contained by policy, not improvised | `retry_backoff`, `fallback_chain`, `circuit_breaker`, `rate_limit`, `distributed_lock`, `idempotency`, `checkpoint_recovery` |
| Security | Direct and indirect injection, no-evidence abstention | Retrieved text is treated as untrusted data | `security_injection`, `security_no_evidence` |
| Runtime | RunState transitions, checkpoints, tool calls, stage-by-stage events | State survives a crash and is replayable | `checkpoint_recovery`, `runtime/db/` |

<!-- Tab clips (uncomment once docs/demo/*.gif exist):

![Query tab](docs/demo/query.gif)
![Retrieval tab](docs/demo/retrieval.gif)
![Context tab](docs/demo/context.gif)
![Resilience tab](docs/demo/resilience.gif)
![Security tab](docs/demo/security.gif)
![Runtime tab](docs/demo/runtime.gif)
-->

## Architecture

```text
React Ops Console
       |
       v
FastAPI API Layer
       |
       +--> POST /ask ------------------------------+
       |                                             |
       +--> POST /capabilities/{id}/run              |
       |                                             v
       |                                      RAGRuntime
       |                                             |
       |        +------------------------------------+
       |        |
       |        +--> Query Rewrite
       |        +--> Metadata Filter
       |        +--> Vector + BM25
       |        +--> RRF Fusion
       |        +--> Conditional Rerank
       |        +--> Context Packing / Citation
       |        +--> DeepSeek Generation
       |        +--> CapabilityEvent / RunTrace
       |
       +--> PostgreSQL: runs, checkpoints, tool_calls, idempotency
       |
       +--> Redis: rate limit, distributed lock
```

## Verified Capabilities

```text
retrieval_hybrid
rerank_comparison
context_packing
retry_backoff
fallback_chain
circuit_breaker
rate_limit
distributed_lock
idempotency
checkpoint_recovery
security_injection
security_no_evidence
```

C07 unified capability regression:

```text
registry_passed = true
capabilities     = 12/12
all_passed       = true
```

B10 advanced RAG regression:

```text
real_ask                         passed
context_conflict_and_injection   passed
no_evidence                      passed
retry_and_fallback               passed
all_passed                       true
```

## Metrics

Retrieval:

```text
Hit@1     0.9762
Recall@4  0.9881
MRR       0.9881
nDCG@4    0.9763
```

Context:

```text
invalid citation   0
citation recall    1.0
conflict covered   3/3
injection covered  2/2
context tokens avg 451
context tokens max 851
```

Resilience and security:

```text
security regression 5/5
fault injection     4/4
load requests       20
load concurrency    5
load failures       0
p50                 135.01 ms
p95                 286.89 ms
```

## API

```text
GET  /health
GET  /ready

POST /documents/upload

POST /sessions
POST /ask
POST /ask/stream
GET  /tasks/{run_id}

GET  /capabilities
POST /capabilities/{capability_id}/run
GET  /runs/{run_id}/trace
```

Swagger:

```text
http://127.0.0.1:8000/docs
```

## Quick Start

From the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1

pip install -r requirements.txt
pip install -r requirements-db.txt
pip install -r requirements-resilience.txt
```

Configure the repository-root `.env`:

```env
DEEPSEEK_API_KEY=your-key
DATABASE_URL=postgresql+psycopg://agent:agent_password@localhost:5433/agent_runtime
REDIS_URL=redis://localhost:6380/0
```

Start PostgreSQL and Redis:

```powershell
cd project_a
docker compose -f .\docker-compose.db.yml up -d
```

Apply database migrations and start the API:

```powershell
.\.venv\Scripts\alembic.exe upgrade head

.\.venv\Scripts\python.exe -m uvicorn runtime.api.S19_2_app:app --host 127.0.0.1 --port 8000
```

Start the Ops Console:

```powershell
cd frontend
npm.cmd install
npm.cmd run dev
```

Open:

```text
http://127.0.0.1:5173
http://127.0.0.1:8000/docs
```

## Example Capability Call

```powershell
$body = @{
  thread_id = "retrieval-demo"
  input = @{
    question = "What is the accommodation standard?"
    semantic_query = "What is the accommodation standard?"
    keyword_query = "accommodation standard"
    candidate_k = 5
  }
} | ConvertTo-Json -Depth 5

Invoke-RestMethod `
  -Uri "http://127.0.0.1:8000/capabilities/retrieval_hybrid/run" `
  -Method Post `
  -ContentType "application/json" `
  -Body $body
```

## Evaluation

Run the core retrieval suite:

```powershell
cd project_a
.\.venv\Scripts\python.exe .\evaluation\harness\run_full_suite.py --report-dir .\evaluation\reports\baseline-2026-10-08
```

Run the advanced RAG regression:

```powershell
.\.venv\Scripts\python.exe -B -m runtime.B10_advanced_rag_regression
```

Run the 12-capability regression:

```powershell
.\.venv\Scripts\python.exe -B -m runtime.C07_capability_regression
```

Run frontend production build:

```powershell
cd frontend
npm.cmd run build
```

## Visual Evidence

Desktop:

![Desktop Ops Console](docs/ops-console-desktop.png)

Mobile:

![Mobile Ops Console](docs/ops-console-mobile.png)

Walkthrough clips and the demo video cover belong in `docs/demo/`.

## Repository Map

```text
  runtime/            RAG runtime, resilience, security and APIs
  runtime/retrieval/ Vector, BM25, RRF and reranker
  runtime/context/   Context packing adapter
  runtime/api/       FastAPI routes and capability registry
  frontend/          React Ops Console
  evaluation/        datasets, harnesses and reports
  docs/              architecture, baselines and acceptance records
  docs/demo/         walkthrough clips for the README
```

## Known Limitations

- Rerank is condition-triggered and defaults to off to avoid unconditional CPU latency.
- The current load test uses a fake ask function and measures API, database, Redis, lock, idempotency and checkpoint paths rather than model throughput.
- SSE currently chunks a completed answer instead of streaming model tokens directly.
- Authentication, tenant isolation and full RBAC are not part of the first internship version.
- The current demo corpus is intentionally small and isolated from the enterprise-simulation roadmap.

## Roadmap

- Replace the fake ask function in the load test with a recorded model latency profile.
- Move SSE to real token streaming.
- Extend the evaluation corpus and publish a versioned retrieval quality baseline.

## Project Focus

SourceLedger is designed around one engineering principle:

```text
The model must not be the only place where correctness, state, citations,
retries, security and observability live.
```

The runtime owns those guarantees and exposes them as traceable, reproducible evidence.
