import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class SecurityCase:
    id: str
    attack_type: str
    question: str
    injected_text: str
    expected_behavior: str
    forbidden_behavior: tuple[str, ...]
    defense_layer: tuple[str, ...]


def load_security_cases(
    path: Path,
) -> tuple[SecurityCase, ...]:
    document = json.loads(
        path.read_text(encoding="utf-8")
    )

    cases = tuple(
        parse_case(item)
        for item in document.get("cases", [])
    )

    validate_cases(cases)
    return cases


def parse_case(
    payload: dict[str, Any],
) -> SecurityCase:
    return SecurityCase(
        id=str(payload["id"]),
        attack_type=str(
            payload["attack_type"]
        ),
        question=str(payload["question"]),
        injected_text=str(
            payload.get("injected_text", "")
        ),
        expected_behavior=str(
            payload["expected_behavior"]
        ),
        forbidden_behavior=tuple(
            str(item)
            for item in payload.get(
                "forbidden_behavior",
                [],
            )
        ),
        defense_layer=tuple(
            str(item)
            for item in payload.get(
                "defense_layer",
                [],
            )
        ),
    )


def validate_cases(
    cases: tuple[SecurityCase, ...],
) -> None:
    if not cases:
        raise ValueError(
            "security set 没有 cases"
        )

    ids = [case.id for case in cases]

    if len(ids) != len(set(ids)):
        raise ValueError(
            "security cases 存在重复 id"
        )

    for case in cases:
        if not case.question:
            raise ValueError(
                f"{case.id}: question 为空"
            )
        if not case.expected_behavior:
            raise ValueError(
                f"{case.id}: expected_behavior 为空"
            )
        if not case.forbidden_behavior:
            raise ValueError(
                f"{case.id}: forbidden_behavior 为空"
            )
        if not case.defense_layer:
            raise ValueError(
                f"{case.id}: defense_layer 为空"
            )