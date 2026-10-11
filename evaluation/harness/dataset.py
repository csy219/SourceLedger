# 这两个类是 **S14 Harness 的「统一评测数据集核心」**，对应你规划的 `dataset.py` 模块。
# 作用：把 JSON 格式的评测题库，转换成**结构化、不可篡改、提前校验过**的 Python 对象，给所有实验配置统一使用。保证所有分块 / 检索 / 重排 / 上下文组合，跑的都是同一套测试题，结果可以横向对比。

# 设计思路和之前的 `HarnessConfig` 完全一致：**JSON 输入 → 结构化对象 → 前置合法性校验 → 冻结不可变**，从根源上避免「数据不一致、结果不可比」的问题。

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

@dataclass(frozen=True)
class EvalCase:
    id:str
    category:str
    question:str
    source_check:str
    expected_sources:tuple[tuple[str,int],...]

    @classmethod
    def from_dict(
        cls,
        payload:dict[str,Any],
    )->"EvalCase":
        return cls(
            id=str(payload["id"]),
            category=str(payload["category"]),
            question=str(payload["question"]),
            source_check=str(payload.get("source_check","any")),
            expected_sources=tuple(
                (
                    str(item["source"]),
                    int(item["page"]),
                )
                for item in payload.get(
                    "expected_sources",
                    [],
                )
            ),
        )

@dataclass(frozen=True)
class EvalDataset:
    path:Path
    schema_version:str
    cases:tuple[EvalCase,...]

    @classmethod
    def from_json(
        cls,
        path:Path,
    )->"EvalDataset":
        payload=json.loads(
            path.read_text(encoding="utf-8")
        )

        cases=tuple(
            EvalCase.from_dict(item)
            for item in payload.get("cases",[])
        )

        if not cases:
            raise ValueError(f"评测集里没有 cases:{path}")

        dataset=cls(
            path=path,
            schema_version=str(
                payload.get("schema_version","")
            ),
            cases=cases,
        )
        dataset.validate()
        return dataset

    def validate(self)->None:
        case_ids=[
            case.id
            for case in self.cases
        ]
        if len(case_ids)!=len(set(case_ids)):
            raise ValueError(
                "评测集存在重复 case id"
            )

        for case in self.cases:
            if not case.id:
                raise ValueError(
                    "存在空 case id"
                )
            if not case.question:
                raise ValueError(
                    f"{case.id}: question 为空"
                )
            if not case.category:
                raise ValueError(
                    f"{case.id}: category 为空"
                )
    def categories(self)->dict[str,Any]:
        result:dict[str,Any]={}

        for case in self.cases:
            result[case.category]=(
                result.get(case.category,0)+1
            )
        return result