import argparse
import json
import subprocess
import sys
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="运行完整 Harness suite"
    )
    parser.add_argument(
        "--report-dir",
        type=Path,
        default=Path(__file__).parent
        / "reports",
    )
    return parser.parse_args()


def run_command(
    script: Path,
    args: list[str],
) -> None:
    command = [
        sys.executable,
        str(script),
        *args,
    ]
    subprocess.run(
        command,
        check=True,
    )


def main() -> int:
    args = parse_args()
    harness_dir = Path(__file__).parent

    chunk_suite = (
        harness_dir / "run_chunk_suite.py"
    )
    core_suite = (
        harness_dir / "run_suite.py"
    )
    rerank_suite = (
        harness_dir / "run_rerank_suite.py"
    )
    compare_reports = (
        harness_dir / "compare_reports.py"
    )

    print("=" * 70)
    print("STEP 1/4: CHUNK SUITE")
    print("=" * 70)
    run_command(
        chunk_suite,
        [
            "--report-dir",
            str(args.report_dir),
        ],
    )

    print("=" * 70)
    print("STEP 2/4: CORE RETRIEVAL SUITE")
    print("=" * 70)
    run_command(
        core_suite,
        [
            "--suite",
            "core",
            "--report-dir",
            str(args.report_dir),
        ],
    )

    print("=" * 70)
    print("STEP 3/4: RERANK SUITE")
    print("=" * 70)
    run_command(
        rerank_suite,
        [
            "--report-dir",
            str(args.report_dir),
        ],
    )

    print("=" * 70)
    print("STEP 4/4: COMPARE CORE REPORTS")
    print("=" * 70)
    run_command(
        compare_reports,
        [
            "--report-dir",
            str(args.report_dir),
            "--output",
            str(
                args.report_dir
                / "core_comparison.json"
            ),
        ],
    )

    manifest = {
        "status": "ok",
        "report_dir": str(
            args.report_dir.resolve()
        ),
        "reports": {
            "chunk": [
                "chunk_fixed.json",
                "chunk_structure.json",
                "chunk_semantic.json",
                "chunk_parent_child.json",
            ],
            "retrieval": [
                "vector.json",
                "bm25.json",
                "hybrid.json",
            ],
            "comparison": [
                "core_comparison.json",
                "core_comparison.md",
            ],
            "rerank": [
                "rerank_hybrid.json",
                "rerank_comparison.json",
            ],
        },
    }

    manifest_path = (
        args.report_dir
        / "suite_manifest.json"
    )
    manifest_path.write_text(
        json.dumps(
            manifest,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print("=" * 70)
    print("FULL SUITE COMPLETE")
    print("=" * 70)
    print(f"manifest={manifest_path.resolve()}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
