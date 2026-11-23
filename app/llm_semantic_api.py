"""Явно запускаемый платный LLM-этап; не подменяет локальный /match."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .llm_matching import MatchError
from .llm_semantic import SemanticError, SemanticUpstreamError, semantic_match

router = APIRouter(prefix="/api/llm", tags=["LLM"])


class SemanticMatchRequest(BaseModel):
    resume: dict[str, Any]
    vacancy: dict[str, Any]
    cloud_consent: bool = False


@router.post("/semantic-match")
async def run_semantic_match(request: SemanticMatchRequest) -> dict[str, Any]:
    if not request.cloud_consent:
        raise HTTPException(422, "Нужно отдельное согласие на отправку цитат в OpenAI")
    try:
        return await semantic_match(request.resume, request.vacancy)
    except (MatchError, SemanticError) as exc:
        raise HTTPException(422, str(exc)) from exc
    except SemanticUpstreamError as exc:
        raise HTTPException(502, str(exc)) from exc
