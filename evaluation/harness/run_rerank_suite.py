import argparse
import subprocess
import sys
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="运行 rerank ablation suite"
    )
    parser.add_argument(
        "--report-dir",
        type=Path,
        default=Path(__file__).parent
        / "reports",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    evaluation_dir = (
        Path(__file__).resolve().parents[1]
    )

    rerank_runner = (
        evaluation_dir
        / "S12_3_rerank_hybrid.py"
    )
    compare_runner = (
        evaluation_dir
        / "S12_5_compare_rerank_results.py"
    )

    rerank_report = (
        args.report_dir
        / "rerank_hybrid.json"
    )
    comparison_report = (
        args.report_dir
        / "rerank_comparison.json"
    )

    print("=" * 70)
    print("RUN RERANK ABLATION")
    print("=" * 70)

    subprocess.run(
        [
            sys.executable,
            str(rerank_runner),
            "--output",
            str(rerank_report),
        ],
        check=True,
    )

    subprocess.run(
        [
            sys.executable,
            str(compare_runner),
            "--report",
            str(rerank_report),
            "--output",
            str(comparison_report),
        ],
        check=True,
    )

    print(
        f"rerank_report={rerank_report.resolve()}"
    )
    print(
        "comparison_report="
        f"{comparison_report.resolve()}"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())