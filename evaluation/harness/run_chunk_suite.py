import argparse
import json
import subprocess
import sys
from pathlib import Path


CHUNK_MODES = [
    "fixed",
    "structure",
    "semantic",
    "parent_child",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="运行 chunk mode 消融套件"
    )
    parser.add_argument(
        "--report-dir",
        type=Path,
        default=Path(__file__).parent
        / "reports",
    )
    return parser.parse_args()


def load_summary(
    path: Path,
) -> dict:
    payload = json.loads(
        path.read_text(encoding="utf-8")
    )
    return payload.get("summary", {})


def main() -> int:
    args = parse_args()

    evaluation_dir = (
        Path(__file__).resolve().parents[1]
    )
    chunk_runner = (
        evaluation_dir
        / "run_fixed_chunk_baseline.py"
    )

    summaries: dict[str, dict] = {}

    for chunk_mode in CHUNK_MODES:
        output_path = (
            args.report_dir
            / f"chunk_{chunk_mode}.json"
        )

        command = [
            sys.executable,
            str(chunk_runner),
            "--chunk-mode",
            chunk_mode,
            "--output",
            str(output_path),
        ]

        print("\n" + "=" * 70)
        print(f"CHUNK_MODE={chunk_mode}")
        print("=" * 70)

        subprocess.run(
            command,
            check=True,
        )

        summaries[chunk_mode] = load_summary(
            output_path
        )

    print("\n" + "=" * 70)
    print("CHUNK SUITE SUMMARY")
    print("=" * 70)

    for chunk_mode, summary in summaries.items():
        print(f"\n[{chunk_mode}]")
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
            "latency_ms_avg="
            f"{summary.get('latency_ms_avg')}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())