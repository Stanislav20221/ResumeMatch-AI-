"""Локальные проверки доказательной матрицы; без OpenAI и сетевых запросов."""
from __future__ import annotations

from datetime import date

from fastapi.testclient import TestClient

from app.documents import extract_document
from app.evidence_matrix import build_evidence_matrix
from app.evidence_matrix_api import router
from fastapi import FastAPI

RESUME = '''Backend-разработчик
01.2022 — 05.2025
Разрабатывал REST API на Python, FastAPI и PostgreSQL.
AI-разработчик
09.2024 — 10.2026
Интегрировал LLM через OpenAI API в backend-сервисы.
Навыки: Python, FastAPI, Docker.
Нет опыта работы с Kubernetes.
'''

VACANCY = {
    'description_text': '''Опыт разработки на Python от 3 лет.
Опыт работы с FastAPI от 2 лет.
Разрабатывать REST API.
Интегрировать LLM в backend-сервисы.''',
    'key_skills': ['Python', 'FastAPI', 'Kubernetes'],
}


def fact(value, quote, valid=True):
    return {'value': value, 'source_text': quote, 'source_verified': valid, 'page': 999}


def fixture():
    resume = {'fields': {
        'skills': [fact('Python', 'Навыки: Python, FastAPI, Docker.'),
                   fact('FastAPI', 'Навыки: Python, FastAPI, Docker.'),
                   fact('Kubernetes', 'Нет опыта работы с Kubernetes.')],
        'experience': [], 'projects': [], 'education': []
    }}
    vacancy = {'fields': {
        'required_skills': [fact('Python', 'Python'), fact('FastAPI', 'FastAPI'),
                            fact('Kubernetes', 'Kubernetes')],
        'optional_skills': [],
        'experience': [fact('Опыт Python от 3 лет', 'Опыт разработки на Python от 3 лет.'),
                       fact('Опыт FastAPI от 2 лет', 'Опыт работы с FastAPI от 2 лет.')],
        'responsibilities': [fact('Разработка REST API', 'Разрабатывать REST API.'),
                             fact('Интеграция LLM', 'Интегрировать LLM в backend-сервисы.')],
        'conditions': []
    }}
    doc = extract_document('resume.txt', RESUME.encode('utf-8'))
    return doc, resume, vacancy


def experience():
    return {'jobs': [
        {'role': 'Backend-разработчик', 'role_source_text': 'Backend-разработчик',
         'period_source_text': '01.2022 — 05.2025', 'start_month': '2022-01',
         'end_month': '2025-05', 'is_current': False,
         'tasks': [fact('Разработка REST API', 'Разрабатывал REST API на Python, FastAPI и PostgreSQL.')],
         'technologies': [fact('Python', 'Разрабатывал REST API на Python, FastAPI и PostgreSQL.'),
                          fact('FastAPI', 'Разрабатывал REST API на Python, FastAPI и PostgreSQL.')]},
        {'role': 'AI-разработчик', 'role_source_text': 'AI-разработчик',
         'period_source_text': '09.2024 — 10.2026', 'start_month': '2024-09',
         'end_month': '2026-10', 'is_current': False,
         'tasks': [fact('Интеграция LLM', 'Интегрировал LLM через OpenAI API в backend-сервисы.')],
         'technologies': [fact('OpenAI API', 'Интегрировал LLM через OpenAI API в backend-сервисы.')]}
    ], 'responsibility_reviews': [
        {'requirement': 'Разработка REST API', 'vacancy_source_text': 'Разрабатывать REST API.',
         'verdict': 'supported', 'evidence': [{'quote': 'Разрабатывал REST API на Python, FastAPI и PostgreSQL.'}]},
        {'requirement': 'Интеграция LLM', 'vacancy_source_text': 'Интегрировать LLM в backend-сервисы.',
         'verdict': 'supported', 'evidence': [{'quote': 'Интегрировал LLM через OpenAI API в backend-сервисы.'}]}
    ]}


def matrix(**kwargs):
    doc, resume, vacancy = fixture()
    return build_evidence_matrix(doc, VACANCY, resume, vacancy, today=date(2026, 11, 23), **kwargs)


def by_category(result, category):
    return [r for r in result['rows'] if r['category'] == category]


def test_no_extra_calls_or_experience_guesses():
    result = matrix()
    skills = by_category(result, 'required_skill')
    assert [r['status'] for r in skills] == ['exact_mention', 'exact_mention', 'not_confirmed']
    assert result['summary']['literal_skill_score_percent'] == 67
    assert all(r['status'] == 'not_run' for r in by_category(result, 'experience'))
    assert all(r['status'] == 'not_run' for r in by_category(result, 'responsibility'))
    assert all(r['human_review_required'] for r in result['rows'])


