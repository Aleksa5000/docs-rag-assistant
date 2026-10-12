"""Upload validation and text extraction."""
import io
import re
import uuid
from pathlib import Path

from pypdf import PdfReader

from .chunking import chunk_text

ALLOWED = {".pdf", ".md", ".txt"}


class UploadError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


def safe_filename(name: str) -> str:
    """Strip any directory part (both separators) and unsafe characters."""
    base = re.split(r"[\\/]", name or "")[-1]
    base = re.sub(r"[^A-Za-z0-9._ -]", "_", base).strip(" .")
    if len(base) > 120:  # shorten the stem, never the extension
        suffix = Path(base).suffix[:10]
        base = base[: 120 - len(suffix)] + suffix
    return base or "upload"


def validate(filename: str, data: bytes, max_bytes: int) -> str:
    name = safe_filename(filename)
    ext = Path(name).suffix.lower()
    if ext not in ALLOWED:
        raise UploadError(415, f"Unsupported file type '{ext or 'none'}'. Allowed: .pdf, .md, .txt")
    if not data:
        raise UploadError(400, "File is empty")
    if len(data) > max_bytes:
        raise UploadError(413, f"File exceeds the {max_bytes / (1024 * 1024):g} MB limit")
    if ext == ".pdf" and not data.startswith(b"%PDF"):
        raise UploadError(400, "File is not a valid PDF")
    return name


def extract_pages(name: str, data: bytes) -> list[tuple[int | None, str]]:
    """Returns [(page_or_None, text)]."""
    if name.lower().endswith(".pdf"):
        try:
            reader = PdfReader(io.BytesIO(data))
            return [(i, p.extract_text() or "") for i, p in enumerate(reader.pages, start=1)]
        except Exception as exc:  # pypdf raises many types on corrupt input
            raise UploadError(400, "Could not read the PDF") from exc
    return [(None, data.decode("utf-8", errors="replace"))]


def build_chunks(name: str, data: bytes) -> list[tuple[int | None, str]]:
    chunks = [(page, c) for page, text in extract_pages(name, data) for c in chunk_text(text)]
    if not chunks:
        raise UploadError(422, "No extractable text found (scanned PDFs need OCR)")
    return chunks


def store_file(directory: str, name: str, data: bytes) -> str:
    Path(directory).mkdir(parents=True, exist_ok=True)
    path = Path(directory) / f"{uuid.uuid4().hex[:8]}_{name}"
    path.write_bytes(data)
    return str(path)
