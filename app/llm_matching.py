"""Детерминированная матрица на основе проверенных LLM-фактов.

Это только буквальное сопоставление и небольшой явный набор синонимов.
Ни новая генерация, ни семантическая оценка, ни оценка стажа здесь не выполняются.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any

# Только очевидные синонимы названий; не расширяем автоматически стек технологий.
_ALIASES = {
    "drf": "django rest framework",
    "django-rest-framework": "django rest framework",
    "postgres": "postgresql",
    "postgresql": "postgresql",
    "restful api": "rest api",
}


class MatchError(ValueError):
    """Ошибка структуры извлечённых фактов."""


def _text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return unicodedata.normalize("NFKC", value).strip()


def _key(value: Any) -> str:
    normalized = " ".join(_text(value).casefold().split())
    return _ALIASES.get(normalized, normalized)


def _forms(value: str) -> set[str]:
    """Варианты написания, которые должны встречаться в подтверждающей цитате."""
    canonical = _key(value)
    if not canonical:
        return set()
    result = {canonical, " ".join(_text(value).casefold().split())}
    result.update(alias for alias, target in _ALIASES.items() if target == canonical)
    return result


def _mentions_skill(quote: str, skill: str) -> bool:
    """Защита от очевидного случая: цитата настоящая, а навык придуманный."""
    source = unicodedata.normalize("NFKC", quote).casefold()
    for form in _forms(skill):
        # Не засчитываем Go внутри Django или SQL внутри PostgreSQL.
        pattern = r"(?<!\w)" + re.escape(form) + r"(?!\w)"
        if re.search(pattern, source, flags=re.IGNORECASE):
            return True
    return False


# Названия навыков, записанные явным перечислением в одной строке резюме.
# Ограничиваемся только разделом skills и ранее проверенными цитатами:
# произвольные фразы вроде «не работал с RAG» не должны становиться навыком.
_SKILL_LIST_HEADER = re.compile(
    r"^(?:навыки|технологии|технический стек|стек|skills|tech stack)\s*:\s*",
    flags=re.IGNORECASE,
)
_SKILL_TOKEN = re.compile(r"^[\w+#./-]+(?:\s+[\w+#./-]+){0,3}$", flags=re.UNICODE)
_NEGATION = re.compile(r"(?<!\w)(?:не|нет|без|no|not|never)(?!\w)", flags=re.IGNORECASE)


def _explicit_list_items(quote: str) -> set[str]:
    """Достаём *только явное перечисление* навыков из короткой цитаты.

    Например, «RAG, FAISS, LangChain» -> {rag, faiss, langchain}.
    Не извлекаем навыки из связного текста: его проверит LLM/человек.
    """
    text = _text(quote)
    text = _SKILL_LIST_HEADER.sub("", text).strip()
    if _NEGATION.search(text):
        return set()
    # Строгое разделение запятыми или точкой с запятой: один элемент = один навык.
    chunks = [part.strip().rstrip(".").strip() for part in re.split(r"[,;]", text)]
    if not 2 <= len(chunks) <= 30:
        return set()
    if any(not chunk or len(chunk) > 60 or not _SKILL_TOKEN.fullmatch(chunk)
           for chunk in chunks):
        return set()
    return {_key(chunk) for chunk in chunks}


def _resume_skill_index(skills: list[dict[str, Any]]):
    """Вернём факты по точному имени и явно указанным в их цитатах навыкам.

    У LLM бывает пропуск: value='FAISS', source_text='RAG, FAISS, ...'.
    Если эта цитата уже подтверждена парсером, RAG не требует повторного LLM.
    """
    index: dict[str, dict[str, Any]] = {}
    recovered: set[str] = set()
    for fact in skills:
        if not _usable(fact):
            continue
        index[_key(fact["value"])] = fact
    for fact in skills:
        if not _usable(fact):
            continue
        for skill in _explicit_list_items(fact["source_text"]):
            if skill not in index:
                index[skill] = fact
                recovered.add(skill)
    return index, recovered


def _facts(document: dict[str, Any], category: str) -> list[dict[str, Any]]:
    fields = document.get("fields", {})
    if not isinstance(fields, dict):
        raise MatchError("В JSON отсутствует корректный объект fields")
    items = fields.get(category, [])
    if not isinstance(items, list):
        raise MatchError(f"Категория {category} должна содержать список")
    return [fact for fact in items if isinstance(fact, dict)]


def _usable(fact: dict[str, Any]) -> bool:
    value = _text(fact.get("value"))
    quote = _text(fact.get("source_text"))
    return (
        fact.get("source_verified") is True
        and bool(value)
        and bool(quote)
        and _mentions_skill(quote, value)
    )


def _deduplicate(facts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Один навык — одно требование; выбираем подтверждённое упоминание."""
    by_key: dict[str, dict[str, Any]] = {}
    for fact in facts:
        skill = _key(fact.get("value"))
        if not skill:
            continue
        if skill not in by_key or (_usable(fact) and not _usable(by_key[skill])):
            by_key[skill] = fact
    return list(by_key.values())


