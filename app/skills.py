"""Conservative local skill vocabulary. These are labels, not a trained entity extractor.

Never infer experience from a related technology: match only explicit skill mentions.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


SKILL_ALIASES: dict[str, tuple[str, ...]] = {
    "Python": ("python", "питон"),
    "Django": ("django", "джанго"),
    "Django REST Framework": ("django rest framework", "drf"),
    "FastAPI": ("fastapi",),
    "Flask": ("flask",),
    "REST API": ("rest api", "restful api", "rest-апи", "rest-ful"),
    "PostgreSQL": ("postgresql", "postgres", "постгрес"),
    "SQL": ("sql",),
    "SQLite": ("sqlite",),
    "MySQL": ("mysql",),
    "Redis": ("redis",),
    "Docker": ("docker", "докер"),
    "Docker Compose": ("docker compose", "docker-compose"),
    "Kubernetes": ("kubernetes", "k8s"),
    "Git": ("git",),
    "GitHub Actions": ("github actions",),
    "Linux": ("linux", "линукс"),
    "Nginx": ("nginx",),
    "Pandas": ("pandas",),
    "NumPy": ("numpy",),
    "PyTorch": ("pytorch",),
    "TensorFlow": ("tensorflow",),
    "Scikit-learn": ("scikit-learn", "sklearn"),
    "LLM": ("llm", "large language models", "языковые модели"),
    "RAG": ("rag", "retrieval augmented generation", "retrieval-augmented generation"),
    "FAISS": ("faiss",),
    "LangChain": ("langchain",),
    "OpenAI API": ("openai api", "api openai"),
    "Embeddings": ("embeddings", "эмбеддинги", "векторные представления"),
    "OCR": ("ocr", "распознавание текста"),
    "Tesseract": ("tesseract",),
    "PaddleOCR": ("paddleocr", "paddle ocr"),
    "Docling": ("docling",),
    "PDF": ("pdf",),
    "DOCX": ("docx",),
    "MCP": ("mcp", "model context protocol"),
    "pgvector": ("pgvector",),
    "Celery": ("celery",),
    "RabbitMQ": ("rabbitmq",),
    "Apache Kafka": ("apache kafka", "kafka"),
    "JavaScript": ("javascript", "js"),
    "TypeScript": ("typescript", "ts"),
    "React": ("react", "reactjs"),
    "Next.js": ("next.js", "nextjs"),
    "HTML": ("html",),
    "CSS": ("css",),
    "AWS": ("aws", "amazon web services"),
    "Azure": ("azure",),
    "CI/CD": ("ci/cd", "cicd"),
    "pytest": ("pytest",),
    "Unit testing": ("unit testing", "модульное тестирование", "юнит-тесты"),
}


@dataclass(frozen=True)
class SkillHit:
    name: str
    matched_text: str
    alias: bool


def _rx(alias: str) -> re.Pattern[str]:
    """Avoid partial hits: 'git' should not match 'digital'."""
    return re.compile(r"(?<![\w])" + re.escape(alias).replace(r"\ ", r"\s+") + r"(?![\w])", re.IGNORECASE)


PATTERNS = {name: [(a, _rx(a)) for a in aliases] for name, aliases in SKILL_ALIASES.items()}


def find_skills(text: str) -> list[SkillHit]:
    found: list[SkillHit] = []
    for name, patterns in PATTERNS.items():
        for alias, pattern in patterns:
            match = pattern.search(text)
            if match:
                found.append(SkillHit(name=name, matched_text=match.group(0), alias=alias.casefold() != name.casefold()))
                break
    return found
