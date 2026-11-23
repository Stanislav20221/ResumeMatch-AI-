"""Бесплатный локальный API сопоставления уже извлечённых JSON-фактов."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .llm_matching import MatchError, match_extractions

router = APIRouter(prefix="/api/llm", tags=["LLM"])


class MatchRequest(BaseModel):
    resume: dict[str, Any]
    vacancy: dict[str, Any]


@router.post("/match")
async def match_llm(request: MatchRequest) -> dict[str, Any]:
    # Без OpenAI и hh.ru: только детерминированная обработка JSON.
    try:
        return match_extractions(request.resume, request.vacancy)
    except MatchError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