def _skill_row(required: dict[str, Any], resume_index: dict[str, dict[str, Any]],
               *, optional: bool, recovered: set[str]) -> dict[str, Any]:
    requirement = _text(required.get("value"))
    normalized = _key(requirement)
    valid = _usable(required)
    evidence = resume_index.get(normalized) if valid else None
    from_list = evidence is not None and normalized in recovered

    if not valid:
        status = "manual_review"
    elif evidence:
        status = "matched"
    else:
        status = "not_confirmed"

    return {
        "requirement": requirement,
        "category": "optional_skill" if optional else "required_skill",
        "status": status,
        "match_method": (
            "literal_in_verified_skill_list" if from_list else
            "exact_or_known_alias" if evidence else None
        ),
        "vacancy_source_text": _text(required.get("source_text")),
        "vacancy_source_verified": required.get("source_verified") is True,
        "vacancy_source_field": required.get("source_field"),
        "vacancy_page": required.get("page"),
        "resume_source_text": _text(evidence.get("source_text")) if evidence else None,
        "resume_source_field": evidence.get("source_field") if evidence else None,
        "resume_page": evidence.get("page") if evidence else None,
        "note": (
            "Проверить извлечённое требование или его цитату вручную"
            if not valid else
            "В подтверждённых фактах резюме навык не найден"
            if not evidence else
            "Название навыка явно перечислено в ранее проверенной цитате раздела skills; "
            "LLM не выделила его отдельным фактом; опыт применения не проверен"
            if from_list else
            "Название навыка совпало буквально или по явному синониму; опыт применения не проверен"
        ),
    }


def match_extractions(resume: dict[str, Any], vacancy: dict[str, Any]) -> dict[str, Any]:
    """Сопоставить два JSON, полученных через /api/llm/resume и /api/llm/vacancy.

    Процент считается только для обязательных атомарных навыков. Если есть
    неподтверждённые обязательные требования, общий процент не публикуем.
    Флаги source_verified получены от upstream-парсера, они не перепроверяются
    по исходным документам в этом отдельном HTTP-запросе.
    """
    if not isinstance(resume, dict) or not isinstance(vacancy, dict):
        raise MatchError("Ожидались объекты JSON резюме и вакансии")

    # Даже при совпадении по названию не используем факт без проверенной цитаты.
    resume_skills = _deduplicate(_facts(resume, "skills"))
    resume_index, recovered = _resume_skill_index(resume_skills)

    required = _deduplicate(_facts(vacancy, "required_skills"))
    required_keys = {_key(f["value"]) for f in required}
    optional = [f for f in _deduplicate(_facts(vacancy, "optional_skills"))
                if _key(f["value"]) not in required_keys]

    required_rows = [_skill_row(f, resume_index, optional=False, recovered=recovered) for f in required]
    optional_rows = [_skill_row(f, resume_index, optional=True, recovered=recovered) for f in optional]

    invalid = sum(row["status"] == "manual_review" for row in required_rows)
    matched = sum(row["status"] == "matched" for row in required_rows)
    verified_total = len(required_rows) - invalid
    # Не показываем ложные 100% при недостоверных требованиях.
    score = (round(100 * matched / verified_total)
             if verified_total and not invalid else None)

    return {
        "score_percent": score,
        "required_matched": matched,
        "required_total": len(required_rows),
        "required_verified_total": verified_total,
        "required_review_total": invalid,
        "optional_matched": sum(row["status"] == "matched" for row in optional_rows),
        "optional_total": len(optional_rows),
        "recovered_explicit_skills": [r["requirement"] for r in (required_rows + optional_rows)
                                      if r["match_method"] == "literal_in_verified_skill_list"],
        "required_matrix": required_rows,
        "optional_matrix": optional_rows,
        "not_scored": {
            "experience": _facts(vacancy, "experience"),
            "responsibilities": _facts(vacancy, "responsibilities"),
            "conditions": _facts(vacancy, "conditions"),
        },
        "method": "literal_or_explicit_alias_only",
        "disclaimer": (
            "Процент — доля подтверждённых по названию обязательных навыков, "
            "а не вероятность трудоустройства. Стаж, уровень владения и контекст "
            "проектов не оценены. source_verified поступает из этапа LLM-извлечения; "
            "этот endpoint не сверяет цитаты повторно с исходными файлами. "
            "Не найдено в резюме не означает отсутствует у кандидата."
        ),
    }
