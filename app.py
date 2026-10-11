import shutil

from fastapi import FastAPI, File, HTTPException, UploadFile
from pydantic import BaseModel

from agent import ask
from pdf_rag import UPLOAD_DIR, index_pdf

app = FastAPI(title="SourceLedger API")


class AskRequest(BaseModel):
    question: str
    thread_id: str = "default"


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/upload")
async def upload_pdf(file: UploadFile = File(...)):
    filename = (file.filename or "").lower()
    if not filename.endswith(".pdf"):
        raise HTTPException(status_code=400, detail="只支持 PDF 文件")

    path = UPLOAD_DIR / file.filename
    with path.open("wb") as f:
        shutil.copyfileobj(file.file, f)

    chunk_count = index_pdf(path)
    return {"filename": file.filename, "chunks": chunk_count}


@app.post("/ask")
def ask_question(req: AskRequest):
    return ask(req.question, req.thread_id)
