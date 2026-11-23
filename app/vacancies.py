"""HH API adapter, vacancy-to-JSON normalization, and source-grounded requirements."""
from __future__ import annotations

import html
import os
import re
from typing import Any

import httpx
from bs4 import BeautifulSoup

from .skills import find_skills

HH_BASE = "https://api.hh.ru"


class VacancyError(ValueError):
    pass


def html_to_text(raw: str) -> str:
    soup = BeautifulSoup(raw or "", "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    for tag in soup.find_all(["br", "p", "li", "h2", "h3"]):
        # Preserve paragraph separation for evidence snippets.
        tag.insert_before("\n")
    text = soup.get_text(" ", strip=False)
    return "\n".join(re.sub(r"\s+", " ", html.unescape(line)).strip()
                     for line in text.splitlines() if line.strip())


def _requirements_from_source(description: str, listed_skills: list[str]) -> list[dict[str, str]]:
    requirements: dict[str, dict[str, str]] = {}
    for raw in listed_skills:
        for hit in find_skills(raw):
            requirements.setdefault(hit.name, {"skill": hit.name, "source_text": raw, "source_field": "key_skills"})
    for line in description.splitlines():
        for hit in find_skills(line):
            requirements.setdefault(hit.name, {"skill": hit.name, "source_text": line, "source_field": "description"})
    return sorted(requirements.values(), key=lambda row: row["skill"].casefold())


def _other_requirements(description: str) -> list[str]:
    hints = re.compile(r"\b(требовани|опыт|знани|умени|навык|понимани|владени|обязател|будет плюсом|requirements|experience)\w*", re.I)
    return [line for line in description.splitlines() if hints.search(line)][:18]


def normalize_vacancy(payload: dict[str, Any]) -> dict[str, Any]:
    description = html_to_text(payload.get("description") or "")
    key_skills = [x.get("name", "") for x in payload.get("key_skills") or [] if x.get("name")]
    return {
        "id": str(payload.get("id", "")),
        "name": payload.get("name") or "Без названия",
        "employer": (payload.get("employer") or {}).get("name") or "Не указан",
        "url": payload.get("alternate_url") or (f"https://hh.ru/vacancy/{payload.get('id')}" if str(payload.get("id", "")).isdigit() else ""),
        "experience": (payload.get("experience") or {}).get("name"),
        "salary": payload.get("salary"),
        "description_text": description,
        "key_skills": key_skills,
        "requirements": _requirements_from_source(description, key_skills),
        "other_requirements_for_review": _other_requirements(description),
        "extraction_method": "hh_api_fields_plus_local_keyword_aliases",
    }


async def search_hh(query: str, count: int, area: str | None = None) -> list[dict[str, Any]]:
    user_agent = os.getenv("HH_USER_AGENT", "").strip()
    if not user_agent or "example.com" in user_agent:
        raise VacancyError("Для поиска через hh.ru задайте HH_USER_AGENT с реальным email разработчика. См. README.md")
    headers = {"User-Agent": user_agent, "Accept": "application/json"}
    params: dict[str, Any] = {"text": query, "per_page": count, "page": 0}
    if area:
        params["area"] = area
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(15), headers=headers, follow_redirects=False) as client:
            response = await client.get(f"{HH_BASE}/vacancies", params=params)
            _check_response(response)
            items = response.json().get("items", [])
            results = []
            # Sequential requests: conservative on public HH API; cap in API at <= 10.
            for item in items[:count]:
                vacancy_id = item.get("id")
                if not vacancy_id or not str(vacancy_id).isdigit():
                    continue
                try:
                    detail = await client.get(f"{HH_BASE}/vacancies/{vacancy_id}")
                    _check_response(detail)
                    results.append(normalize_vacancy(detail.json()))
                except (httpx.HTTPError, ValueError, VacancyError):
                    # One unavailable vacancy shouldn't prevent processing the rest.
                    continue
            if items and not results:
                raise VacancyError("Вакансии найдены, но подробные описания получить не удалось")
            return results
    except VacancyError:
        raise
    except (httpx.HTTPError, ValueError) as exc:
        raise VacancyError("Ошибка соединения с hh.ru: " + str(exc)) from exc


def _check_response(response: httpx.Response) -> None:
    if response.status_code in (403, 429):
        raise VacancyError("hh.ru ограничил доступ к API (капча, авторизация или лимит запросов). Используйте демо-режим или настройте доступ согласно документации hh.ru")
    if response.status_code >= 400:
        raise VacancyError(f"hh.ru вернул HTTP {response.status_code}")
