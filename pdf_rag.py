import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

import threading

# 离线模式：只用本地缓存，不去 HuggingFace 检查更新
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
# 如果缓存缺失、需要下载时才用镜像
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

import chromadb
from pypdf import PdfReader
from sentence_transformers import SentenceTransformer

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "uploads"
CHROMA_DIR = BASE_DIR / "chroma_db"
UPLOAD_DIR.mkdir(exist_ok=True)

MODEL_NAME = "BAAI/bge-small-zh-v1.5"
_model = None


def get_model():
    global _model
    if _model is None:
        _model = SentenceTransformer(MODEL_NAME)
    return _model


def embed(texts: list) -> list:
    return get_model().encode(
        texts,
        normalize_embeddings=True,
        show_progress_bar=False,
    ).tolist()


def chunk_text(text: str, size: int = 400, overlap: int = 80) -> list:
    step = max(1, size - overlap)
    chunks = []
    for start in range(0, len(text), step):
        piece = text[start : start + size].strip()
        if piece:
            chunks.append(piece)
    return chunks


def load_pdf_pages(pdf_path: Path) -> list:
    reader = PdfReader(str(pdf_path))
    pages = []
    for page_no, page in enumerate(reader.pages, start=1):
        text = (page.extract_text() or "").strip()
        if text:
            pages.append((page_no, text))
    return pages

_client = None
_collection = None
_collection_lock = threading.Lock()


def get_collection():
    global _client, _collection

    if _collection is None:
        with _collection_lock:
            if _collection is None:
                _client = chromadb.PersistentClient(path=str(CHROMA_DIR))
                _collection = _client.get_or_create_collection(
                    name="docs",
                    metadata={"hnsw:space": "cosine"},
                )
    return _collection


def index_pdf(pdf_path, size: int = 400, overlap: int = 80) -> int:
    pdf_path = Path(pdf_path)
    collection = get_collection()

    ids, docs, metas = [], [], []
    for page_no, page_text in load_pdf_pages(pdf_path):
        for chunk_index, chunk in enumerate(chunk_text(page_text, size, overlap)):
            ids.append(f"{pdf_path.name}#p{page_no}#c{chunk_index}")
            docs.append(chunk)
            metas.append({"source": pdf_path.name, "page": page_no})

    if ids:
        collection.upsert(
            ids=ids,
            documents=docs,
            metadatas=metas,
            embeddings=embed(docs),
        )
    return len(ids)


def search_knowledge(query: str, top_k: int = 4, threshold: float = 0.5) -> list:
    collection = get_collection()
    results = collection.query(
        query_embeddings=embed([query]),
        n_results=top_k,
        include=["documents", "metadatas", "distances"],
    )

    hits = []
    for doc, meta, distance in zip(
        results["documents"][0],
        results["metadatas"][0],
        results["distances"][0],
    ):
        d = round(float(distance), 4)
        if threshold is None or d < threshold:
            hits.append(
                {
                    "text": doc,
                    "source": meta["source"],
                    "page": meta["page"],
                    "distance": d,
                }
            )
    return hits