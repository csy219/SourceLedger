# SourceLedger Architecture

## 1. Data Ingest

```text
PDF
  |
  v
Page parser
  |
  v
Chunk strategies
  - fixed
  - structure-aware
  - semantic
  - parent-child
  |
  v
Embedding / BM25 index
  |
  v
Chroma / in-memory keyword index
```

## 2. Retrieval

```text
Question
  |
  v
Query rewrite
  |
  v
Metadata filter
  |
  +------------------+
  |                  |
  v                  v
Vector search      BM25 search
  |                  |
  +--------+---------+
           |
           v
       RRF fusion
           |
           v
    optional rerank
```

## 3. Context Integrity

```text
RRF candidates
  |
  v
Deduplicate by normalized text hash
  |
  v
Round-robin by source/page
  |
  v
Page/parent/token limits
  |
  v
Citation IDs
  |
  v
Conflict and injection detection
```

## 4. Runtime

```text
RunState
  |
  +--> ContextState
  +--> ToolCallRecord

Request
  |
  v
RequestIdempotencyService
  |
  v
RunStateRepository
  |
  v
DatabaseCheckpointer
```

## 5. API

```text
FastAPI
  |
  +--> /health
  +--> /ready
  +--> /documents/upload
  +--> /sessions
  +--> /ask
  +--> /ask/stream
  +--> /tasks/{run_id}
```

## 6. Consistency Boundaries

- Request idempotency key protects duplicate requests.
- Tool idempotency key protects repeated tool execution.
- Checkpoint is written before and after side-effect tools.
- PostgreSQL stores durable Run and checkpoint snapshots.
- Redis stores rate limits and distributed locks.
- Untrusted retrieved text is never treated as system instructions.
