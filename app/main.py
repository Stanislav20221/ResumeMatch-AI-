"""Local-only FastAPI web app. No permanent CV storage or cloud CV forwarding."""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from .llm_api import router as llm_router
from .demo import demo_vacancies
from .documents import DocumentError, MAX_FILE_BYTES, build_resume_json, extract_document
from .matching import rank_matches
from .vacancies import VacancyError, search_hh
from .llm_match_api import router as llm_match_router
from .llm_semantic_api import router as llm_semantic_router
from .llm_experience_api import router as llm_experience_router
app = FastAPI(title="ResumeMatch AI", version="0.1.0", docs_url="/docs")
app.include_router(llm_router)
app.include_router(llm_match_router)
app.include_router(llm_semantic_router)
app.include_router(llm_experience_router)
STATIC_HTML = Path(__file__).resolve().parent.parent / "static" / "index.html"


@app.get("/", response_class=HTMLResponse)
async def index() -> str:
    return STATIC_HTML.read_text(encoding="utf-8")


@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok", "version": "0.1.0", "hh_user_agent_configured": bool(os.getenv("HH_USER_AGENT", "").strip())}


@app.post("/api/analyze")
async def analyze(
    resume: UploadFile = File(...),
    search_query: str = Form("Python разработчик"),
    mode: str = Form("demo"),
    count: int = Form(5),
    area: str = Form(""),
) -> dict:
    if mode not in {"demo", "hh"}:
        raise HTTPException(422, "mode должен быть 'demo' или 'hh'")
    if not 1 <= count <= 10:
        raise HTTPException(422, "Число вакансий должно быть от 1 до 10")
    if mode == "hh" and not search_query.strip():
        raise HTTPException(422, "Укажите поисковый запрос")
    if area and not area.isdigit():
        raise HTTPException(422, "Код региона area должен быть числом")
    raw = await resume.read(MAX_FILE_BYTES + 1)
    try:
        document = extract_document(resume.filename or "", raw)
        profile = build_resume_json(document)
        vacancies = demo_vacancies()[:count] if mode == "demo" else await search_hh(search_query.strip(), count, area or None)
    except (DocumentError, VacancyError) as exc:
        raise HTTPException(400, str(exc)) from exc
    finally:
        await resume.close()
    return {
        "mode": mode,
        "source_label": "Синтетические вакансии (демо)" if mode == "demo" else "HeadHunter API — реальные вакансии",
        "search_query": search_query,
        "resume": profile,
        "matches": rank_matches(profile, vacancies),
        "summary": {"vacancies_count": len(vacancies), "extracted_skills_count": len(profile["skills"])},
        "data_policy": "Резюме обрабатывается локально без постоянного хранения; на hh.ru передаётся только поисковый запрос.",
    }
