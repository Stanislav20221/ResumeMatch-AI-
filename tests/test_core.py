import io

import fitz
from docx import Document
from fastapi.testclient import TestClient

from app.documents import DocumentError, build_resume_json, extract_document
from app.matching import match_one
from app.skills import find_skills
from app.vacancies import html_to_text, normalize_vacancy
from app.main import app

client = TestClient(app)


def test_skill_evidence_not_substrings():
    assert "Git" not in [s.name for s in find_skills("digital marketing")]
    assert "Python" in [s.name for s in find_skills("Python; Django")]
    assert "PostgreSQL" in [s.name for s in find_skills("Postgres")]


def test_pdf_page_citation():
    pdf = fitz.open()
    page = pdf.new_page()
    page.insert_text((40, 70), "Python FastAPI Docker")
    document = extract_document("resume.pdf", pdf.tobytes())
    profile = build_resume_json(document)
    assert any(s["name"] == "Python" and s["page"] == 1 for s in profile["skills"])


def test_docx_support():
    doc = Document()
    doc.add_paragraph("My experience: Python and Django")
    b = io.BytesIO()
    doc.save(b)
    profile = build_resume_json(extract_document("cv.docx", b.getvalue()))
    assert {s["name"] for s in profile["skills"]} >= {"Python", "Django"}


def test_clean_vacancy_and_sources():
    vacancy = normalize_vacancy({"id":"123", "name":"Python Dev", "key_skills":[{"name":"Docker"}],
        "description":"<p>Опыт FastAPI и PostgreSQL.</p><script>bad()</script>"})
    assert "bad()" not in vacancy["description_text"]
    assert {r["skill"] for r in vacancy["requirements"]} >= {"Docker", "FastAPI", "PostgreSQL"}
    assert all(r["source_text"] for r in vacancy["requirements"])


def test_matching_provenance_and_unknowns():
    resume = build_resume_json(extract_document("cv.txt", "Python и Docker".encode()))
    vacancy = normalize_vacancy({"id":"123","key_skills":[{"name":"Python"},{"name":"Kubernetes"}]})
    result = match_one(resume, vacancy)
    assert result["score_percent"] == 50
    assert result["matched_count"] == 1
    assert next(x for x in result["matrix"] if x["requirement"] == "Python")["resume_source_text"] == "Python и Docker"
    assert next(x for x in result["matrix"] if x["requirement"] == "Kubernetes")["status"] == "no_evidence"


def test_unknown_skills_do_not_produce_fake_100():
    vacancy = normalize_vacancy({"id":"123","description":"Нужен уникальный отраслевой опыт."})
    resume = build_resume_json(extract_document("cv.txt", "Python".encode()))
    assert match_one(resume, vacancy)["score_percent"] is None


def test_demo_api_e2e():
    with open("samples/demo_resume.txt", "rb") as f:
        response = client.post("/api/analyze", data={"mode":"demo","count":3},
                               files={"resume":("resume.txt",f,"text/plain")})
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["mode"] == "demo" and len(data["matches"]) == 3
    assert data["matches"][0]["score_percent"] is not None
    assert data["matches"][0]["matrix"]
    assert data["resume"]["skills"]


def test_invalid_extension_and_empty_resume():
    r = client.post("/api/analyze",data={"mode":"demo"},files={"resume":("cv.exe",b"hi")})
    assert r.status_code == 400
    r = client.post("/api/analyze",data={"mode":"demo"},files={"resume":("cv.txt",b"")})
    assert r.status_code == 400


def test_api_input_validation():
    r = client.post("/api/analyze",data={"mode":"demo","count":500},files={"resume":("cv.txt",b"Python")})
    assert r.status_code == 422


def test_hh_requires_agent(monkeypatch):
    import asyncio
    from app.vacancies import search_hh, VacancyError
    monkeypatch.delenv("HH_USER_AGENT",raising=False)
    try:
        asyncio.run(search_hh("Python", 2))
        assert False
    except VacancyError as exc:
        assert "HH_USER_AGENT" in str(exc)


def test_demo_vacancies_do_not_forge_hh_links():
    from app.demo import demo_vacancies
    assert all(v["url"] == "" for v in demo_vacancies())


def test_hh_norm_link_for_real_id():
    assert normalize_vacancy({"id":"1234"})["url"] == "https://hh.ru/vacancy/1234"


def test_modified_source_evidence_cannot_be_counted():
    resume = build_resume_json(extract_document("cv.txt", b"Python"))
    vacancy = normalize_vacancy({"id":"123","key_skills":[{"name":"Python"}]})
    resume["skills"][0]["source_text"] = "I am a Python expert (invented)"
    m = match_one(resume, vacancy)
    assert m["score_percent"] == 0
    assert m["matrix"][0]["source_verified"] is False


def test_live_search_adapter_mocked(monkeypatch):
    import asyncio
    from app import vacancies
    import httpx
    monkeypatch.setenv("HH_USER_AGENT", "ResumeMatchAI/0.1 (contact: dev@real-company.ru)")
    calls = []
    def handler(request):
        calls.append(str(request.url))
        if request.url.path == '/vacancies':
            assert request.url.params.get('text') == 'FastAPI'
            assert request.url.params.get('per_page') == '1'
            return httpx.Response(200,json={"items":[{"id":"4567"}]})
        assert request.url.path == '/vacancies/4567'
        return httpx.Response(200,json={"id":"4567","name":"Backend dev","description":"<p>Требуется Python, FastAPI.</p>","key_skills":[]})
    original_client = vacancies.httpx.AsyncClient
    def fake_client(*args,**kwargs):
        return original_client(transport=httpx.MockTransport(handler),*args,**kwargs)
    monkeypatch.setattr(vacancies.httpx,"AsyncClient",fake_client)
    result = asyncio.run(vacancies.search_hh('FastAPI',1))
    assert result[0]['name']=='Backend dev'
    assert {x['skill'] for x in result[0]['requirements']} == {'Python','FastAPI'}
    assert len(calls)==2
