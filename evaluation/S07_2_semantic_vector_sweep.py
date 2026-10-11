import argparse
import json
from pathlib import Path
from typing import Any

import chromadb

from run_fixed_chunk_baseline import (
    build_summary,
    evaluate_case
)


# - 功能：把命令行传入的逗号分隔字符串（如 `"4,6,10,20"`）解析成指定类型的数值列表
# - 用途：批量解析多组 candidate_k 和 threshold 参数，实现网格扫描
def parse_number_list(
        raw:str,
        cast:type,
)->list[int] | list[float]:
    return [cast(item.strip()) for item in raw.split(",") if item.strip()]

def parse_args()->argparse.Namespace:
    parser=argparse.ArgumentParser(
        description="扫描 semantic 向量检索的 candidate_k 和 threshold"
    )
    parser.add_argument(
        "--eval-set",
        type=Path,
        default=Path(__file__).parent / "eval_set.json"
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=Path(__file__).parent / "baseline.chroma",
    )
    parser.add_argument(
        "--collection",
        default="semantic_chunk_baseline",
    )
    parser.add_argument(
        "--candidate-ks",
        default="4,6,10,20",
    )
    parser.add_argument(
        "--thresholds",
        default="0.35,0.40,0.45,0.50,0.55",
    )
    parser.add_argument("--metric-k", type=int, default=4)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).parent
        / "reports"
        / "S07_2_semantic_vector_sweep.json",
    )
    return parser.parse_args()


# - 功能：连接 Chroma 数据库，加载指定名称的集合
# - 容错：如果集合不存在，直接抛出明确错误，提示先运行 semantic 模式建库
# - 目的：确保评估前向量库已就绪
def load_collection(
        db_dir:Path,
        collection_name:str,
)->chromadb.Collection:
    client=chromadb.PersistentClient(path=str(db_dir))
    try:
        return client.get_collection(collection_name)
    except (ValueError, chromadb.errors.NotFoundError) as exc:
        raise RuntimeError(
            f"集合不存在: {collection_name}，请先运行 semantic 模式"
        ) from exc
    


# 这是核心评估单元，针对**一组特定的参数组合**执行完整评测：
# 1. 遍历所有测试用例，逐个调用 `evaluate_case` 执行检索并判分
# 2. 调用 `build_summary` 汇总所有用例，计算整体指标（通过率、hit@1、hit@k、召回率、MRR）
# 3. 收集所有检索失败的用例 ID
# 4. 返回：参数配置、汇总指标、失败用例列表
# > 注意：这里 `parent_store={}` 传了空字典，说明这个脚本测的是**纯语义分块检索本身的效果**，不做父页面上下文扩展。

def evaluate_configuration(
        collection:chromadb.Collection,
        cases:list[dict[str,Any]],
        candidate_k:int,
        metric_k:int,
        threshold:float,
)->dict[str,Any]:
    rows=[
        evaluate_case(
            collection=collection,
            case=case,
            candidate_k=candidate_k,
            metric_k=metric_k,
            threshold=threshold,
            parent_store={}
        )
        for case in cases        
    ]

    summary=build_summary(rows,metric_k)
    failed_ids=[
        row["id"] for row in rows if not row["retrieval_ok"]
    ]

    return {
        "config":{
            "candidate_k":candidate_k,
            "metric_k":metric_k,
            "threshold":threshold,
        },
        "summary":summary,
        "failed_ids":failed_ids
    }

def main()->int:
    args=parse_args()

    candidate_ks=parse_number_list(args.candidate_ks,int)
    thresholds=parse_number_list(args.thresholds,float)

    document=json.loads(
        args.eval_set.read_text(encoding="utf-8")
    )

    cases=document.get("cases",[])

    collection=load_collection(args.db,args.collection)

    results=[]

    for candidate_k in candidate_ks:
        for threshold in thresholds:
            result = evaluate_configuration(
                collection=collection,
                cases=cases,
                candidate_k=candidate_k,
                metric_k=args.metric_k,
                threshold=threshold,
            )
            results.append(result)

            summary = result["summary"]
            print(
                f"candidate_k={candidate_k:>2} "
                f"threshold={threshold:.2f} "
                f"passed={summary['retrieval_passed']} "
                f"hit@1={summary['hit_at_1']:.4f} "
                f"hit@4={summary['hit_at_metric_k']:.4f} "
                f"recall@4={summary['recall_at_metric_k']:.4f} "
                f"mrr={summary['mrr']:.4f}"
            )

    report = {
        "collection": args.collection,
        "eval_set": str(args.eval_set.resolve()),
        "db": str(args.db.resolve()),
        "results": results,
    }
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(
        json.dumps(report,ensure_ascii=False,indent=2),
        encoding="utf-8"
    )

    print(f"\nreport: {args.output.resolve()}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
            
    