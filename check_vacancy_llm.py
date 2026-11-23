import asyncio
import json

from app.llm import extract_vacancy_json


vacancy = {
    "key_skills": [
        "Python",
        "FastAPI",
        "PostgreSQL"
    ],
    "description_text": """
    Требования:
    Опыт разработки на Python от 2 лет.
    Уверенное владение FastAPI и PostgreSQL.
    Опыт работы с Docker.

    Будет преимуществом:
    Знание LangChain и FAISS.

    Обязанности:
    Разрабатывать REST API.
    Интегрировать LLM в backend-сервисы.

    Условия:
    Удалённая работа.
    Полная занятость.
    """
}


async def main():
    result = await extract_vacancy_json(vacancy)

    print(json.dumps(
        result,
        ensure_ascii=False,
        indent=2
    ))


asyncio.run(main())