def test_duration_recalculated_and_duties_are_only_proposals():
    result = matrix(experience_result=experience())
    durations = by_category(result, 'experience')
    assert [r['status'] for r in durations] == ['duration_provisional', 'duration_provisional']
    assert [r['documented_months'] for r in durations] == [40, 40]
    assert [r['required_months'] for r in durations] == [36, 24]
    assert len(durations[0]['resume_evidence']) >= 3
    assert all(r['status'] == 'semantic_proposal' for r in by_category(result, 'responsibility'))
    assert result['summary']['literal_skill_score_percent'] == 67


def test_tampered_dates_not_trusted():
    changed = experience()
    changed['jobs'][0]['start_month'] = '2020-01'
    changed['jobs'][1]['start_month'] = '2020-01'
    result = matrix(experience_result=changed)
    assert all(r['status'] == 'insufficient_evidence' for r in by_category(result, 'experience'))


def test_source_flag_cannot_forge_quote():
    doc, resume, vacancy = fixture()
    resume['fields']['skills'][0] = fact('Python', 'Фальшивая цитата Python')
    resume['fields']['skills'][1] = fact('FastAPI', 'Разрабатывал REST API на Python, FastAPI и PostgreSQL.')
    vacancy['fields']['required_skills'][1] = fact('FastAPI', 'Несуществующее требование FastAPI')
    result = build_evidence_matrix(doc, VACANCY, resume, vacancy)
    skills = by_category(result, 'required_skill')
    assert skills[0]['status'] == 'not_confirmed'
    assert skills[1]['status'] == 'invalid_source'
    assert result['summary']['literal_skill_score_percent'] is None
    assert result['summary']['sources_revalidated'] is True


def test_semantic_proposal_needs_verified_resume_evidence():
    sem = {'required_matrix': [
        {'requirement': 'Kubernetes', 'vacancy_source_text': 'Kubernetes',
         'status': 'semantic_suggestion', 'semantic_evidence': [{'quote': 'Несуществующая технология'}]}]}
    assert by_category(matrix(semantic_result=sem), 'required_skill')[2]['status'] == 'not_confirmed'
    sem['required_matrix'][0]['semantic_evidence'] = [{'quote': 'Нет опыта работы с Kubernetes.'}]
    assert by_category(matrix(semantic_result=sem), 'required_skill')[2]['status'] == 'not_confirmed'
    sem['required_matrix'][0]['semantic_evidence'] = [{'quote': 'Интегрировал LLM через OpenAI API в backend-сервисы.'}]
    output = matrix(semantic_result=sem)
    assert by_category(output, 'required_skill')[2]['status'] == 'semantic_proposal'
    assert output['summary']['literal_skill_score_percent'] == 67
    assert output['summary']['proposals_for_review'] == 1


def test_rag_cannot_relabel_a_vacancy_quote_as_resume():
    rag = {'claims': [
        {'statement': 'Есть опыт Kubernetes.', 'citations': [
            {'document_type': 'resume', 'quote': 'Kubernetes'},
            {'document_type': 'vacancy', 'quote': 'Опыт работы с FastAPI от 2 лет.'}]},
        {'statement': 'Нет резюме', 'citations': [
            {'document_type': 'resume', 'quote': 'Невозможная цитата'}]},
    ]}
    result = matrix(rag_result=rag)
    assert len(result['rag_observations']) == 1
    assert result['rag_observations'][0]['affects_score'] is False
    assert result['summary']['literal_skill_score_percent'] == 67


def test_resume_line_with_negative_skill_is_not_accepted():
    assert by_category(matrix(), 'required_skill')[2]['status'] == 'not_confirmed'


def test_local_api_multipart_and_validation():
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    doc, resume, vacancy = fixture()
    import json
    fields = {'resume_extraction': json.dumps(resume), 'vacancy_extraction': json.dumps(vacancy),
              'vacancy_source': json.dumps(VACANCY)}
    response = client.post('/api/evidence/matrix', data=fields,
                           files={'resume': ('resume.txt', RESUME.encode('utf-8'), 'text/plain')})
    assert response.status_code == 200, response.text
    assert response.headers['cache-control'] == 'no-store'
    assert response.json()['summary']['literal_skill_score_percent'] == 67
    fields['vacancy_source'] = 'NOT_JSON'
    response = client.post('/api/evidence/matrix', data=fields,
                           files={'resume': ('resume.txt', RESUME.encode('utf-8'), 'text/plain')})
    assert response.status_code == 422
    assert RESUME not in response.text
