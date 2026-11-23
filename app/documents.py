"""In-memory text extraction; each block is retained for verifiable source quotes."""
from __future__ import annotations

import io
import os
from pathlib import Path
from typing import Any

import fitz
from docx import Document

from .skills import find_skills

MAX_FILE_BYTES = 6 * 1024 * 1024
MAX_PAGES = 35


class DocumentError(ValueError):
    pass


def _block(text: str, page: int | None = None) -> dict[str, Any]:
    return {"source_text": text.strip(), "page": page}


def _ocr_pdf_page(page: fitz.Page) -> str:
    try:
        import pytesseract
        from PIL import Image

        pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
        img = Image.open(io.BytesIO(pix.tobytes("png")))
        return pytesseract.image_to_string(img, lang=os.getenv("OCR_LANG", "rus+eng"))
    except Exception as exc:
        raise DocumentError(
            "OCR не выполнен. Проверьте установку Tesseract и языков rus+eng: " + str(exc)
        ) from exc


def extract_document(filename: str, data: bytes) -> dict[str, Any]:
    ext = Path(filename).suffix.lower()
    if ext not in {".pdf", ".docx", ".txt"}:
        raise DocumentError("Допустимые форматы: PDF, DOCX, TXT")
    if not data:
        raise DocumentError("Файл пустой")
    if len(data) > MAX_FILE_BYTES:
        raise DocumentError("Максимальный размер файла — 6 МБ")

    blocks: list[dict[str, Any]] = []
    if ext == ".pdf":
        try:
            pdf = fitz.open(stream=data, filetype="pdf")
            with pdf:
                if pdf.page_count > MAX_PAGES:
                    raise DocumentError("Максимум 35 страниц PDF")
                for index, page in enumerate(pdf, start=1):
                    text = page.get_text("text", sort=True)
                    if not text.strip() and os.getenv("ENABLE_OCR") == "1":
                        text = _ocr_pdf_page(page)
                    for line in text.splitlines():
                        if line.strip():
                            blocks.append(_block(line, index))
        except DocumentError:
            raise
        except Exception as exc:
            raise DocumentError("Не удалось прочитать PDF: " + str(exc)) from exc
    elif ext == ".docx":
        try:
            document = Document(io.BytesIO(data))
            # Paragraph order relative to tables may differ; all evidence quotes are exact.
            for paragraph in document.paragraphs:
                if paragraph.text.strip():
                    blocks.append(_block(paragraph.text))
            for table in document.tables:
                for row in table.rows:
                    for cell in row.cells:
                        if cell.text.strip():
                            blocks.append(_block(cell.text))
        except Exception as exc:
            raise DocumentError("Не удалось прочитать DOCX: " + str(exc)) from exc
    else:
        try:
            text = data.decode("utf-8-sig")
        except UnicodeError as exc:
            raise DocumentError("TXT должен быть в UTF-8") from exc
        blocks = [_block(line) for line in text.splitlines() if line.strip()]
    if not blocks:
        raise DocumentError("В документе не найден текст. Для скана PDF включите ENABLE_OCR=1")
    return {"filename": Path(filename).name, "format": ext.lstrip("."), "blocks": blocks}


def build_resume_json(document: dict[str, Any]) -> dict[str, Any]:
    """Explicitly extracted skills only, with exact evidence from source lines."""
    skills: dict[str, dict[str, Any]] = {}
    for block in document["blocks"]:
        for skill in find_skills(block["source_text"]):
            if skill.name not in skills:
                skills[skill.name] = {"name": skill.name, "matched_text": skill.matched_text,
                                      "source_text": block["source_text"], "page": block["page"]}
    return {
        "filename": document["filename"], "format": document["format"],
        "text_length": sum(len(b["source_text"]) for b in document["blocks"]),
        "skills": sorted(skills.values(), key=lambda item: item["name"].casefold()),
        "source_blocks": document["blocks"],
        "extraction_method": "local_rules_and_keyword_aliases",
        "notice": "Навыки определяются только по явным упоминаниям; текст не отправляется в LLM.",
    }
