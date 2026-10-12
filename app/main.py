import json
import logging
import os
import secrets
from collections.abc import Iterator
from pathlib import Path
from typing import Annotated

import anthropic
from fastapi import Depends, FastAPI, File, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import config, ingest, llm, store

log = logging.getLogger("docs-rag")
STATIC = Path(__file__).parent / "static"
MULTIPART_OVERHEAD = 64 * 1024  # boundaries and part headers on top of the file itself


def require_key(x_api_key: str | None = Header(default=None)) -> None:
    expected = config.app_api_key()
    if expected and not secrets.compare_digest((x_api_key or "").encode(), expected.encode()):
        raise HTTPException(401, "Missing or invalid X-API-Key")


class UploadSizeLimit:
    """Reject oversized uploads by Content-Length before Starlette spools the body to disk.
    Bodies without a Content-Length (chunked) are refused, so the check cannot be skipped."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["method"] == "POST" and scope["path"] == "/api/documents":
            headers = dict(scope["headers"])
            length = headers.get(b"content-length", b"")
            limit = config.max_upload_bytes()
            if b"transfer-encoding" in headers or not length.isdigit():
                return await JSONResponse({"detail": "Content-Length required"}, 411)(scope, receive, send)
            if int(length) > limit + MULTIPART_OVERHEAD:
                detail = f"File exceeds the {limit / (1024 * 1024):g} MB limit"
                return await JSONResponse({"detail": detail}, 413)(scope, receive, send)
        await self.app(scope, receive, send)


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)


def sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def number_sources(hits: list[dict]) -> list[dict]:
    return [
        {"n": n, "doc_id": h["doc_id"], "filename": h["filename"], "page": h["page"],
         "chunk": h["idx"], "text": h["text"], "score": round(h["score"], 3)}
        for n, h in enumerate(hits, start=1)
    ]


def chat_events(question: str) -> Iterator[str]:
    sources = number_sources(store.search(question))
    yield sse("sources", {"demo": config.demo_mode(), "sources": sources})
    try:
        for text in llm.generate(question, sources):
            yield sse("token", {"text": text})
    except anthropic.APIError as exc:
        log.exception("Anthropic API error")
        yield sse("error", {"message": f"The language model request failed ({type(exc).__name__})."})
    yield sse("done", {})


def create_app() -> FastAPI:
    if config.app_api_key():
        # The schema and Swagger UI would stay public, so hide them when auth is on.
        app = FastAPI(title="docs-rag-assistant", docs_url=None, redoc_url=None, openapi_url=None)
    else:
        log.warning("APP_API_KEY is not set: anyone who can reach this server can upload, delete and "
                    "query documents. Set it before exposing the app beyond localhost.")
        app = FastAPI(title="docs-rag-assistant")
    app.add_middleware(UploadSizeLimit)
    store.init_db()
    auth = [Depends(require_key)]

    @app.get("/api/health")
    def health():
        return {"status": "ok", "demo_mode": config.demo_mode(), "model": config.model(),
                "auth_required": bool(config.app_api_key())}

    @app.get("/api/documents", dependencies=auth)
    def documents():
        return store.list_documents()

    @app.post("/api/documents", status_code=201, dependencies=auth)
    def upload(file: Annotated[UploadFile, File()]):  # sync, so pypdf parsing runs in the threadpool
        limit = config.max_upload_bytes()
        # UploadSizeLimit bounds the request body; this bounds what is held in memory.
        data = file.file.read(limit + 1)
        try:
            name = ingest.validate(file.filename or "", data, limit)
            chunks = ingest.build_chunks(name, data)
        except ingest.UploadError as exc:
            raise HTTPException(exc.status, exc.message) from exc
        path = ingest.store_file(config.upload_dir(), name, data)
        doc_id = store.add_document(name, path, chunks)
        return {"id": doc_id, "filename": name, "chunks": len(chunks)}

    @app.delete("/api/documents/{doc_id}", status_code=204, dependencies=auth)
    def remove(doc_id: int):
        path = store.delete_document(doc_id)
        if path is None:
            raise HTTPException(404, "Document not found")
        if path and os.path.exists(path):
            os.remove(path)

    @app.post("/api/chat", dependencies=auth)
    def chat(req: ChatRequest):
        return StreamingResponse(
            chat_events(req.question.strip()),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(STATIC / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app


app = create_app()
