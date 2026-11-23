"""Synthetic vacancy fixtures. Never claim these are live hh.ru listings."""
from .vacancies import normalize_vacancy

RAW_DEMO_VACANCIES = [
    {
        "id": "demo-1", "name": "Python / RAG разработчик", "employer": {"name": "Пример: ТехЛаб"},
        "alternate_url": "", "experience": {"name": "1–3 года"},
        "key_skills": [{"name": x} for x in ["Python", "FastAPI", "RAG", "FAISS", "Docker", "PostgreSQL"]],
        "description": "<p>Требования: Python, FastAPI, RAG, FAISS, Docker, PostgreSQL. Плюсом будет опыт построения REST API.</p>",
    },
    {
        "id": "demo-2", "name": "Backend-разработчик Django", "employer": {"name": "Пример: ВебСистемы"},
        "alternate_url": "", "experience": {"name": "1–3 года"},
        "key_skills": [{"name": x} for x in ["Python", "Django", "DRF", "Postgres", "Redis", "Celery"]],
        "description": "<p>Ожидаем знание Django REST Framework, Redis, Celery и PostgreSQL.</p>",
    },
    {
        "id": "demo-3", "name": "ML-инженер", "employer": {"name": "Пример: DataWorks"},
        "alternate_url": "", "experience": {"name": "3–6 лет"},
        "key_skills": [{"name": x} for x in ["Python", "PyTorch", "TensorFlow", "Kubernetes", "SQL"]],
        "description": "<p>Опыт разработки моделей на PyTorch. Работа с Kubernetes и SQL.</p>",
    },
    {
        "id": "demo-4",
        "name": "Python Backend / AI-разработчик — проверка стажа",
        "employer": {"name": "Пример: AI Systems"},
        "alternate_url": "",
        "experience": {"name": "3–6 лет"},
        "key_skills": [
            {"name": name}
            for name in ("Python", "FastAPI", "PostgreSQL", "Docker")
        ],
        "description": (
            "<h3>Требования</h3>"
            "<ul>"
            "<li>Опыт разработки на Python от 3 лет.</li>"
            "<li>Опыт работы с FastAPI от 2 лет.</li>"
            "<li>Знание PostgreSQL и Docker.</li>"
            "</ul>"
            "<h3>Обязанности</h3>"
            "<ul>"
            "<li>Разрабатывать REST API.</li>"
            "<li>Интегрировать LLM в backend-сервисы.</li>"
            "</ul>"
            "<h3>Будет плюсом</h3>"
            "<ul><li>Опыт работы с Kubernetes.</li></ul>"
        ),
    },
]


def demo_vacancies() -> list[dict]:
    return [normalize_vacancy(item) for item in RAW_DEMO_VACANCIES]
