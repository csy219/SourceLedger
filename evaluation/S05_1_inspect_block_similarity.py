import argparse
import math
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from chunking import chunk_structure_aware  # noqa: E402
from pdf_rag import embed, load_pdf_pages  # noqa: E402


TARGETS = {
    "AI应用开发知识手册.pdf": [2, 3, 9],
    "Agent平台需求说明.pdf": [2],
}

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="检查结构块之间的语义相似度"
    )
    parser.add_argument(
        "--corpus",
        type=Path,
        default=Path(__file__).parent / "corpus",
    )
    return parser.parse_args()


# 手写**余弦相似度**计算函数
def cosine_similarity(
    vector_a: list[float],
    vector_b: list[float],
) -> float:
    dot_product = sum(
        value_a * value_b
        for value_a, value_b in zip(vector_a, vector_b)
    )
    length_a = math.sqrt(
        sum(value * value for value in vector_a)
    )
    length_b = math.sqrt(
        sum(value * value for value in vector_b)
    )

    if length_a == 0 or length_b == 0:
        return 0.0

    return dot_product / (length_a * length_b)

def print_page_similarity(
        source:str,
        page_number:int,
        page_text:str
)->None:
    chunks=chunk_structure_aware(
        page_text=page_text,
        source=source,
        page_number=page_number,
        max_size=400,
        overlap=80,
    )

    vectors=embed([chunk["text"] for chunk in chunks])


    print("\n" + "=" * 80)
    print(f"{source} | 第 {page_number} 页")
    print("=" * 80)

    for index, chunk in enumerate(chunks):
        metadata: dict[str, Any] = chunk["metadata"]
        preview = chunk["text"].replace("\n", " / ")[:100]

        print(
            f"[{index}] "
            f"type={metadata['block_type']} "
            f"length={len(chunk['text'])} "
            f"| {preview}"
        )

    print("\n相邻块相似度：")

    for index in range(len(chunks) - 1):
        similarity = cosine_similarity(
            vectors[index],
            vectors[index + 1],
        )
        print(
            f"{index} -> {index + 1}: "
            f"{similarity:.4f}"
        )

def main() -> int:
    args = parse_args()
    corpus_dir = args.corpus

    for source, target_pages in TARGETS.items():
        pdf_path = corpus_dir / source
        page_map = {
            page_number: page_text
            for page_number, page_text in load_pdf_pages(pdf_path)
        }

        for page_number in target_pages:
            print_page_similarity(
                source=source,
                page_number=page_number,
                page_text=page_map[page_number],
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())