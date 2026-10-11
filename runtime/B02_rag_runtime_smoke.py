"""Smoke test for B02 Query Rewriter and RAGRuntime."""

from __future__ import annotations

from dotenv import load_dotenv

from runtime.B02_query_rewriter import (
    QueryRewriter,
)
from runtime.rag_runtime import (
    RAGRuntime,
)
from runtime.rag_contracts import (
    RAGRequest,
    RetrievalFilters,
    TraceStatus,
)

load_dotenv()

# 二、`FailingLLM` 模拟失败模型
# - 一个极简的 Mock 类，只有 `invoke` 方法，调用就抛异常
# - **作用**：模拟大模型调用失败的场景，不用真的让 API 挂掉，就能稳定测试降级逻辑
# - 因为 `QueryRewriter` 支持注入 LLM 客户端，所以直接把这个对象传进去即可
class FailingLLM:
    def invoke(self, messages):
        raise RuntimeError(
            "forced query rewrite failure"
        )


# 三、测试用例 1：真实查询重写
def test_real_query_rewrite()->None:
    request = RAGRequest(
        question=(
            "只看最新的差旅报销制度，"
            "住宿标准是多少？"
        ),
        thread_id="smoke-b02-real",
    )

    runtime = RAGRuntime(
        rewriter=QueryRewriter()
    )

    result = runtime.prepare(request)

    # 断言验证点
    # 断言	验证目标
    # fallback_used is False	正常调用成功，没有触发降级
    # 语义 / 关键词查询非空	重写输出了有效结果
    # len(result.trace) == 2	产生了 2 个追踪事件（接收 + 重写），追踪逻辑正常
    # 第二个事件状态为 SUCCEEDED	追踪状态标记正确
    # Token 数 > 0	真实调用了 API，产生了实际消耗
    assert (
        result.rewrite.fallback_used
        is False
    )
    assert (
        result.rewrite.semantic_query
    )
    assert (
        result.rewrite.keyword_query
    )
    assert len(result.trace) == 2
    assert (
        result.trace[1].status
        is TraceStatus.SUCCEEDED
    )
    assert (
        result.rewrite.usage.total_tokens
        > 0
    )

    print(
        "case=real_query_rewrite "
        "passed=True "
        f"tokens={result.rewrite.usage.total_tokens} "
        f"latency_ms={result.rewrite.latency_ms}"
    )


# 四、测试用例 2：降级与显式过滤器
def test_fallback_and_explicit_filter() -> None:
    request = RAGRequest(
        question="住宿标准是多少？",
        thread_id="smoke-b02-fallback",
        filters=RetrievalFilters(
            sources=(
                "差旅报销制度_v2.pdf",
            ),
            pages=(1,),
        ),
    )

    runtime = RAGRuntime(
        rewriter=QueryRewriter(
            llm=FailingLLM()
        )
    )

    result = runtime.prepare(request)

    assert (
        result.rewrite.fallback_used
        is True
    )
    assert (
        result.rewrite.inferred_filters.sources
        == ("差旅报销制度_v2.pdf",)
    )
    assert (
        result.rewrite.inferred_filters.pages
        == (1,)
    )
    assert (
        result.trace[1].status
        is TraceStatus.FALLBACK_USED
    )

    print(
        "case=fallback_and_explicit_filter "
        "passed=True"
    )


def main() -> int:
    test_real_query_rewrite()
    test_fallback_and_explicit_filter()

    print("all_passed=True")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())