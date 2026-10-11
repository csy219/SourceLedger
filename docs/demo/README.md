# docs/demo

Recorded walkthrough of the Ops Console. Every clip is a real session against a locally
running stack: real API calls, real PostgreSQL checkpoints, real Redis locks.

```text
walkthrough.gif   all six tabs in order, with title cards
cover.png         still used as a link preview

query.gif         grounded answer, [C1] citations, token usage, run trace
retrieval.gif     Vector vs BM25 vs RRF candidates with rank and score
context.gif       dedup, token budget, evidence pack, citations
resilience.gif    retry, fallback, breaker, rate limit, lock, idempotency
security.gif      injection blocked, no-evidence abstention
runtime.gif       checkpoint recovery and run state

*-full.png        full-page captures of each tab with results loaded
```

How these were produced:

```text
1. Start PostgreSQL, Redis, the FastAPI app and the Vite dev server.
2. Index the demo PDFs through POST /documents/upload.
3. Drive a headless browser over the DevTools protocol: click each tab, run its real
   capability, and capture frames while the request is in flight.
4. Drop near-identical frames, sample evenly, and assemble GIFs.
```

To re-record, start the stack from the repository root (see Quick Start in the root README)
and repeat step 3 with the same tab order.
