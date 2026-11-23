"""Локальная проверка источников и агрегирование результатов v0.7."""
from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, Response, UploadFile

from .documents import DocumentError, MAX_FILE_BYTES, extract_document
from .evidence_matrix import EvidenceMatrixError, build_evidence_matrix

router = APIRouter(prefix='/api/evidence', tags=['Evidence matrix'])


def _json_object(raw: str, *, optional: bool = False) -> dict[str, Any] | None:
    if optional and not raw:
        return None
    if len(raw) > 300_000:
        raise HTTPException(413, 'Слишком большой JSON')
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(422, 'Некорректный JSON для матрицы') from exc
    if not isinstance(data, dict):
        raise HTTPException(422, 'Ожидается JSON-объект')
    return data


@router.post('/matrix')
async def evidence_matrix(
    response: Response,
    resume: UploadFile = File(...),
    resume_extraction: str = Form(...),
    vacancy_extraction: str = Form(...),
    vacancy_source: str = Form(...),
    semantic_result: str = Form(''),
    experience_result: str = Form(''),
    rag_result: str = Form(''),
) -> dict[str, Any]:
    response.headers['Cache-Control'] = 'no-store'
    try:
        data = await resume.read(MAX_FILE_BYTES + 1)
        document = extract_document(resume.filename or '', data)
        return build_evidence_matrix(
            document, _json_object(vacancy_source),
            _json_object(resume_extraction), _json_object(vacancy_extraction),
            semantic_result=_json_object(semantic_result, optional=True),
            experience_result=_json_object(experience_result, optional=True),
            rag_result=_json_object(rag_result, optional=True),
        )
    except (DocumentError, EvidenceMatrixError) as exc:
        raise HTTPException(422, str(exc)) from exc
    finally:
        await resume.close()
