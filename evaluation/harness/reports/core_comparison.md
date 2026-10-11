# Harness Core Comparison

## Summary

| runner | retrieval_accuracy | hit_at_1 | hit_at_k | recall_at_k | mrr | ndcg_at_k | latency_ms_avg | context_tokens_avg |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| vector | 0.9783 | 0.9286 | 1.0 | 0.9881 | 0.9563 | 0.9569 | 24.962 | 787.0217 |
| bm25 | 0.8696 | 0.7381 | 1.0 | 0.9643 | 0.8611 | 0.8739 | 0.6665 | 975.9783 |
| hybrid | 0.9783 | 0.9762 | 1.0 | 0.9881 | 0.9881 | 0.9763 | 30.6246 | 911.0435 |

## Failures

- all_failed=['E33']
- hybrid_fixes=[]
- hybrid_regressions=[]

## Best Metrics

- hit_at_1: hybrid (0.9762)
- recall_at_k: vector (0.9881)
- context_tokens_avg: vector (787.0217)
- hit_at_k: vector (1.0)
- mrr: hybrid (0.9881)
- latency_ms_avg: bm25 (0.6665)
- retrieval_accuracy: vector (0.9783)
- ndcg_at_k: hybrid (0.9763)
