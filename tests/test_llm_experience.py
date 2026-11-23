"""v0.5: офлайн-тесты — не выполняют настоящих платных вызовов OpenAI."""
import asyncio
import json
from datetime import date
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.llm_experience import (
    DutyDecision, DutyDecisions, Employment, EmploymentOutput,
    EvidenceFact, _date_tokens, _employment_rows, _merge_intervals,
    _minimum_months, analyze_experience,
)
from app.llm_experience_api import router


def fact(value, quote):
    return EvidenceFact(value=value, source_text=quote)


def job(start="01.2022", end="05.2025", current=False):
    period = f"{start} — {end}" if not current else f"{start} — настоящее время"
    return Employment(
        role="Backend-разработчик",
        role_source_text="Backend-разработчик",
        period_source_text=period,
        start_month="2022-01" if start == "01.2022" else "2024-01",
        end_month="2025-05" if end == "05.2025" and not current else "",
        is_current=current,
        tasks=[fact("Разработка REST API", "Разрабатывал REST API на FastAPI")],
        technologies=[fact("FastAPI", "Разрабатывал REST API на FastAPI")],
    )


def data():
    doc = {"blocks": [
        {"source_text": "Backend-разработчик", "page": 1},
        {"source_text": "01.2022 — 05.2025", "page": 1},
        {"source_text": "Разрабатывал REST API на FastAPI", "page": 1},
    ]}
    vacancy = {"fields": {
        "experience": [{"value": "Опыт FastAPI от 2 лет", "source_text": "Опыт FastAPI от 2 лет.",
                        "source_verified": True}],
        "responsibilities": [{"value": "Разрабатывать REST API", "source_text": "Разрабатывать REST API.",
                              "source_verified": True}],
    }}
    source = {"description_text": "Опыт FastAPI от 2 лет.\nРазрабатывать REST API.",
              "key_skills": ["FastAPI", "Python"]}
    return doc, vacancy, source


class FakeClient:
    def __init__(self, job_response=None, duty_decisions=None):
        self.responses = self
        self.jobs = job_response or EmploymentOutput(jobs=[job()])
        self.decisions = duty_decisions if duty_decisions is not None else [
            DutyDecision(requirement_id="r0", verdict="supported", evidence_ids=["e0"], explanation="REST API")
        ]
        self.calls = []

    async def parse(self, **kwargs):
        self.calls.append(kwargs)
        assert kwargs["store"] is False
        if kwargs["text_format"] is EmploymentOutput:
            return SimpleNamespace(output_parsed=self.jobs)
        assert kwargs["text_format"] is DutyDecisions
        return SimpleNamespace(output_parsed=DutyDecisions(decisions=self.decisions))


def test_valid_date_parsing_and_no_year_only_guess():
    assert _date_tokens("01.2022 — 2024-12") == ["2022-01", "2024-12"]
    assert _date_tokens("2022 — 2024") == []
    assert _date_tokens("Январь 2022 — октября 2024") == ["2022-01", "2024-10"]


def test_monthly_overlaps_do_not_double_count():
    assert _merge_intervals([(100, 120), (115, 130), (125, 140)]) == 40
    assert _merge_intervals([(100, 110), (130, 140)]) == 20


def test_months_required():
    assert _minimum_months("Опыт Python от 2 лет") == 24
    assert _minimum_months("Стаж 2,5 года") == 30
    assert _minimum_months("Не менее 18 месяцев") == 18
    assert _minimum_months("Стаж три года") is None
    assert _minimum_months("Проект выполнен в 2024 году") is None


def test_dates_verified_with_original_quote():
    doc, _, _ = data()
    selected = [{"block_id": i, "text": b["source_text"], "page": b["page"]}
                for i, b in enumerate(doc["blocks"])]
    rows = _employment_rows(EmploymentOutput(jobs=[job()]), selected, today=date(2026, 11, 22))
    assert rows[0]["dates_verified"] is True
    assert rows[0]["conservative_months"] == 40
    assert rows[0]["tasks"][0]["source_verified"] is True
    assert rows[0]["technologies"][0]["source_verified"] is True
    assert rows[0]["period_page"] == 1


def test_model_cannot_forge_dates_or_skills():
    doc, _, _ = data()
    selected = [{"block_id": i, "text": b["source_text"], "page": b["page"]}
                for i, b in enumerate(doc["blocks"])]
    wrong = job()
    wrong.start_month = "2021-01"
    wrong.technologies = [fact("Kubernetes", "Разрабатывал REST API на FastAPI")]
    rows = _employment_rows(EmploymentOutput(jobs=[wrong]), selected, today=date(2026, 11, 22))
    assert rows[0]["dates_verified"] is False
    assert rows[0]["conservative_months"] is None
    assert rows[0]["technologies"][0]["source_verified"] is False


