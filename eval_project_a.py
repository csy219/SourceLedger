import json
from pathlib import Path

from agent import ask

REPORT_FILE = Path("eval_report.json")

CASES = [
    {"question": "RAG 的完整流程是什么？", "expect_keyword": "分块", "expect_page": 2},
    {"question": "chunk_size 和 chunk_overlap 有什么区别？", "expect_keyword": "overlap", "expect_page": 2},
    {"question": "BGE 和 TF-IDF 有什么区别？", "expect_keyword": "BGE", "expect_page": 3},
    {"question": "提示注入怎么防御？", "expect_keyword": "权限", "expect_page": 7},
    {"question": "LangGraph 的 Checkpointer 有什么用？", "expect_keyword": "thread_id", "expect_page": 5},
    {"question": "MCP 有哪三个角色？", "expect_keyword": "Server", "expect_page": 10},
    {"question": "缓存能优化什么？", "expect_keyword": "重复", "expect_page": 8},
    {"question": "公司年假有多少天？", "expect_keyword": None, "expect_page": None},
]

REFUSAL_WORDS = ["不知道", "资料不足", "没有检索到", "无法", "未检索"]


def evaluate_case(index: int, case: dict) -> dict:
    result = ask(case["question"], thread_id=f"eval-{index}")
    answer = result["answer"]
    citations = result["citations"]
    pages = [c["page"] for c in citations]

    if case["expect_page"] is None:
        answer_ok = any(word in answer for word in REFUSAL_WORDS)
        retrieval_ok = len(citations) == 0
    else:
        answer_ok = case["expect_keyword"] in answer
        retrieval_ok = case["expect_page"] in pages

    passed = answer_ok and retrieval_ok

    return {
        "index": index,
        "question": case["question"],
        "answer_ok": answer_ok,
        "retrieval_ok": retrieval_ok,
        "passed": passed,
        "pages": pages,
        "answer_preview": answer[:100],
    }


def main():
    rows = [evaluate_case(i, case) for i, case in enumerate(CASES, 1)]

    total = len(rows)
    passed = sum(1 for r in rows if r["passed"])
    answer_ok = sum(1 for r in rows if r["answer_ok"])
    retrieval_ok = sum(1 for r in rows if r["retrieval_ok"])

    report = {
        "total": total,
        "passed": passed,
        "pass_rate": round(passed / total, 3),
        "answer_accuracy": round(answer_ok / total, 3),
        "retrieval_accuracy": round(retrieval_ok / total, 3),
        "rows": rows,
    }

    REPORT_FILE.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("===== 项目 A 评测 =====")
    for r in rows:
        print(
            f"[{'PASS' if r['passed'] else 'FAIL'}] "
            f"检索={r['retrieval_ok']} 回答={r['answer_ok']} | {r['question']}"
        )

    print(f"\n总数:{total}")
    print(f"通过率：{report['pass_rate']:.0%}")
    print(f"检索命中率：{report['retrieval_accuracy']:.0%}")
    print(f"回答正确率：{report['answer_accuracy']:.0%}")
    print(f"报告：{REPORT_FILE.resolve()}")


if __name__ == "__main__":
    main()