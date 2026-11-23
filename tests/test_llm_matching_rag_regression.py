"""Регрессия: явный RAG в проверенном списке навыков не требует LLM.

Только локальные тесты, никаких платных API-запросов.
"""
import asyncio
from types import SimpleNamespace

from app.llm_matching import match_extractions
from app.llm_semantic import semantic_match


def fact(value, quote, *, verified=True):
    return {
        "value": value,
        "source_text": quote,
        "source_verified": verified,
        "source_field": "resume",
        "page": None,
    }


def texts(skills, required):
    return (
        {"fields": {"skills": skills, "projects": [], "experience": [], "education": []}},
        {"fields": {"required_skills": required, "optional_skills": [], "experience": []}},
    )


class NoOpenAICalls:
    def __init__(self):
        self.responses = self
        self.calls = 0

    async def parse(self, **kwargs):
        self.calls += 1
        raise AssertionError("Точное совпадение RAG не должно отправляться в LLM")


def test_rag_recovered_from_verified_skill_list():
    quote = "RAG, FAISS, LangChain, OpenAI API, REST API, SQL, Git."
    resume, vacancy = texts(
        [fact("FAISS", quote)],  # LLM пропустила отдельный value=RAG
        [fact("RAG", "Требования: RAG"), fact("FAISS", "Требования: FAISS")],
    )
    result = match_extractions(resume, vacancy)
    assert result["score_percent"] == 100
    assert result["required_matched"] == 2
    assert result["required_matrix"][0]["status"] == "matched"
    assert result["required_matrix"][0]["match_method"] == "literal_in_verified_skill_list"
    assert result["required_matrix"][0]["resume_source_text"] == quote
    assert result["recovered_explicit_skills"] == ["RAG"]


def test_rag_from_skill_list_does_not_trigger_semantic_llm():
    resume, vacancy = texts(
        [fact("FAISS", "Навыки: RAG, FAISS, LangChain.")],
        [fact("RAG", "Нужен RAG"), fact("FAISS", "Нужен FAISS")],
    )
    mock = NoOpenAICalls()
    out = asyncio.run(semantic_match(resume, vacancy, client=mock))
    assert mock.calls == 0
    assert out["semantic_model"] == "not_called"
    assert out["score_percent"] == 100
    assert out["semantic_suggested_required"] == 0


def test_no_recovery_when_quote_not_verified():
    resume, vacancy = texts(
        [fact("FAISS", "RAG, FAISS, LangChain.", verified=False)],
        [fact("RAG", "Нужен RAG")],
    )
    out = match_extractions(resume, vacancy)
    assert out["score_percent"] == 0
    assert out["recovered_explicit_skills"] == []


def test_no_recovery_in_negative_sentence():
    resume, vacancy = texts(
        [fact("FAISS", "Изучал FAISS, но не работал с RAG.")],
        [fact("RAG", "Нужен RAG")],
    )
    out = match_extractions(resume, vacancy)
    assert out["score_percent"] == 0


def test_no_recovery_from_project_only():
    resume, vacancy = texts([], [fact("RAG", "Нужен RAG")])
    resume["fields"]["projects"] = [fact("Разработка RAG", "Разработал AI-консультанта с RAG")]
    out = match_extractions(resume, vacancy)
    assert out["score_percent"] == 0  # такой опыт сначала оценивается по смыслу


def test_no_substring_match_go_in_django():
    resume, vacancy = texts(
        [fact("Django", "Python, Django, FastAPI")],
        [fact("Go", "Нужен Go")],
    )
    assert match_extractions(resume, vacancy)["score_percent"] == 0


def test_normalized_explicit_alias_from_list():
    resume, vacancy = texts(
        [fact("Python", "Python, DRF, PostgreSQL")],
        [fact("Django REST Framework", "Нужен Django REST Framework")],
    )
    out = match_extractions(resume, vacancy)
    assert out["score_percent"] == 100
    assert out["required_matrix"][0]["match_method"] == "literal_in_verified_skill_list"
