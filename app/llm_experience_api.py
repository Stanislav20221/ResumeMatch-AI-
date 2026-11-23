"""v0.5 — явный платный запрос к OpenAI по подтверждённому согласию."""
from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from .documents import DocumentError, MAX_FILE_BYTES, extract_document
from .llm_experience import ExperienceError, ExperienceUpstreamError, analyze_experience

router = APIRouter(prefix="/api/llm", tags=["LLM"])


@router.post("/experience-match")
async def experience_match(
    resume: UploadFile = File(...),
    vacancy_extraction: str = Form(...),
    vacancy_source: str = Form(...),
    cloud_consent: bool = Form(False),
) -> dict[str, Any]:
    if not cloud_consent:
        raise HTTPException(422, "Требуется согласие на передачу резюме в OpenAI")
    if len(vacancy_extraction) > 95000 or len(vacancy_source) > 95000:
        raise HTTPException(413, "Данные вакансии слишком велики")
    try:
        raw = await resume.read(MAX_FILE_BYTES + 1)
        document = extract_document(resume.filename or "", raw)
        try:
            extraction = json.loads(vacancy_extraction)
            source = json.loads(vacancy_source)
        except json.JSONDecodeError as exc:
            raise HTTPException(422, "Невалидный JSON вакансии") from exc
        if not isinstance(extraction, dict) or not isinstance(source, dict):
            raise HTTPException(422, "Данные вакансии должны быть JSON-объектами")
        return await analyze_experience(document, extraction, source)
    except DocumentError as exc:
        raise HTTPException(400, str(exc)) from exc
    except ExperienceError as exc:
        raise HTTPException(422, str(exc)) from exc
    except ExperienceUpstreamError as exc:
        raise HTTPException(502, str(exc)) from exc
    finally:
        await resume.close()
