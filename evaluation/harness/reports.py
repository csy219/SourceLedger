import json
from pathlib import Path
from typing import Any

def write_report(
        output_path:Path,
        payload:dict[str,Any],
)->None:
    output_path.parent.mkdir(parents=True,exist_ok=True)
    output_path.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8"
    )