def test_year_only_does_not_calculate_duration():
    doc, _, _ = data()
    selected = [{"block_id": 0, "text": "Backend-разработчик", "page": 1},
                {"block_id": 1, "text": "2022 — 2025", "page": 1}]
    uncertain = job()
    uncertain.period_source_text = "2022 — 2025"
    rows = _employment_rows(EmploymentOutput(jobs=[uncertain]), selected, today=date(2026, 11, 22))
    assert rows[0]["dates_verified"] is False


def test_full_pipeline_with_dated_resume_and_compared_duties():
    doc, vacancy, source = data()
    fake = FakeClient()
    result = asyncio.run(analyze_experience(doc, vacancy, source, client=fake, today=date(2026, 11, 22)))
    assert result["summary"]["documented_months_total_conservative"] == 40
    assert result["experience_requirements"][0]["required_months"] == 24
    assert result["experience_requirements"][0]["status"] == "duration_meets_provisionally"
    assert result["experience_requirements"][0]["documented_months"] == 40
    assert result["responsibility_reviews"][0]["verdict"] == "supported"
    assert result["summary"]["skills_score_changed"] is False
    assert result["summary"]["llm_request_count"] == 2
    assert len(fake.calls) == 2
    assert "_interval" not in result["jobs"][0]


def test_fake_evidence_id_never_supported():
    doc, vacancy, source = data()
    fake = FakeClient(duty_decisions=[DutyDecision(
        requirement_id="r0", verdict="supported", evidence_ids=["invented"], explanation="Совпадает")])
    result = asyncio.run(analyze_experience(doc, vacancy, source, client=fake, today=date(2026, 11, 22)))
    assert result["responsibility_reviews"][0]["verdict"] == "unsupported"
    assert result["responsibility_reviews"][0]["evidence"] == []


def test_false_vacancy_quote_cannot_confirm_requirement():
    doc, vacancy, source = data()
    vacancy["fields"]["experience"][0]["source_text"] = "Опыт от 100 лет."
    result = asyncio.run(analyze_experience(doc, vacancy, source, client=FakeClient(), today=date(2026, 11, 22)))
    assert result["experience_requirements"][0]["status"] == "source_unverified"


def test_missing_dated_job_not_treated_as_zero_months():
    doc, vacancy, source = data()
    missing = job()
    missing.period_source_text = "Период не указан"
    result = asyncio.run(analyze_experience(doc, vacancy, source,
        client=FakeClient(job_response=EmploymentOutput(jobs=[missing])), today=date(2026, 11, 22)))
    assert result["experience_requirements"][0]["documented_months"] is None
    assert result["experience_requirements"][0]["status"] == "insufficient_data"


def test_ongoing_requires_explicit_present():
    selected = [{"block_id": 0, "text": "Backend-разработчик", "page": 1},
                {"block_id": 1, "text": "01.2022 — настоящее время", "page": 1},
                {"block_id": 2, "text": "Разрабатывал REST API на FastAPI", "page": 1}]
    rows = _employment_rows(EmploymentOutput(jobs=[job(current=True)]), selected, today=date(2026, 11, 22))
    assert rows[0]["dates_verified"] is True
    assert rows[0]["conservative_months"] == 58


def test_no_resume_tasks_skips_second_llm_call():
    doc, vacancy, source = data()
    no_tasks = job()
    no_tasks.tasks = []
    fake = FakeClient(job_response=EmploymentOutput(jobs=[no_tasks]))
    result = asyncio.run(analyze_experience(doc, vacancy, source, client=fake, today=date(2026, 11, 22)))
    assert len(fake.calls) == 1
    assert result["responsibility_reviews"][0]["verdict"] == "unsupported"


def test_api_rejects_missing_consent_before_paid_request():
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    response = client.post('/api/llm/experience-match', data={
        "cloud_consent": "false", "vacancy_extraction": "{}", "vacancy_source": "{}"},
        files={"resume": ("x.txt", b"Backend developer 01.2022", "text/plain")})
    assert response.status_code == 422


def test_api_sends_document_without_real_llm(monkeypatch):
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    async def mock_analyze(document, extraction, source):
        assert document["blocks"][0]["source_text"] == "Backend-разработчик"
        return {"summary": {"jobs_extracted": 1}}

    monkeypatch.setattr("app.llm_experience_api.analyze_experience", mock_analyze)
    response = client.post('/api/llm/experience-match', data={
        "cloud_consent": "true", "vacancy_extraction": json.dumps({"fields": {}}),
        "vacancy_source": json.dumps({"description_text": "Опыт 2 года"})},
        files={"resume": ("x.txt", "Backend-разработчик\n01.2022 — 05.2025".encode(), "text/plain")})
    assert response.status_code == 200
    assert response.json()["summary"]["jobs_extracted"] == 1
