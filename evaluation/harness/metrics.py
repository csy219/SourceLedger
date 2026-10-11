# 这段代码是 **S14 Harness 的「统一指标计算器」**，对应你规划的 `metrics.py` 模块。
# 核心作用：把所有测试用例的单例运行结果，汇总成**口径完全统一的整体评测指标**。不管是向量检索、BM25、混合检索，还是开不开上下文打包，指标定义、计算方式完全一致，结果可以直接横向对比。

# 一共覆盖四大类指标：

# 1. **检索效果指标**：准确率、Hit@k、Recall@k、MRR、NDCG
# 2. **性能指标**：延迟的平均值、分位数、最大值
# 3. **上下文质量指标**：上下文 token 规模、来源多样性、重复文本数、无效引用数
# 4. **异常统计**：冲突案例数、失败案例数、预算超限数


import math
import statistics
from typing import Any

# safe_mean：安全求平均值
def safe_mean(values:list[float])->float:
    if not values:
        return 0.0
    return round(statistics.mean(values),4)

# 2. percentile：百分位数计算
# 延迟列表 `[10, 12, 15, 20, 100]`，算 P95：

# - 比例 0.95，索引 = (5-1)*0.95 = 3.8 → 取整 3
# - 返回 `ordered[3] = 20`
def percentile(
        values:list[float],
        ratio:float,
)->float:
    if not values:
        return 0.0

    ordered=sorted(values)
    index=int((len(ordered)-1)*ratio)
    return round(ordered[index],2)

# 3. binary_ndcg：二值化 NDCG
# 第一步：计算 DCG（折损累计增益）
# 第二步：计算 IDCG（理想折损累计增益）
# 第三步：归一化得到 NDCG
def binary_ndcg(
        ranks:list[int | None],
)->float:
    if not ranks:
        return 0.0
    dcg=0.0
    for rank in ranks:
        if rank is None:
            continue
        dcg+=1.0/math.log2(rank+1)

    ideal_ranks=list(range(1,len(ranks)+1))
    idcg=sum(
        1.0/math.log2(rank+1)
        for rank in ideal_ranks
    )

    if idcg==0:
        return 0.0
    return round(dcg/idcg,4)

# summarize_rows：主汇总函数
def summarize_rows(
        rows:list[dict[str,Any]],
        metric_k:int,
)->dict[str,Any]:
    retrieval_values=[
        1.0 if row["retrieval_ok"] else 0.0
        for row in rows
    ]
    latencies=[
        float(row["latency_ms"])
        for row in rows
    ]
    context_tokens=[
        int(row["context_tokens_est"])
        for row in rows
    ]
    context_chars = [
        int(row["context_chars"])
        for row in rows
    ]
    diversity_values = [
        float(row["source_diversity"])
        for row in rows
    ]

    cases_with_expected = [
        row
        for row in rows
        if row.get("ranks")
    ]
    hit_at_1_values: list[float] = []
    hit_at_k_values: list[float] = []
    recall_values: list[float] = []
    ndcg_values: list[float] = []

    for row in cases_with_expected:
        ranks=[
            rank
            for rank in row["ranks"]
        ]

        hit_at_1_values.append(
            1.0
            if any(rank==1 for rank in ranks)
            else 0.0
        )
        hit_at_k_values.append(
            1.0
            if any(rank is not None for rank in ranks)
            else 0.0
        )

        matched=sum(
            1
            for rank in ranks
            if rank is not None
        )

        recall_values.append(
            matched/len(ranks)
        )
        ndcg_values.append(
            binary_ndcg(ranks)
        )

        invalid_citation_count = sum(
        len(row["invalid_citation_ids"])
        for row in rows
    )
    duplicate_text_count = sum(
        int(row["duplicate_text_count"])
        for row in rows
    )
    retrieval_failed_rows = [
        row
        for row in rows
        if not row["retrieval_ok"]
    ]

    pipeline_failed_rows = [
        row
        for row in rows
        if row.get("failed_reasons")
    ]

    conflict_rows = [
        row
        for row in rows
        if row.get("conflict", {}).get(
            "has_conflict"
        )
    ]

    budget_violation_count = sum(
        1
        for row in rows
        if "budget_exceeded"
        in row.get("failed_reasons", [])
    )

    return {
        "cases": len(rows),
        "retrieval_accuracy": safe_mean(
            retrieval_values
        ),
        "cases_with_expected_sources": len(
            cases_with_expected
        ),
        "hit_at_1": safe_mean(hit_at_1_values),
        "hit_at_k": safe_mean(hit_at_k_values),
        "recall_at_k": safe_mean(recall_values),
        "mrr": safe_mean(
            [
                float(row["reciprocal_rank"])
                for row in cases_with_expected
            ]
        ),
        "ndcg_at_k": safe_mean(ndcg_values),
        "latency_ms_avg": safe_mean(latencies),
        "latency_ms_p50": percentile(
            latencies,
            0.5,
        ),
        "latency_ms_p95": percentile(
            latencies,
            0.95,
        ),
        "latency_ms_max": (
            round(max(latencies), 2)
            if latencies
            else 0.0
        ),
        "context_tokens_avg": safe_mean(
            [float(value) for value in context_tokens]
        ),
        "context_tokens_max": (
            max(context_tokens)
            if context_tokens
            else 0
        ),
        "context_chars_avg": safe_mean(
            [float(value) for value in context_chars]
        ),
        "source_diversity_avg": safe_mean(
            diversity_values
        ),
        "duplicate_text_count": (
            duplicate_text_count
        ),
        "invalid_citation_count": (
            invalid_citation_count
        ),
        "budget_violation_count": (
            budget_violation_count
        ),
        "conflict_cases": len(conflict_rows),
        "retrieval_failed_cases": len(
            retrieval_failed_rows
        ),
        "retrieval_failed_ids": [
            row["case_id"]
            for row in retrieval_failed_rows
        ],
        "pipeline_failed_cases": len(
            pipeline_failed_rows
        ),
        "pipeline_failed_ids": [
            row["case_id"]
            for row in pipeline_failed_rows
        ],
        "failed_cases": len(
            set(
                row["case_id"]
                for row in (
                    retrieval_failed_rows
                    + pipeline_failed_rows
                )
            )
        ),
        "failed_ids": sorted(
            set(
                row["case_id"]
                for row in (
                    retrieval_failed_rows
                    + pipeline_failed_rows
                )
            )
),
    }
    