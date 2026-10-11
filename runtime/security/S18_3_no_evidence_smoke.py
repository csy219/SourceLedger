# 这是**S18-3 无证据策略的正式测试脚本**，从统一的安全测试用例集加载测试问题，分别验证「检索结果为空」「证据质量不足」「证据充足」三个核心场景的评估逻辑和对应话术，
# 最终输出结构化测试结果，并通过程序退出码标识测试是否通过，可集成到自动化测试流水线。

import json
import sys
from pathlib import Path

PROJECT_ROOT = (
    Path(__file__).resolve().parents[2]
)
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from runtime.security.S18_1_security_fixture_loader import (
    load_security_cases,
)
from runtime.security.S18_3_no_evidence import (
    NoEvidencePolicy,
    build_abstention_answer,
)


def main()->int:
    set_path=(
        PROJECT_ROOT
        / "evaluation"
        / "security"
        / "S18_security_set.json"
    )

    cases={
        case.id:case
        for case in load_security_cases(set_path)
    }

    question=cases["SEC03"].question

    # 场景 1：检索结果为空测试
    empty_policy = NoEvidencePolicy(
        min_evidence_count=1
    )
    empty_assessment = empty_policy.assess(
        question=question,
        retrieval_context=[],
    )
    empty_answer = build_abstention_answer(
        empty_assessment,
        question,
    )

    # 场景 2：低质量证据测试
    low_score_policy = NoEvidencePolicy(
        min_evidence_count=1,
        min_score=0.8,
    )
    low_score_assessment = (
        low_score_policy.assess(
            question=question,
            retrieval_context=[
                {
                    "source": "unknown.pdf",
                    "page": 1,
                    "text": "不相关内容",
                    "similarity": 0.2,
                }
            ],
        )
    )
    low_score_answer = build_abstention_answer(
        low_score_assessment,
        question,
    )

    # 场景 3：充足证据测试
    enough_policy = NoEvidencePolicy(
        min_evidence_count=1,
        min_score=0.5,
    )
    enough_assessment = enough_policy.assess(
        question=question,
        retrieval_context=[
            {
                "source": "employee_handbook.pdf",
                "page": 10,
                "text": "员工年假制度",
                "similarity": 0.9,
            }
        ],
    )
    enough_answer = build_abstention_answer(
        enough_assessment,
        question,
    )
    # 测试通过条件判断
    passed = (
        not empty_assessment.has_evidence
        and not low_score_assessment.has_evidence
        and enough_assessment.has_evidence
        and "没有足够信息" in empty_answer
        and "没有足够信息" in low_score_answer
        and "可以继续生成" in enough_answer
    )


    output = {
        "question": question,
        "empty": {
            "assessment": (
                empty_assessment.__dict__
            ),
            "answer": empty_answer,
        },
        "low_score": {
            "assessment": (
                low_score_assessment.__dict__
            ),
            "answer": low_score_answer,
        },
        "has_evidence": {
            "assessment": (
                enough_assessment.__dict__
            ),
            "answer": enough_answer,
        },
        "passed": passed,
    }

    print(
        json.dumps(
            output,
            ensure_ascii=False,
            indent=2,
        )
    )

    if not passed:
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())