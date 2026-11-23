"""Offline regression tests for numeric experience requirements demo fixture."""

import asyncio
from datetime import date
from pathlib import Path
from types import SimpleNamespace

from app.demo import demo_vacancies
from app.documents import extract_document
from app.llm_experience import (
    DutyDecision,
    DutyDecisions,
    Employment,
    EmploymentOutput,
    EvidenceFact,
    analyze_experience,
)


def test_fourth_demo_is_visible_with_count_five_and_has_verbatim_requirements():
    vacancies = demo_vacancies()
    assert len(vacancies) == 4
    assert [v["id"] for v in vacancies[:3]] == ["demo-1", "demo-2", "demo-3"]
    vacancy = vacancies[3]
    assert vacancy["id"] == "demo-4"
    assert vacancy["url"] == ""
    description = vacancy["description_text"]
    assert "Опыт разработки на Python от 3 лет." in description.splitlines()
    assert "Опыт работы с FastAPI от 2 лет." in description.splitlines()
    assert "Разрабатывать REST API." in description.splitlines()
    assert "Интегрировать LLM в backend-сервисы." in description.splitlines()
    assert "Опыт работы с Kubernetes." in description.splitlines()
    assert {"Python", "FastAPI"} <= set(vacancy["key_skills"])


def _fact(value: str, quote: str) -> EvidenceFact:
    return EvidenceFact(value=value, source_text=quote)


class OfflineClient:
    """Two deterministic model replies; no network, no billing."""

    def __init__(self, *, python_in_job: bool = True):
        self.python_in_job = python_in_job
        self.calls = []
        self.responses = self

    async def parse(self, **kwargs):
        self.calls.append(kwargs)
        assert kwargs["store"] is False
        if kwargs["text_format"] is EmploymentOutput:
            first = (
                "Разрабатывал REST API на Python, FastAPI и PostgreSQL."
                if self.python_in_job else
                "Разрабатывал REST API на FastAPI и PostgreSQL."
            )
            return SimpleNamespace(output_parsed=EmploymentOutput(jobs=[
                Employment(
                    role="Backend-разработчик", role_source_text="Backend-разработчик",
                    period_source_text="01.2022 — 05.2025",
                    start_month="2022-01", end_month="2025-05", is_current=False,
                    tasks=[_fact("Разработка REST API", first)],
                    technologies=[
                        _fact("FastAPI", first),
                        *([_fact("Python", first)] if self.python_in_job else []),
                        _fact("PostgreSQL", first),
                    ],
                ),
                Employment(
                    role="AI-разработчик", role_source_text="AI-разработчик",
                    period_source_text="09.2024 — 10.2026",
                    start_month="2024-09", end_month="2026-10", is_current=False,
                    tasks=[
                        _fact("Интеграция LLM", "Интегрировал LLM через OpenAI API в backend-сервисы."),
                        _fact("Разработка REST API", "Разрабатывал REST API для поиска по базе знаний."),
                    ],
                    technologies=[_fact("OpenAI API", "Интегрировал LLM через OpenAI API в backend-сервисы.")],
                ),
            ]))
        return SimpleNamespace(output_parsed=DutyDecisions(decisions=[
            DutyDecision(requirement_id="r0", verdict="supported", evidence_ids=["e0"],
                         explanation="REST API разрабатывались на первом месте работы."),
            DutyDecision(requirement_id="r1", verdict="supported", evidence_ids=["e1"],
                         explanation="Есть описание интеграции LLM."),
        ]))


def _vacancy_extraction():
    """Mimics a correctly extracted vacancy, with exact original snippets."""
    return {"fields": {
        "experience": [
            {"value": "Опыт Python от 3 лет", "source_text": "Опыт разработки на Python от 3 лет.",
             "source_verified": True},
            {"value": "Опыт FastAPI от 2 лет", "source_text": "Опыт работы с FastAPI от 2 лет.",
             "source_verified": True},
        ],
        "responsibilities": [
            {"value": "Разрабатывать REST API", "source_text": "Разрабатывать REST API.",
             "source_verified": True},
            {"value": "Интегрировать LLM", "source_text": "Интегрировать LLM в backend-сервисы.",
             "source_verified": True},
        ],
    }}


def test_full_offline_v05_numeric_requirements_and_duties():
    vacancy = demo_vacancies()[3]
    path = Path(__file__).parents[1] / "samples" / "demo_resume_experience_positive.txt"
    document = extract_document(path.name, path.read_bytes())
    fake = OfflineClient()
    result = asyncio.run(analyze_experience(
        document, _vacancy_extraction(), vacancy, client=fake, today=date(2026, 11, 23)))
    assert result["summary"]["documented_months_total_conservative"] == 57
    assert result["summary"]["jobs_with_verified_dates"] == 2
    assert result["summary"]["llm_request_count"] == 2
    requirements = {r["skill"]: r for r in result["experience_requirements"]}
    assert requirements["Python"]["required_months"] == 36
    assert requirements["FastAPI"]["required_months"] == 24
    assert requirements["Python"]["documented_months"] == 40
    assert requirements["FastAPI"]["documented_months"] == 40
    assert all(r["status"] == "duration_meets_provisionally" for r in requirements.values())
    assert all(r["vacancy_source_verified"] for r in requirements.values())
    assert len(result["responsibility_reviews"]) == 2
    assert all(r["human_review_required"] for r in result["responsibility_reviews"])
    assert all(r["verdict"] == "supported" for r in result["responsibility_reviews"])
    assert result["summary"]["skills_score_changed"] is False


def test_global_skill_list_does_not_inflate_python_job_duration():
    vacancy = demo_vacancies()[3]
    path = Path(__file__).parents[1] / "samples" / "demo_resume_dated.txt"
    document = extract_document(path.name, path.read_bytes())
    fake = OfflineClient(python_in_job=False)
    result = asyncio.run(analyze_experience(
        document, _vacancy_extraction(), vacancy, client=fake, today=date(2026, 11, 23)))
    requirements = {r["skill"]: r for r in result["experience_requirements"]}
    assert requirements["Python"]["documented_months"] is None
    assert requirements["Python"]["status"] == "insufficient_data"
    assert requirements["FastAPI"]["documented_months"] == 40
