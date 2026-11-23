"""v0.9: локальное пакетное сравнение, без вызовов OpenAI и записи файлов."""
from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, Response, UploadFile

from .batch_v09 import BatchError, MAX_CANDIDATES, MAX_PAYLOAD_CHARS, compare_documents
from .documents import DocumentError, MAX_FILE_BYTES, extract_document

router = APIRouter(prefix='/api/batch', tags=['Batch evidence comparison / v0.9'])


def _parse_json(text: str, name: str, *, optional: bool = False) -> Any:
    if optional and not text:
        return None
    if len(text) > MAX_PAYLOAD_CHARS:
        raise HTTPException(413, f'Поле {name} слишком велико')
    try:
        return json.loads(text)
    except (ValueError, TypeError) as exc:
        raise HTTPException(422, f'Некорректный JSON: {name}') from exc


@router.post('/compare')
async def batch_compare(
    response: Response,
    resumes: list[UploadFile] = File(...),
    resume_extractions: str = Form(...),
    vacancy_extraction: str = Form(...),
    vacancy_source: str = Form(...),
    experience_results: str = Form(''),
    candidate_labels: str = Form(''),
) -> dict[str, Any]:
    response.headers['Cache-Control'] = 'no-store'
    response.headers['Pragma'] = 'no-cache'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    if not 1 <= len(resumes) <= MAX_CANDIDATES:
        raise HTTPException(422, f'Укажите от 1 до {MAX_CANDIDATES} резюме')
    try:
        extracts = _parse_json(resume_extractions, 'resume_extractions')
        vacancy = _parse_json(vacancy_source, 'vacancy_source')
        requirements = _parse_json(vacancy_extraction, 'vacancy_extraction')
        experiences = _parse_json(experience_results, 'experience_results', optional=True)
        labels = _parse_json(candidate_labels, 'candidate_labels', optional=True)
        documents = []
        for file in resumes:
            raw = await file.read(MAX_FILE_BYTES + 1)
            documents.append(extract_document(file.filename or '', raw))
        return compare_documents(
            documents, vacancy, requirements, extracts,
            experience_results=experiences, labels=labels,
        )
    except (BatchError, DocumentError) as exc:
        raise HTTPException(422, str(exc)) from exc
    finally:
        for file in resumes:
            await file.close()
