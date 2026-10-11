import os
import subprocess
import sys
import tempfile
from pathlib import Path


def main() -> int:
    project_root = (
        Path(__file__).resolve().parents[2]
    )
    artifact = (
        Path(tempfile.gettempdir())
        / "agent_runtime_s16_6.json"
    )

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONDONTWRITEBYTECODE"] = "1"

    print("=" * 70)
    print("PROCESS 1: WRITE CHECKPOINT")
    print("=" * 70)
    subprocess.run(
        [
            sys.executable,
            "-m",
            "runtime.db.S16_6_recovery_writer",
            "--artifact",
            str(artifact),
        ],
        cwd=project_root,
        env=env,
        check=True,
    )

    print("=" * 70)
    print("PROCESS 2: RECOVER CHECKPOINT")
    print("=" * 70)
    subprocess.run(
        [
            sys.executable,
            "-m",
            "runtime.db.S16_6_recovery_reader",
            "--artifact",
            str(artifact),
        ],
        cwd=project_root,
        env=env,
        check=True,
    )

    print("=" * 70)
    print("CROSS-PROCESS RECOVERY COMPLETE")
    print("=" * 70)
    print(f"artifact={artifact}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())