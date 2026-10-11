import argparse
import time
from typing import Any

from sentence_transformers import CrossEncoder

PRIMARY_MODEL = "BAAI/bge-reranker-v2-m3"
FALLBACK_MODEL = "BAAI/bge-reranker-base"


class Reranker:
    def __init__(
        self,
        model_name: str = PRIMARY_MODEL,
        device: str = "cpu",
        max_length: int = 512,
        allow_fallback: bool = True,
    ) -> None:
        self.model_name = model_name
        self.device = device
        self.max_length = max_length
        self.allow_fallback = allow_fallback
        self.model: CrossEncoder | None = None
        self.backend = "noop"
        self.load_error = ""
        self.load_ms = 0.0
        self._load_model()

    #  接收 model_name
    # → 调用 CrossEncoder
    # → 返回模型对象
    def _try_load(
        self,
        model_name:str,
    )->CrossEncoder:
        return CrossEncoder(
            model_name,
            device=self.device,
            max_length=self.max_length
        )

    # 模型加载 + 降级核心
    def _load_model(self)->None:
        started=time.perf_counter()
        candidates=[self.model_name]

        if(
            self.allow_fallback
            and FALLBACK_MODEL not in candidates
        ):
            candidates.append(FALLBACK_MODEL)

        errors=[]

        for model_name in candidates:
            try:
                self.model=self._try_load(model_name)
                self.model_name=model_name
                self.backend="cross_encoder"
                break
            except Exception as exc:
                errors.append(
                    f"{model_name}:"
                    f"{type(exc).__name__}:{exc}"
                )

        self.load_ms=(
            time.perf_counter()-started
        )*1000

        if self.model is None:
            self.backend="noop"
            self.load_error=" | ".join(errors)
    # 核心重排方法
    def rerank(
        self,
        question:str,
        candidates:list[dict[str,Any]],
        top_k:int,
        batch_size:int=8,
    )->list[dict[str,Any]]:
        if not candidates:
            return []
        for rank,candidate in enumerate(candidates,start=1):
            candidate.setdefault("rrf_rank",rank)

        if self.model is None:
            ordered=sorted(
                candidates,
                key=lambda item:(
                    -(item.get("rrf_score" or 0.0)),
                    item["child_id"],
                ),
            )

            for rank,candidate in enumerate(ordered[:top_k],start=1):
                candidate["rerank_rank"]=rank
                candidate["rerank_score"]=candidate.get(
                    "rrf_socre",
                    0.0,
                )
            return ordered[:top_k]

        pairs=[
            (question,candidate.get("text",""))
            for candidate in candidates
        ]

        scores=self.model.predict(
            pairs,
            batch_size=batch_size,
            show_progress_bar=False,
        )

        for candidate,score in zip(candidates,scores):
            candidate["rerank_score"]=float(score)

        ordered=sorted(
            candidates,
            key=lambda item:(
                -(item.get("rerank_score")),
                -(item.get("rrf_score" or 0.0)),
                item["child_id"],
            ),
        )

        for rank,candidate in enumerate(ordered[:top_k],start=1):
            candidate["rerank_rank"]=rank

        return ordered[:top_k]

def parse_args()->argparse.Namespace:
        parser=argparse.ArgumentParser(
            description="测试 Rerank 适配器"
        )
        parser.add_argument(
            "--model",
            default=PRIMARY_MODEL
        )
        parser.add_argument("--device",default="cpu")

        return parser.parse_args()

def main()->int:
    args=parse_args()

    reranker=Reranker(
        model_name=args.model,
        device=args.device,
    )

    candidates = [
        {
            "child_id": "a",
            "text": "RAG 的完整流程包括文档加载、分块、向量化、检索和生成。",
            "rrf_score": 0.03,
        },
        {
            "child_id": "b",
            "text": "API Token 每 90 天轮换一次。",
            "rrf_score": 0.02,
        },
        {
            "child_id": "c",
            "text": "RAG 检索需要设置 top-k 和相似度阈值。",
            "rrf_score": 0.01,
        },
    ]

    result = reranker.rerank(
        question="RAG 的完整流程是什么？",
        candidates=candidates,
        top_k=2,
    )

    print(f"backend={reranker.backend}")
    print(f"model_name={reranker.model_name}")
    print(f"load_ms={reranker.load_ms:.2f}")
    print(f"load_error={reranker.load_error}")


    for item in result:
        print(
            f"rerank_rank={item['rerank_rank']} "
            f"child_id={item['child_id']} "
            f"rerank_score={item['rerank_score']}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())