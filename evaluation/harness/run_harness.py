import argparse
from pathlib import Path
import json

from config import HarnessConfig
from dataset import EvalDataset
from runners import(
    RunnerContext,
    create_runner,
)
from metrics import summarize_rows
from reports import write_report

def parse_args()->argparse.Namespace:
    parser=argparse.ArgumentParser(
        description="运行 Agent RAG Harness"
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path(__file__).parent
        / "configs"
        / "core.json"
    )
    parser.add_argument(
        "--runner",
        default="vector",
    )
    parser.add_argument(
        "--case-id",
        default=None
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
    )
    return parser.parse_args()

def main() -> int:
    args = parse_args()
    config = HarnessConfig.from_json(
        args.config
    )
    dataset = EvalDataset.from_json(
        config.eval_set
    )
    cases=list(dataset.cases)
    if args.case_id:
        cases=[
            case
            for case in cases
            if case.id==args.case_id
        ]
        if not cases:
            raise KeyError(
                f"没有找到 case={args.case_id}"
            )
    from S06_2_parent_child_index import (
        build_parents_and_children,
    )
    from S08_3_bm25_index import BM25Index
    from S09_4_hybrid_eval import load_collection

    collection=load_collection(
        db_dir=config.db,
        collection_name=config.collection,
    )
    _,children=build_parents_and_children(
        corpus_dir=config.corpus,
        chunk_size=config.chunk_size,
        overlap=config.overlap,
        semantic_threshold=config.semantic_threshold,
    )
    bm25_index=BM25Index()
    bm25_index.fit(children)

    runner_context=RunnerContext(
        config=config,
        collection=collection,
        bm25_index=bm25_index
    )

    runner=create_runner(
        name=args.runner,
        context=runner_context,
    )
    results=[]
    for case in cases:
        result=runner.run_case(
            case=case,
            candidate_k=config.candidate_k,
            metric_k=config.metric_k,
        )
        results.append(result)
        print(
            f"case={case.id} "
            f"retrieval_ok={result.retrieval_ok} "
            f"ranks={result.ranks} "
            f"tokens={result.context_tokens_est}"
        )
        
    rows=[
        result.to_dict()
        for result in results
    ]
    summary=summarize_rows(
        rows=rows,
        metric_k=config.metric_k,
    )
    if args.output is None:
        output_path=(
            Path(__file__).parent
            / "reports"
            / f"{args.runner}.json"
        )
    else:
        output_path=args.output

    report={
        "config":{
            "name":config.name,
            "runner":args.runner,
            "candidate_k":config.candidate_k,
            "metric_k":config.metric_k,
            "retrieval_budget":config.retrieval_budget,
            "use_context_packing":config.use_context_packing,
        },
        "summary":summary,
        "rows":rows,
    }
    write_report(output_path,report)

    print("===== Harness Summary =====")
    print(f"runner={args.runner}")
    for key, value in summary.items():
        print(f"{key}={value}")
    print(f"report={output_path.resolve()}")


    return 0


if __name__ == "__main__":
    raise SystemExit(main())