# 结构分块
# → 向量化每个结构块
# → 比较相邻块相似度
# → 相似且满足约束时合并
# → 重新生成 chunk_index
import math
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from chunking import chunk_structure_aware  # noqa: E402
from pdf_rag import embed, load_pdf_pages  # noqa: E402


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

# **strip_heading**：把 chunk 开头的标题前缀去掉，只保留正文，用于长度统计。
def strip_heading(
        text:str,
        heading:str
)->str:
    prefix=f"{heading}\n"

    if heading and text.startswith(prefix):
        return text[len(prefix):]
    return text

# **can_merge**：合并判断核心函数，满足全部条件才允许合并：
# - 当前块和下一块`heading`完全相同
# - `block_type`相同
# - 不能是`list_item`列表项
# - 向量相似度 ≥ similarity_threshold（默认 0.72）
# - 合并后文本长度 ≤ max_size
def can_merge(
    current_indices:list[int],
    next_index:int,
    base_chunks:list[dict[str,Any]],
    vectors:list[list[float]],
    max_size:int,
    similarity_threshold:float,
)->bool:
    # 从`base_chunks`中取出**当前分组的最后一个分块**。`current_indices[-1]`取列表最后一个元素，也就是当前组最末尾分块的下标。
    # 设计逻辑：采用贪心合并策略，只拿当前组的最后一块和下一块做相似度判断，不需要计算整组的聚合向量。
    current_chunk=base_chunks[current_indices[-1]]
    next_chunk=base_chunks[next_index]

    current_meta=current_chunk["metadata"]
    next_meta=next_chunk["metadata"]

    if current_meta["heading"] != next_meta["heading"]:
        return False
    if current_meta["block_type"] != next_meta["block_type"]:
        return False
    if current_meta["block_type"] == "list_item":
        return False
    similarity=cosine_similarity(
        vectors[current_indices[-1]],
        vectors[next_index]
    )
    if similarity < similarity_threshold:
        return False

    merged_length = sum(
        len(
            strip_heading(
                base_chunks[index]["text"],
                base_chunks[index]["metadata"]["heading"],
            )
        )
        for index in [*current_indices, next_index]
    )
    merged_length += len(current_meta["heading"])

    return merged_length <= max_size

# `build_merged_chunk` 是**语义合并的构建函数**：输入一组基础分块的下标，将它们合并为一个完整的语义分块；自动去除每个分块重复的标题前缀，只保留一个统一标题，同时扩展元数据记录合并信息。输出结构与原始基础分块完全一致（`text` + `metadata`），可直接被下游逻辑使用。
def build_merged_chunk(
    base_chunks:list[dict[str,Any]],
    group_indices:list[int],
)->dict[str,Any]:
    first=base_chunks[group_indices[0]]
    metadata=dict(first["metadata"])
    heading=metadata["heading"]

    bodies = [
        strip_heading(
            base_chunks[index]["text"],
            base_chunks[index]["metadata"]["heading"],
        )
        for index in group_indices
    ]
    body="\n".join(bodies)
    text=f"{heading}\n{body}" if heading else body

    metadata["semantic_group_size"]=len(group_indices)
    metadata["block_indices"]=",".join(
        str(index) for index in group_indices
    )

    return {
        "text":text,
        "metadata":metadata
    }


# `chunk_semantic` 是**语义合并分块的主入口函数**：先通过结构感知分块得到细粒度的基础分块，再按照「同标题、同块类型、非列表项、语义达标、长度不超限」的规则，将相邻符合条件的基础分块贪心合并为更大的语义分块，最终返回合并后的分块列表。

def chunk_semantic(
        page_text:str,
        source:str,
        page_number:int,
        max_size:int=400,
        overlap:int=80,
        similarity_threshold:float=0.72
)->list[dict[str,Any]]:
    base_chunks=chunk_structure_aware(
        page_text=page_text,
        source=source,
        page_number=page_number,
        max_size=max_size,
        overlap=overlap,
    )

    if len(base_chunks) <=1 :
        return base_chunks

    vectors=embed([chunk["text"] for chunk in base_chunks])

    groups: list[list[int]]=[]
    current_indices=[0]
    for next_index in range(1,len(base_chunks)):
        if can_merge(
            current_indices=current_indices,
            next_index=next_index,
            base_chunks=base_chunks,
            vectors=vectors,
            max_size=max_size,
            similarity_threshold=similarity_threshold,
        ):
            current_indices.append(next_index)
        else:
            groups.append(current_indices)
            current_indices=[next_index]
    groups.append(current_indices)


    merged_chunks=[
        build_merged_chunk(
            base_chunks=base_chunks,
            group_indices=group_indices
        )
        for group_indices in groups
    ]

    for chunk_index,chunk in enumerate(merged_chunks):
        chunk["metadata"]["chunk_index"]=chunk_index

    return merged_chunks

# `main` 是整个语义分块脚本的**主入口函数**：硬编码语料目录与待检测的 PDF 页码，逐个读取目标 PDF 的指定页面，调用`chunk_semantic`执行结构感知 + 语义合并分块，最终打印每页的分块数量与每个分块的元数据，用于调试、验证语义合并效果。
def main()->int:
    corpus_dir=Path(__file__).resolve().parent / "corpus"
    targets={
        "AI应用开发知识手册.pdf": [2, 3, 9],
        "Agent平台需求说明.pdf": [2],
    }

    for source, target_pages in targets.items():
        page_map = {
            page_number: page_text
            for page_number, page_text in load_pdf_pages(
                corpus_dir / source
            )
        }
        for page_number in target_pages:
            chunks=chunk_semantic(
                page_text=page_map[page_number],
                source=source,
                page_number=page_number
            )

            print(
                f"{source}第 {page_number}页： "
                f"{len(chunks)} chunks"
            )
            for chunk in chunks:
                metadata = chunk["metadata"]
                print(
                    f"  chunk_index={metadata['chunk_index']} "
                    f"type={metadata['block_type']} "
                    f"group_size={metadata['semantic_group_size']} "
                    f"blocks={metadata['block_indices']}"
                )
    return 0
if __name__ == "__main__":
    raise SystemExit(main())
