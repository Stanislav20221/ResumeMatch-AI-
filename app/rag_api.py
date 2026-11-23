"""Separate, opt-in endpoints for ephemeral resume/vacancy RAG with FAISS."""
from __future__ import annotations

import json
import os
from typing import Any, Literal

from fastapi import APIRouter, File, Form, HTTPException, Response, UploadFile
from pydantic import BaseModel, Field

from .documents import DocumentError, MAX_FILE_BYTES, extract_document
from .rag import (RagError, RagUpstreamError, SESSIONS,
                  answer_question, make_index, retrieve)

router = APIRouter(prefix="/api/rag", tags=["RAG / FAISS"])


def _consent(value: bool) -> None:
    if not value:
        raise HTTPException(status_code=422, detail="Требуется отдельное согласие на отправку текста в OpenAI")
    if not os.getenv("OPENAI_API_KEY", "").strip():
        raise HTTPException(status_code=400, detail="OPENAI_API_KEY не задан в .env")


@router.post("/index")
async def index_documents(
    response: Response,
    resume: UploadFile = File(...),
    vacancy_description: str = Form(...),
    vacancy_key_skills: str = Form("[]"),
    cloud_consent: bool = Form(False),
) -> dict[str, Any]:
    response.headers["Cache-Control"] = "no-store"
    _consent(cloud_consent)
    if len(vacancy_description) > 50000 or len(vacancy_key_skills) > 20000:
        raise HTTPException(413, "Слишком большое описание вакансии")
    try:
        skills = json.loads(vacancy_key_skills)
        if not isinstance(skills, list) or len(skills) > 80 or any(not isinstance(s, str) or len(s) > 200 for s in skills):
            raise RagError("Некорректный список навыков вакансии")
        raw = await resume.read(MAX_FILE_BYTES + 1)
        document = extract_document(resume.filename or "", raw)
        return await make_index(document, {"description_text": vacancy_description, "key_skills": skills})
    except json.JSONDecodeError as exc:
        raise HTTPException(422, "Некорректный JSON навыков") from exc
    except (DocumentError, RagError) as exc:
        raise HTTPException(422, str(exc)) from exc
    except RagUpstreamError as exc:
        raise HTTPException(502, str(exc)) from exc
    finally:
        await resume.close()


class RetrievalRequest(BaseModel):
    session_id: str = Field(min_length=16, max_length=128)
    question: str = Field(min_length=3, max_length=700)
    top_k: int = Field(default=6, ge=1, le=8)
    scope: Literal["resume", "vacancy", "both"] = "both"
    cloud_consent: bool = False


@router.post("/search")
async def vector_search(request: RetrievalRequest, response: Response) -> dict[str, Any]:
    response.headers["Cache-Control"] = "no-store"
    _consent(request.cloud_consent)
    try:
        hits = await retrieve(request.session_id, request.question, request.top_k, request.scope)
        return {"matches": hits, "method": "faiss_IndexFlatIP_cosine", "embedding_model": "text-embedding-3-small",
                "disclaimer": "Косинусная близость — не доказательство истинности утверждения"}
    except RagError as exc:
        raise HTTPException(422, str(exc)) from exc
    except RagUpstreamError as exc:
        raise HTTPException(502, str(exc)) from exc


@router.post("/ask")
async def rag_answer(request: RetrievalRequest, response: Response) -> dict[str, Any]:
    response.headers["Cache-Control"] = "no-store"
    _consent(request.cloud_consent)
    try:
        return await answer_question(request.session_id, request.question, request.top_k)
    except RagError as exc:
        raise HTTPException(422, str(exc)) from exc
    except RagUpstreamError as exc:
        raise HTTPException(502, str(exc)) from exc


class DeleteRequest(BaseModel):
    session_id: str = Field(min_length=16, max_length=128)


@router.post("/delete")
async def delete_index(request: DeleteRequest, response: Response) -> dict[str, bool]:
    response.headers["Cache-Control"] = "no-store"
    try:
        SESSIONS.delete(request.session_id)
        return {"deleted": True}
    except RagError as exc:
        raise HTTPException(404, str(exc)) from exc
