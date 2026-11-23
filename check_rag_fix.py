"""Проверка исправления RAG без обращения к OpenAI API."""
from app.llm_matching import match_extractions

resume = {"fields": {
    "skills": [{
        "value": "FAISS",  # Имитируем пропуск RAG при LLM-извлечении.
        "source_text": "RAG, FAISS, LangChain, OpenAI API, REST API, SQL, Git.",
        "source_verified": True,
        "source_field": "resume",
        "page": None,
    }],
}}
vacancy = {"fields": {
    "required_skills": [
        {"value": name, "source_text": f"Требования: {name}", "source_verified": True}
        for name in ("RAG", "FAISS")
    ],
    "optional_skills": [],
    "experience": [],
    "responsibilities": [],
    "conditions": [],
}}

result = match_extractions(resume, vacancy)
print("Доля точных совпадений:", result["score_percent"], "%")
print("Навыки, восстановленные из перечня:", result["recovered_explicit_skills"])
for row in result["required_matrix"]:
    print(row["requirement"], "->", row["status"], "/", row["match_method"])
assert result["score_percent"] == 100
assert result["recovered_explicit_skills"] == ["RAG"]
print("RAG REGRESSION FIX PASSED")
