import argparse
import json
# - `subprocess`：核心依赖，用来启动独立子进程执行 `run_harness.py`，实现运行环境隔离
# - 其余为通用工具和之前实现的配置类
import subprocess
import sys
from pathlib import Path

from config import HarnessConfig

CORE_SUITE = [
    "vector",
    "bm25",
    "hybrid",
]

RUNNER_ALIASES = {
    "vector": "vector",
    "bm25": "bm25",
    "hybrid": "hybrid",
    "rrf_hybrid": "hybrid",
}

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="运行 Harness 配置套件"
    )
    parser.add_argument(
        "--suite",
        default="core",
        choices=["core"],
    )
    parser.add_argument(
    "--config",
    type=Path,
    default=Path(__file__).parent
    / "configs"
    / "core.json",
    )
    parser.add_argument(
        "--report-dir",
        type=Path,
        default=Path(__file__).parent
        / "reports",
    )
    return parser.parse_args()


def load_summary(
    report_path: Path,
) -> dict:
    payload = json.loads(
        report_path.read_text(encoding="utf-8")
    )
    return payload.get("summary", {})


def main() -> int:
    args = parse_args()

    if args.suite!="core":
        raise ValueError(
            f"未知 suite={args.suite}"
        )
    config=HarnessConfig.from_json(
        args.config
    )

    runners=[]
    for item in CORE_SUITE:
        runner=RUNNER_ALIASES.get(
            item,
            item,
        )
        if runner not in runners:
            runners.append(runner)
    run_harness=(
        Path(__file__).parent
        / "run_harness.py"
    )
    summaries={}

    for runner in runners:
        output_path = (
            args.report_dir
            / f"{runner}.json"
        )
        command = [
            sys.executable,
            str(run_harness),
            "--config",
            str(args.config),
            "--runner",
            runner,
            "--output",
            str(output_path),
        ]

        print("\n" + "=" * 70)
        print(f"RUNNER={runner}")
        print("=" * 70)

        subprocess.run(
            command,
            check=True,
        )

        summaries[runner] = load_summary(
            output_path
        )

    print("\n" + "=" * 70)
    print("SUITE SUMMARY")
    print("=" * 70)

    for runner, summary in summaries.items():
        print(f"\n[{runner}]")
        print(
            "retrieval_accuracy="
            f"{summary.get('retrieval_accuracy')}"
        )
        print(
            "hit_at_1="
            f"{summary.get('hit_at_1')}"
        )
        print(
            "hit_at_k="
            f"{summary.get('hit_at_k')}"
        )
        print(
            "recall_at_k="
            f"{summary.get('recall_at_k')}"
        )
        print(
            "mrr="
            f"{summary.get('mrr')}"
        )
        print(
            "ndcg_at_k="
            f"{summary.get('ndcg_at_k')}"
        )
        print(
            "context_tokens_avg="
            f"{summary.get('context_tokens_avg')}"
        )
        print(
            "invalid_citation_count="
            f"{summary.get('invalid_citation_count')}"
        )
        print(
            "failed_cases="
            f"{summary.get('failed_cases')}"
        )

    return 0

if __name__ == "__main__":
    raise SystemExit(main())