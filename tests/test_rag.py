"""Offline RAG tests: fake embeddings/FAISS/LLM, no keys or paid API calls."""
from __future__ import annotations

import asyncio
import sys
import types
from types import SimpleNamespace

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import rag
from app.rag_api import router


def resume_doc():
    return {"blocks": [
        {"source_text": "Backend-разработчик, опыт с Python и FastAPI.", "page": 1},
        {"source_text": "Разрабатывал REST API на FastAPI и PostgreSQL.", "page": 1},
        {"source_text": "Контакт: вымышленный кандидат", "page": 2},
    ]}


def vacancy_doc():
    return {"description_text": "Опыт работы с Python от 3 лет.\nТребуется FastAPI и REST API.",
            "key_skills": ["Python", "FastAPI"]}


class FakeFaissIndex:
    def __init__(self, dim):
        self.dim = dim
        self.data = None

    def add(self, data):
        assert data.dtype == np.float32 and data.shape[1] == self.dim
        self.data = data

    def search(self, query, count):
        dot = (self.data @ query[0]).astype(np.float32)
        ids = np.argsort(-dot).astype(np.int64)[:count]
        return np.array([dot[ids]], dtype=np.float32), np.array([ids], dtype=np.int64)


class FakeOpenAI:
    def __init__(self):
        self.embeddings = self
        self.responses = self
        self.parsed = None
        self.calls = []

    async def create(self, *, model, input, encoding_format):
        assert model == rag.EMBEDDING_MODEL
        assert encoding_format == 'float'
        self.calls.append(('embeddings', len(input)))
        vectors = []
        for idx, content in enumerate(input):
            lower = content.lower()
            vectors.append(SimpleNamespace(index=idx, embedding=[
                1 + float('fastapi' in lower),
                1 + float('python' in lower),
                1 + float('rest api' in lower),
            ]))
        return SimpleNamespace(data=vectors)

    async def parse(self, **kwargs):
        assert kwargs['store'] is False
        assert kwargs['text_format'] is rag.GroundedAnswer
        self.calls.append(('responses', 1))
        return SimpleNamespace(output_parsed=self.parsed)



@pytest.fixture
def env(monkeypatch):
    monkeypatch.setitem(sys.modules, 'faiss', types.SimpleNamespace(IndexFlatIP=FakeFaissIndex))
    monkeypatch.setenv('OPENAI_API_KEY', 'fake-test-key')
    monkeypatch.setenv('OPENAI_MODEL', 'gpt-4.1-mini')
    monkeypatch.setattr(rag, 'SESSIONS', rag.MemoryIndexes())
    return FakeOpenAI()


def test_chunk_sources_and_metadata():
    chunks = rag.chunk_documents(resume_doc(), vacancy_doc())
    assert {c.document_type for c in chunks} == {'resume', 'vacancy'}
    assert any(c.page == 1 and 'FastAPI' in c.text for c in chunks)
    assert any(c.source_field == 'key_skills' for c in chunks)
    assert len({c.chunk_id for c in chunks}) == len(chunks)


def test_no_silent_loss_when_document_too_big():
    very_long = {"blocks": [{"source_text": 'x' * (rag.MAX_SOURCE_CHARS + 1)}]}
    with pytest.raises(rag.RagError):
        rag.chunk_documents(very_long, vacancy_doc())


def test_verbatim_quote_must_exist_in_original_line():
    chunks = rag.chunk_documents(resume_doc(), vacancy_doc())
    assert any('Python' in line for c in chunks for line in c.original_lines)
    assert not any('Kubernetes' in line for c in chunks for line in c.original_lines)


def test_vectors_normalized_and_invalid_rejected():
    matrix = rag._matrix([[3.0, 4.0], [1.0, 0.0]], 2)
    assert np.allclose(np.linalg.norm(matrix, axis=1), 1)
    with pytest.raises(rag.RagUpstreamError):
        rag._matrix([[float('nan'), 2]], 1)
    with pytest.raises(rag.RagUpstreamError):
        rag._matrix([[0, 0]], 1)


