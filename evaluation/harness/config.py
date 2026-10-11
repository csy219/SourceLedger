# 这段代码是 **S14 评测 Harness 的配置核心类**，是整个「配置驱动」架构的基石。它负责 JSON 配置文件的加载、路径自动解析、合法性校验，最终输出**不可变的标准化配置对象**，供后续 runner、metrics、reports 所有模块统一使用。
# 用 `@dataclass(frozen=True)` 实现冻结配置，核心目的是保证运行过程中配置不会被意外篡改，确保实验可复现、结果可追溯。
import json
from pathlib import Path
from typing import Any

# - `dataclass`：数据类装饰器，自动生成初始化、打印、等值判断等样板代码，非常适合配置类
from dataclasses import dataclass

# 类定义与冻结特性
# - `@dataclass`：自动生成 `__init__`、`__repr__`、`__eq__` 等方法，无需手写样板代码
# - `frozen=True`：**实例创建后完全不可修改**
#   - 核心价值：杜绝运行时意外篡改配置，保证实验结果可复现
#   - 避免多 runner 并行场景下，配置被改动导致结果不一致
@dataclass(frozen=True)
class HarnessConfig:
    name:str
    eval_set:Path
    corpus:Path
    db:Path
    collection:str
    candidate_k:int
    metric_k:int
    retrieval_budget:int
    chunk_modes:tuple[str,...]
    retrieval_modes:tuple[str,...]
    use_rerank:bool
    use_context_packing:bool
    distance_threshold: float
    chunk_size: int
    overlap: int
    semantic_threshold: float
    rrf_k: int

    ### 4. `from_json` 类方法：从文件加载配置
    # 这是配置类的标准入口，负责文件读取、路径解析、默认值兜底、实例化与校验。
    @classmethod
    def from_json(
        cls,
        config_path: Path,
    ) -> "HarnessConfig":
        payload: dict[str, Any] = json.loads(
            config_path.read_text(encoding="utf-8")
        )
        base_dir = config_path.resolve().parent

        def resolve_path(value: str) -> Path:
            path = Path(value)
            if not path.is_absolute():
                path = base_dir / path
            return path.resolve()

        config = cls(
            name=str(payload.get("name", "core")),
            eval_set=resolve_path(
                str(payload["eval_set"])
            ),
            corpus=resolve_path(
                str(payload["corpus"])
            ),
            db=resolve_path(
                str(payload["db"])
            ),
            collection=str(
                payload.get(
                    "collection",
                    "semantic_chunk_baseline",
                )
            ),
            candidate_k=int(
                payload.get("candidate_k", 20)
            ),
            metric_k=int(
                payload.get("metric_k", 4)
            ),
            retrieval_budget=int(
                payload.get(
                    "retrieval_budget",
                    1800,
                )
            ),
            chunk_modes=tuple(
                payload.get(
                    "chunk_modes",
                    ["fixed"],
                )
            ),
            retrieval_modes=tuple(
                payload.get(
                    "retrieval_modes",
                    ["vector"],
                )
            ),
            use_rerank=bool(
                payload.get("use_rerank", False)
            ),
            use_context_packing=bool(
                payload.get(
                    "use_context_packing",
                    False,
                )
            ),
            distance_threshold=float(
                payload.get("distance_threshold", 0.5)
            ),
            chunk_size=int(
                payload.get("chunk_size", 400)
            ),
            overlap=int(
                payload.get("overlap", 80)
            ),
            semantic_threshold=float(
                payload.get("semantic_threshold", 0.72)
            ),
            rrf_k=int(
                payload.get("rrf_k", 60)
            ),
        )

        config.validate()
        return config

    def validate(self) -> None:
        if not self.eval_set.exists():
            raise FileNotFoundError(
                f"eval_set 不存在: {self.eval_set}"
            )

        if not self.corpus.exists():
            raise FileNotFoundError(
                f"corpus 不存在: {self.corpus}"
            )

        if self.candidate_k <= 0:
            raise ValueError(
                "candidate_k 必须大于 0"
            )

        if self.metric_k <= 0:
            raise ValueError(
                "metric_k 必须大于 0"
            )

        if self.retrieval_budget <= 0:
            raise ValueError(
                "retrieval_budget 必须大于 0"
            )