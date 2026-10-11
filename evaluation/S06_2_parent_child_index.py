import argparse
import json
import sys
from pathlib import Path
from typing import Any

import chromadb

PROJECT_ROOT=Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0,str(PROJECT_ROOT))

from S05_2_semantic_chunking import chunk_semantic
from pdf_rag import embed,load_pdf_pages

COLLECTION_NAME="parent_child_semantic"

def parse_args()->argparse.Namespace:
    parser=argparse.ArgumentParser(
        description="构建 parent store 并索引 semantic child chunks"
    )
    parser.add_argument(
        "--corpus",
        type=Path,
        default=(Path(__file__).parent / "corpus"),
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=(Path(__file__).parent / "parent_child_chroma")
    )
    parser.add_argument(
        "--parent-store",
        type=Path,
        default=(
            Path(__file__).parent
            / "parent_store"
            / "S06_2_parent_store.json"
        ),
    )
    parser.add_argument("--chunk-size", type=int, default=400)
    parser.add_argument("--overlap", type=int, default=80)
    parser.add_argument(
        "--semantic-threshold",
        type=float,
        default=0.72,
    )
    return parser.parse_args()

def build_parent_id(source:str,page_number:int)->str:
    return f"{source}#p{page_number}"

def build_child_id(
        source:str,
        page_number:int,
        chunk_index:int
)->str:
    return f"{source}#p{page_number}#c{chunk_index}"


# 核心函数：构建父子节点
def build_parents_and_children(
        corpus_dir:Path,
        chunk_size:int,
        overlap:int,
        semantic_threshold:float
)->tuple[dict[str,dict[str,Any]],list[dict[str,Any]]]:
    pdf_paths=sorted(corpus_dir.glob("*.pdf"))
    if not pdf_paths:
        raise FileNotFoundError(f"corpus中没有PDF : {corpus_dir}")

    parent_store={}
    children=[]

    for pdf_path in pdf_paths:
        for page_number,page_text in load_pdf_pages(pdf_path):
            parent_id=build_parent_id(
                pdf_path.name,
                page_number
            )

            children_for_page=chunk_semantic(
                page_text=page_text,
                source=pdf_path.name,
                page_number=page_number,
                max_size=chunk_size,
                overlap=overlap,
                similarity_threshold=semantic_threshold
            )

            heading=(
                children_for_page[0]["metadata"].get("heading","")
                if children_for_page
                else ""
            )

            parent_store[parent_id]={
                "parent_id":parent_id,
                "source":pdf_path.name,
                "page":page_number,
                "heading":heading,
                "text":page_text
            }

            for child in children_for_page:
                metadata=dict(child["metadata"])
                chunk_index=metadata["chunk_index"]
                child_id=build_child_id(
                    source=pdf_path.name,
                    page_number=page_number,
                    chunk_index=chunk_index
                )
                metadata["child_id"]=child_id
                metadata["parent_id"]=parent_id

                children.append(
                    {
                        "child_id":child_id,
                        "parent_id":parent_id,
                        "text":child["text"],
                        "metadata":metadata
                    }
                )
    return parent_store,children


# 父库写入函数
def write_parent_store(
        parent_store:dict[str,dict[str,Any]],
        output_path:Path
)->None:
    output_path.parent.mkdir(parents=True,exist_ok=True)
    output_path.write_text(
        json.dumps(parent_store,ensure_ascii=False,indent=2),
        encoding="utf-8"
    )

# 子节点索引函数
def index_children(
        children:list[dict[str,Any]],
        db_dir:Path
)->chromadb.Collection:
    client=chromadb.PersistentClient(path=str(db_dir))

    try:
        client.delete_collection(COLLECTION_NAME)
    except(ValueError,chromadb.errors.NotFoundError):
        pass

    collection=client.create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space":"cosine"}
    )

    ids=[child["child_id"] for child in children]
    documents=[child["text"] for child in children]
    metadatas = [
        {
            "source": child["metadata"]["source"],
            "page": child["metadata"]["page"],
            "heading": child["metadata"].get("heading", ""),
            "block_type": child["metadata"].get(
                "block_type",
                "unknown",
            ),
            "block_index": child["metadata"].get("block_index", -1),
            "chunk_index": child["metadata"].get("chunk_index", -1),
            "semantic_group_size": child["metadata"].get(
                "semantic_group_size",
                1,
            ),
            "block_indices": child["metadata"].get(
                "block_indices",
                "",
            ),
            "parent_id": child["parent_id"],
        }
        for child in children
    ]

    collection.add(
        ids=ids,
        documents=documents,
        metadatas=metadatas,
        embeddings=embed(documents)
    )
    return collection

def main()->int:
    args=parse_args()

    parent_store, children = build_parents_and_children(
        corpus_dir=args.corpus,
        chunk_size=args.chunk_size,
        overlap=args.overlap,
        semantic_threshold=args.semantic_threshold,
    )

    write_parent_store(
        parent_store=parent_store,
        output_path=args.parent_store
    )

    collection=index_children(
        children=children,
        db_dir=args.db
    )
    print("\n===== Parent-child Index =====")
    print(f"parents={len(parent_store)}")
    print(f"children={len(children)}")
    print(f"collection={COLLECTION_NAME}")
    print(f"collection_count={collection.count()}")
    print(f"parent_store={args.parent_store.resolve()}")
    print(f"db={args.db.resolve()}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

            