def test_index_search_retrieve_both_sources_and_delete(env):
    async def run():
        created = await rag.make_index(resume_doc(), vacancy_doc(), client=env)
        assert created['vector_dimensions'] == 3
        assert created['chunks_total'] >= 2
        results = await rag.retrieve(created['session_id'], 'FastAPI REST API', top_k=4, client=env)
        assert {x['document_type'] for x in results} == {'resume', 'vacancy'}
        assert all(x['chunk_id'] and -1 <= x['similarity'] <= 1.001 for x in results)
        rag.SESSIONS.delete(created['session_id'])
        with pytest.raises(rag.RagError):
            rag.SESSIONS.get(created['session_id'])
    asyncio.run(run())


def test_invalid_citation_dropped_and_supported_citation_returned(env):
    async def run():
        created = await rag.make_index(resume_doc(), vacancy_doc(), client=env)
        hits = await rag.retrieve(created['session_id'], 'FastAPI', client=env)
        resume_hit = next(hit for hit in hits if hit['document_type'] == 'resume')
        quote = 'FastAPI'
        env.parsed = rag.GroundedAnswer(claims=[
            rag.GroundedClaim(statement='Кандидат использовал FastAPI.',
                citations=[rag.Citation(chunk_id=resume_hit['chunk_id'], quote=quote)]),
            rag.GroundedClaim(statement='Кандидат владеет Kubernetes.',
                citations=[rag.Citation(chunk_id=resume_hit['chunk_id'], quote='Kubernetes')]),
            rag.GroundedClaim(statement='Подтверждение несуществующим ID.',
                citations=[rag.Citation(chunk_id='invented', quote=quote)]),
        ])
        result = await rag.answer_question(created['session_id'], 'Что известно о FastAPI?', client=env)
        assert result['answer'] == 'Кандидат использовал FastAPI.'
        assert len(result['claims']) == 1
        assert result['claims'][0]['citations'][0]['quote'] == quote
    asyncio.run(run())


def test_llm_insufficient_evidence_never_fabricates(env):
    async def run():
        created = await rag.make_index(resume_doc(), vacancy_doc(), client=env)
        env.parsed = rag.GroundedAnswer(
            claims=[rag.GroundedClaim(statement='Непроверенный вывод', citations=[])],
            insufficient_evidence=True)
        result = await rag.answer_question(created['session_id'], 'Есть ли Kubernetes?', client=env)
        assert result['claims'] == []
        assert 'Недостаточно' in result['answer']
    asyncio.run(run())


def test_sessions_expire_without_disk(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(rag.time, 'monotonic', lambda: now[0])
    store = rag.MemoryIndexes()
    session = rag.RagSession(chunks=[], index=None, dimensions=3, created_at=now[0])
    token = store.put(session)
    assert store.get(token) is session
    now[0] += rag.SESSION_TTL_SECONDS + 1
    with pytest.raises(rag.RagError):
        store.get(token)


def test_api_requires_consent_before_handling_documents(monkeypatch):
    app = FastAPI()
    app.include_router(router)
    test_client = TestClient(app)
    response = test_client.post('/api/rag/index', files={'resume': ('test.txt', b'Python')},
        data={'vacancy_description': 'FastAPI', 'cloud_consent': 'false'})
    assert response.status_code == 422
    assert 'согласие' in response.json()['detail']
    query = test_client.post('/api/rag/search', json={'session_id': 'a'*25, 'question': 'FastAPI', 'cloud_consent': False})
    assert query.status_code == 422


def test_api_with_fake_embedding_no_paid_request(monkeypatch, env):
    import app.rag_api as api
    async def fake_make_index(doc, vac):
        assert doc['blocks'][0]['source_text'] == 'Python и FastAPI'
        assert vac['description_text'] == 'Требуется FastAPI'
        return {'session_id': 'test-token'}
    monkeypatch.setattr(api, 'make_index', fake_make_index)
    app = FastAPI()
    app.include_router(router)
    response = TestClient(app).post('/api/rag/index',
        files={'resume': ('cv.txt', 'Python и FastAPI'.encode('utf-8'))},
        data={'vacancy_description': 'Требуется FastAPI', 'vacancy_key_skills': '["FastAPI"]',
              'cloud_consent': 'true'})
    assert response.status_code == 200
    assert response.json()['session_id'] == 'test-token'
    assert response.headers['cache-control'] == 'no-store'
