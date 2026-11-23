"""Офлайн-тесты v0.4: реальный API OpenAI ни разу не вызывается."""
import asyncio
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.llm_semantic import Decision, Decisions, semantic_match
from app.llm_semantic_api import router


def f(value, quote, verified=True):
    return {"value": value, "source_text": quote, "source_verified": verified, "page": 2}


def datasets():
    resume = {"fields": {
        "skills": [f("Python", "Пишу на Python"), f("FastAPI", "Создавал веб-сервисы на FastAPI")],
        "projects": [f("Разработка HTTP endpoints", "В проекте разрабатывал HTTP endpoints")],
        "experience": [f("Разрабатывал на Python 1 год", "Python 1 год")],
    }}
    vacancy = {"fields": {
        "required_skills": [f("Python", "Нужен Python"), f("REST API", "Опыт REST API")],
        "optional_skills": [f("Kubernetes", "Будет плюсом Kubernetes")],
        "experience": [f("От 3 лет", "Нужен опыт от 3 лет")],
    }}
    return resume, vacancy


class MockResponses:
    def __init__(self, decisions):
        self.decisions = decisions
        self.calls = []
        self.responses = self

    async def parse(self, **kwargs):
        self.calls.append(kwargs)
        assert kwargs["store"] is False
        assert kwargs["text_format"] is Decisions
        return SimpleNamespace(output_parsed=Decisions(decisions=self.decisions))


def test_exact_unchanged_semantic_proposal_is_separate():
    resume, vacancy = datasets()
    mock = MockResponses([
        Decision(requirement_id="r0", verdict="supported", evidence_ids=["e3"], reason="HTTP endpoints"),
        Decision(requirement_id="r1", verdict="unsupported", evidence_ids=[], reason="Нет данных"),
        Decision(requirement_id="r2", verdict="partial", evidence_ids=["e2"], reason="Указан один год"),
    ])
    out = asyncio.run(semantic_match(resume, vacancy, client=mock))
    assert out["score_percent"] == 50
    assert out["semantic_score_percent"] == 100
    assert out["semantic_suggested_required"] == 1
    assert out["required_matrix"][1]["status"] == "semantic_suggestion"
    assert out["required_matrix"][1]["semantic_evidence"][0]["quote"] == "В проекте разрабатывал HTTP endpoints"
    assert out["experience_reviews"][0]["verdict"] == "partial"
    assert out["semantic_scored"] is False
    assert len(mock.calls) == 1


def test_unknown_evidence_id_does_not_confirm():
    resume, vacancy = datasets()
    mock = MockResponses([Decision(requirement_id="r0", verdict="supported", evidence_ids=["invented"], reason="Выдуманная цитата")])
    out = asyncio.run(semantic_match(resume, vacancy, client=mock))
    assert out["semantic_score_percent"] == 50
    assert out["required_matrix"][1]["status"] == "not_confirmed"


def test_unverified_resume_quotes_not_forwarded():
    resume, vacancy = datasets()
    resume["fields"]["projects"] = [f("Kubernetes", "Kubernetes", verified=False)]
    mock = MockResponses([Decision(requirement_id="r1", verdict="supported", evidence_ids=["e3"], reason="")])
    out = asyncio.run(semantic_match(resume, vacancy, client=mock))
    assert out["optional_matrix"][0]["status"] == "not_confirmed"
    assert out["semantic_suggested_optional"] == 0


def test_review_requirement_keeps_score_hidden():
    resume, vacancy = datasets()
    vacancy["fields"]["required_skills"].append(f("Docker", "Другой текст", verified=False))
    out = asyncio.run(semantic_match(resume, vacancy, client=MockResponses([])))
    assert out["score_percent"] is None
    assert out["semantic_score_percent"] is None


def test_without_candidate_no_paid_request():
    resume = {"fields": {"skills": [f("Python", "Python")]}}
    vacancy = {"fields": {"required_skills": [f("Python", "Python")]}}
    mock = MockResponses([])
    out = asyncio.run(semantic_match(resume, vacancy, client=mock))
    assert out["score_percent"] == 100
    assert out["semantic_score_percent"] == 100
    assert out["semantic_model"] == "not_called"
    assert not mock.calls


def test_duplicate_model_requirement_ignored():
    resume, vacancy = datasets()
    mock = MockResponses([
        Decision(requirement_id="r0", verdict="supported", evidence_ids=["e3"], reason="ok"),
        Decision(requirement_id="r0", verdict="supported", evidence_ids=["e1"], reason="again"),
        Decision(requirement_id="r555", verdict="supported", evidence_ids=["e1"], reason="invented"),
    ])
    out = asyncio.run(semantic_match(resume, vacancy, client=mock))
    assert out["semantic_suggested_required"] == 1
    assert out["required_matrix"][1]["semantic_evidence"][0]["id"] == "e3"


def test_api_requires_consent():
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    r, v = datasets()
    out = client.post("/api/llm/semantic-match", json={"resume": r, "vacancy": v})
    assert out.status_code == 422


def test_api_responds_with_mocked_semantic(monkeypatch):
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    async def fake(resume, vacancy):
        return {"semantic_score_percent": 50}
    monkeypatch.setattr("app.llm_semantic_api.semantic_match", fake)
    r, v = datasets()
    out = client.post("/api/llm/semantic-match", json={"resume": r, "vacancy": v, "cloud_consent": True})
    assert out.status_code == 200
    assert out.json()["semantic_score_percent"] == 50
