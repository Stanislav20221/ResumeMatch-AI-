"""Deterministic explainable matrix (not a predictive probability or LLM verdict)."""
from __future__ import annotations

from typing import Any


def match_one(resume: dict[str, Any], vacancy: dict[str, Any]) -> dict[str, Any]:
    evidence = {item["name"]: item for item in resume["skills"]}
    rows = []
    resume_sources = {block["source_text"] for block in resume.get("source_blocks", [])}
    vacancy_description_sources = set(vacancy.get("description_text", "").splitlines())
    vacancy_key_skill_sources = set(vacancy.get("key_skills", []))
    for requirement in vacancy["requirements"]:
        skill = requirement["skill"]
        found = evidence.get(skill)
        required_source = requirement["source_text"]
        requirement_verified = (
            required_source in vacancy_key_skill_sources
            if requirement["source_field"] == "key_skills"
            else required_source in vacancy_description_sources
        )
        candidate_verified = bool(found and found["source_text"] in resume_sources)
        source_verified = requirement_verified and (not found or candidate_verified)
        rows.append({
            "requirement": skill,
            "status": "matched" if found and source_verified else ("unverified" if not source_verified else "no_evidence"),
            "source_verified": source_verified,
            "vacancy_source_text": requirement["source_text"],
            "vacancy_source_field": requirement["source_field"],
            "vacancy_url": vacancy["url"],
            "resume_source_text": found["source_text"] if found else None,
            "resume_page": found["page"] if found else None,
            "match_type": "explicit_skill_or_alias" if found else None,
        })
    total = len(rows)
    matched = sum(row["status"] == "matched" for row in rows)
    score = round(100 * matched / total) if total else None
    return {
        "vacancy": vacancy,
        "score_percent": score,
        "matched_count": matched,
        "scored_requirement_count": total,
        "matrix": rows,
        "limitations": (
            "Эвристическая доля явно упомянутых навыков из известных словарю. "
            "Не является вероятностью найма и не оценивает стаж, глубину опыта, контекст, "
            "зарплату, личные качества и требования вне словаря. "
            "Отсутствие подтверждения в резюме не означает отсутствие навыка."
        ),
    }


def rank_matches(resume: dict[str, Any], vacancies: list[dict[str, Any]]) -> list[dict[str, Any]]:
    results = [match_one(resume, vacancy) for vacancy in vacancies]
    return sorted(results, key=lambda item: (item["score_percent"] is not None, item["score_percent"] or 0), reverse=True)
