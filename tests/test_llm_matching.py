"""Офлайн-тесты нового матчера: ни одного платного запроса."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.llm_match_api import router
from app.llm_matching import match_extractions


def fact(value, source=None, verified=True):
    return {
        "value": value,
        "source_text": source if source is not None else f"Владею {value}.",
        "source_verified": verified,
        "page": 2,
        "source_field": "test",
    }


def payload(resume_skills=None, required=None, optional=None):
    return (
        {"fields": {"skills": resume_skills or []}},
        {"fields": {
            "required_skills": required or [],
            "optional_skills": optional or [],
            "experience": [fact("Опыт от 2 лет", "Опыт от 2 лет")],
            "responsibilities": [],
            "conditions": [],
        }},
    )


def test_verified_match_and_optional_excluded_from_score():
    resume, vacancy = payload(
        [fact("Python", "Python, FastAPI"), fact("FastAPI", "Python, FastAPI")],
        [fact("Python", "Требования: Python, FastAPI"),
         fact("FastAPI", "Требования: Python, FastAPI"),
         fact("PostgreSQL", "Требование: PostgreSQL")],
        [fact("Docker", "Будет плюсом Docker")],
    )
    out = match_extractions(resume, vacancy)
    assert out["score_percent"] == 67
    assert out["required_matched"] == 2
    assert out["required_total"] == 3
    assert out["optional_total"] == 1
    assert out["optional_matched"] == 0
    assert out["required_matrix"][0]["resume_page"] == 2
    assert out["required_matrix"][2]["status"] == "not_confirmed"
    assert "experience" in out["not_scored"]


def test_duplicate_required_skill_is_counted_once():
    r, v = payload([fact("Python")], [fact("Python"), fact("python")])
    out = match_extractions(r, v)
    assert out["score_percent"] == 100
    assert out["required_total"] == 1


def test_unverified_resume_quote_not_matched():
    r, v = payload([fact("Kubernetes", verified=False)], [fact("Kubernetes")])
    out = match_extractions(r, v)
    assert out["score_percent"] == 0
    assert out["required_matrix"][0]["status"] == "not_confirmed"


def test_fake_skill_with_real_but_unrelated_quote_not_matched():
    r, v = payload([fact("Kubernetes", "Владею Python")], [fact("Kubernetes")])
    assert match_extractions(r, v)["score_percent"] == 0


def test_unverified_vacancy_quote_makes_score_unavailable():
    r, v = payload([fact("Python")], [fact("Python"), fact("Docker", verified=False)])
    out = match_extractions(r, v)
    assert out["score_percent"] is None
    assert out["required_review_total"] == 1
    assert out["required_matrix"][1]["status"] == "manual_review"


def test_no_required_skills_does_not_give_100_percent():
    r, v = payload([fact("Python")], optional=[fact("Python")])
    out = match_extractions(r, v)
    assert out["score_percent"] is None
    assert out["optional_matched"] == 1


def test_quoted_go_does_not_match_django():
    r, v = payload([fact("Go", "Разрабатывал на Django")], [fact("Go", "Нужен Go")])
    assert match_extractions(r, v)["score_percent"] == 0


def test_known_alias_drf_matches_django_rest_framework():
    r, v = payload([fact("DRF", "Использовал DRF")],
                   [fact("Django REST Framework", "Нужен Django REST Framework")])
    assert match_extractions(r, v)["score_percent"] == 100


def test_only_unique_requirements_optional_cannot_duplicate_required():
    r, v = payload([fact("Python")], [fact("Python")], [fact("Python")])
    out = match_extractions(r, v)
    assert out["optional_total"] == 0


def test_api_is_exposed_and_validated():
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    resume, vacancy = payload([fact("Python")], [fact("Python")])
    response = client.post("/api/llm/match", json={"resume": resume, "vacancy": vacancy})
    assert response.status_code == 200
    assert response.json()["score_percent"] == 100
    response = client.post("/api/llm/match", json={"resume": {"fields": []}, "vacancy": vacancy})
    assert response.status_code == 422
