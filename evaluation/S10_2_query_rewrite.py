import argparse
import json
import os
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI
from pydantic import BaseModel, Field, ValidationError

from S08_2_tokenizer import tokenize

ENV_FILE = Path(__file__).resolve().parents[2] / ".env"

CHINESE_STOP_CHARS = set(
    "的了吗呢哪什么怎如何是否几有和与或"
)

BAD_BIGRAMS = {
    "的完",
    "整流",
    "程有",
    "有哪",
    "哪几",
    "么作",
    "有什",
    "什么",
    "怎么",
    "如何",
    "是否",
}
class RewritePayload(BaseModel):
    semantic: str = Field(min_length=1)
    keywords: list[str] = Field(min_length=1, max_length=12)
    keyword_query: str = Field(min_length=1)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="为评测问题生成语义改写和关键词查询"
    )
    parser.add_argument(
        "--eval-set",
        type=Path,
        default=Path(__file__).parent / "eval_set.json",
    )
    parser.add_argument(
        "--cache",
        type=Path,
        default=Path(__file__).parent
        / "query_rewrite"
        / "S10_2_rewrites.json",
    )
    parser.add_argument("--model", default="deepseek-v4-flash")
    parser.add_argument(
        "--no-llm",
        action="store_true",
        help="强制使用规则回退，不调用模型",
    )
    parser.add_argument(
        "--retry-fallback",
        action="store_true",
    )
    return parser.parse_args()


def load_cache(path: Path) -> dict[str, dict[str, Any]]:
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def save_cache(
    path: Path,
    cache: dict[str, dict[str, Any]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(cache, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def build_fallback_rewrite(question: str) -> dict[str, Any]:
    seen: set[str] = set()
    keywords: list[str] = []

    for token in tokenize(question):
        if token in BAD_BIGRAMS:
            continue

        if (
            len(token) == 2
            and all(
                "\u4e00" <= char <= "\u9fff"
                for char in token
            )
            and any(
                char in CHINESE_STOP_CHARS
                for char in token
            )
        ):
            continue

        useful = (
            len(token) >= 2
            or any(char.isdigit() for char in token)
            or "%" in token
        )
        if not useful or token in seen:
            continue

        seen.add(token)
        keywords.append(token)

        if len(keywords) >= 12:
            break

    if not keywords:
        keywords = [question]

    return {
        "original": question,
        "semantic": question,
        "keywords": keywords,
        "keyword_query": " ".join(keywords),
        "rewrite_status": "fallback",
        "rewrite_latency_ms": 0.0,
    }


def create_client() -> OpenAI | None:
    load_dotenv(ENV_FILE)

    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        return None

    return OpenAI(
        api_key=api_key,
        base_url="https://api.deepseek.com",
    )

def build_prompt(question: str) -> str:
    return (
        "你是检索查询改写器。\n\n"
        "任务：\n"
        "1. 将用户问题改写成一个更适合语义检索的问题；\n"
        "2. 提取 5-12 个检索关键词；\n"
        "3. 生成一个关键词查询；\n"
        "4. 保留 user_id、task_id、tool_name、trace、p95、"
        "百分比和版本日期；\n"
        "5. 不要回答问题，不要增加资料外事实。\n\n"
        "只返回 JSON：\n"
        "{\n"
        '  "semantic": "...",\n'
        '  "keywords": ["...", "..."],\n'
        '  "keyword_query": "..."\n'
        "}\n\n"
        f"用户问题：\n{question}"
    )


def rewrite_query(
    question: str,
    client: OpenAI | None,
    model: str,
) -> dict[str, Any]:
    fallback = build_fallback_rewrite(question)

    if client is None:
        return fallback

    started = time.perf_counter()

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": "只输出合法 JSON，不要输出 Markdown。",
                },
                {
                    "role": "user",
                    "content": build_prompt(question),
                },
            ],
            temperature=0,
            max_tokens=600,
            response_format={"type": "json_object"},
        )
        raw = response.choices[0].message.content or ""
        payload = RewritePayload.model_validate_json(raw)
        latency_ms = (time.perf_counter() - started) * 1000

        return {
            "original": question,
            "semantic": payload.semantic,
            "keywords": payload.keywords,
            "keyword_query": payload.keyword_query,
            "rewrite_status": "llm",
            "rewrite_latency_ms": round(latency_ms, 2),
        }
    except (Exception, ValidationError) as exc:
        fallback["rewrite_error"] = (
            f"{type(exc).__name__}: {exc}"
        )
        return fallback


def main() -> int:
    args = parse_args()
    document = json.loads(
        args.eval_set.read_text(encoding="utf-8")
    )
    questions = [
        case["question"]
        for case in document.get("cases", [])
    ]

    cache = load_cache(args.cache)
    client = None if args.no_llm else create_client()

    for question in questions:
        cached = cache.get(question)

        if cached and not (
            args.retry_fallback
            and cached.get("rewrite_status") == "fallback"
        ):
            continue
        cache[question] = rewrite_query(
            question=question,
            client=client,
            model=args.model,
        )
        save_cache(args.cache, cache)

    llm_count = sum(
        1
        for record in cache.values()
        if record.get("rewrite_status") == "llm"
    )
    fallback_count = sum(
        1
        for record in cache.values()
        if record.get("rewrite_status") == "fallback"
    )

    print(f"questions={len(questions)}")
    print(f"cache_records={len(cache)}")
    print(f"llm_count={llm_count}")
    print(f"fallback_count={fallback_count}")
    print(f"cache={args.cache.resolve()}")

    for question in questions[:3]:
        print(f"\nquestion: {question}")
        print(json.dumps(cache[question], ensure_ascii=False, indent=2))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())