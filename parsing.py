"""
Resume document parsing: PDF (PyMuPDF) and DOCX (python-docx).

Shared by the Celery worker and the Streamlit local-fallback mode.
"""

import io
import tempfile
import os

SUPPORTED_EXTENSIONS = (".pdf", ".docx")


def parse_resume(filename: str, payload: bytes) -> str:
    """Extract plain text from a resume given its filename and raw bytes.

    Raises ValueError for unsupported types or unparseable content.
    """
    ext = os.path.splitext(filename or "")[1].lower()

    if ext == ".pdf":
        return _parse_pdf(payload)
    if ext == ".docx":
        return _parse_docx(payload)
    raise ValueError(
        f"Unsupported file type '{ext or 'unknown'}'. "
        f"Supported: {', '.join(SUPPORTED_EXTENSIONS)}"
    )


def _parse_pdf(payload: bytes) -> str:
    try:
        import pymupdf as fitz   # modern module name (PyMuPDF >= 1.24);
    except ImportError:          # pragma: no cover - older builds
        import fitz              # legacy shim (deprecation-warns on 1.28)
    doc = fitz.open(stream=payload, filetype="pdf")
    try:
        return " ".join(page.get_text() for page in doc)
    finally:
        doc.close()


def _parse_docx(payload: bytes) -> str:
    try:
        from docx import Document
    except ImportError as exc:  # pragma: no cover
        raise ValueError(
            "DOCX support requires python-docx to be installed"
        ) from exc

    document = Document(io.BytesIO(payload))
    parts = [p.text for p in document.paragraphs if p.text.strip()]
    # Include table cell text — resumes love tables
    for table in document.tables:
        for row in table.rows:
            for cell in row.cells:
                if cell.text.strip():
                    parts.append(cell.text)
    return "\n".join(parts)