"""v0.8: отчёты из локально пересчитанной матрицы; без OpenAI/сети."""
from __future__ import annotations

import json
from datetime import date

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.documents import extract_document
from app.evidence_matrix import build_evidence_matrix
from app.report_v08 import ReportError, compose_report, render_pdf
from app.report_v08_api import router

RESUME = '''Backend-разработчик
01.2022 — 05.2025
Разрабатывал REST API на Python и FastAPI.
AI-разработчик
09.2024 — 10.2026
Интегрировал LLM через OpenAI API.
Навыки: Python, FastAPI.
Нет опыта работы с Kubernetes.
'''
VAC = {
    'description_text': 'Опыт Python от 3 лет.\nРазрабатывать REST API.\nОпыт FastAPI от 2 лет.',
    'key_skills': ['Python', 'FastAPI', 'Kubernetes'],
}


def fact(value, quote):
    return {'value': value, 'source_text': quote, 'source_verified': True}


def parts():
    resume = {'fields': {'skills': [fact('Python', 'Навыки: Python, FastAPI.'),
                                    fact('FastAPI', 'Навыки: Python, FastAPI.'),
                                    fact('Kubernetes', 'Нет опыта работы с Kubernetes.')],
                         'experience': [], 'projects': [], 'education': []}}
    vacancy = {'fields': {
        'required_skills': [fact('Python', 'Python'), fact('FastAPI', 'FastAPI'),
                            fact('Kubernetes', 'Kubernetes')],
        'optional_skills': [],
        'experience': [fact('Опыт Python от 3 лет', 'Опыт Python от 3 лет.'),
                       fact('Опыт FastAPI от 2 лет', 'Опыт FastAPI от 2 лет.')],
        'responsibilities': [fact('Разработка REST API', 'Разрабатывать REST API.')],
        'conditions': []}}
    return resume, vacancy


def evidence_matrix(**extra):
    resume, vacancy = parts()
    doc = extract_document('demo.txt', RESUME.encode('utf-8'))
    return build_evidence_matrix(doc, VAC, resume, vacancy, today=date(2026, 11, 23), **extra)


def example_report(**extra):
    return compose_report(evidence_matrix(**extra), vacancy_title='Python-разработчик',
                          candidate_label='Кандидат № 1', today=date(2026, 11, 23))


def client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def form():
    resume, vacancy = parts()
    return {
        'resume_extraction': json.dumps(resume),
        'vacancy_extraction': json.dumps(vacancy),
        'vacancy_source': json.dumps(VAC),
        'vacancy_title': 'Python-разработчик',
        'candidate_label': 'Кандидат № 1',
    }


def upload():
    return {'resume': ('demo.txt', RESUME.encode('utf-8'), 'text/plain')}


def test_report_counts_and_neutral_conclusion():
    report = example_report()
    o = report['overview']
    assert o['required_skills'] == 3
    assert o['literal_mentions'] == 2
    assert o['literal_mention_percent'] == 67
    assert o['pending_checks'] == 3
    assert 'решение' in ' '.join(report['conclusion']).lower()
    assert all(row['category'] in ('required_skill', 'optional_skill', 'experience', 'responsibility')
               for row in report['rows'])
    assert report['candidate_label'] == 'Кандидат № 1'


def test_no_skill_inference_from_negative_mention():
    report = example_report()
    kub = next(r for r in report['rows'] if r['requirement'] == 'Kubernetes')
    assert kub['status'] == 'not_confirmed'
    assert not kub['resume_quotes']


def test_requires_revalidated_matrix():
    with pytest.raises(ReportError):
        compose_report({'version': '0.3', 'rows': []})
    with pytest.raises(ReportError):
        compose_report({'version': '0.7', 'rows': [{'category': 'other', 'status': 'fake'}]})


def test_strips_unverified_quote_in_report_even_after_tampering():
    matrix = evidence_matrix()
    target = matrix['rows'][0]
    target['resume_evidence'] = [{'quote': 'выдумано', 'source_verified': False}]
    report = compose_report(matrix)
    assert report['rows'][0]['status'] == 'insufficient_evidence'
    assert report['overview']['literal_mentions'] == 1


def test_report_does_not_trust_bad_vacancy_quote():
    matrix = evidence_matrix()
    matrix['rows'][0]['vacancy_evidence'] = None
    report = compose_report(matrix)
    assert report['rows'][0]['status'] == 'invalid_source'
    assert report['overview']['literal_mention_percent'] is None


def test_pdf_cyrillic_and_multi_pages():
    pymupdf = pytest.importorskip('pymupdf')
    report = example_report()
    pdf = render_pdf(report)
    assert pdf.startswith(b'%PDF-')
    with pymupdf.open(stream=pdf, filetype='pdf') as doc:
        text = '\n'.join(page.get_text() for page in doc)
        assert 'ResumeMatch AI' in text
        assert 'Обязательные навыки' in text
        assert 'Кандидат № 1' in text
        assert 'Цитата резюме' in text
        assert 'Ручная проверка' in text or 'проверки' in text


def test_pdf_long_quotes_and_html_escape():
    pymupdf = pytest.importorskip('pymupdf')
    matrix = evidence_matrix()
    matrix['rows'][0]['detail'] = '<script>alert(123)</script> & ' + 'очень длинное описание ' * 60
    pdf = render_pdf(compose_report(matrix))
    with pymupdf.open(stream=pdf, filetype='pdf') as doc:
        txt = ' '.join(p.get_text() for p in doc)
        assert '<script>' in txt  # литерал, не выполняемый HTML
        assert 'длинное описание' in txt


def test_preview_api_multipart_and_no_store():
    reply = client().post('/api/report/preview', data=form(), files=upload())
    assert reply.status_code == 200, reply.text
    assert reply.headers['Cache-Control'] == 'no-store'
    assert reply.headers['X-Content-Type-Options'] == 'nosniff'
    assert reply.json()['overview']['literal_mentions'] == 2
    assert reply.json()['candidate_label'] == 'Кандидат № 1'


def test_pdf_api_real_download():
    reply = client().post('/api/report/pdf', data=form(), files=upload())
    assert reply.status_code == 200, reply.text[:300]
    assert reply.content.startswith(b'%PDF-')
    assert reply.headers['Cache-Control'] == 'no-store'
    assert reply.headers['Content-Disposition'].startswith('attachment;')
    assert 'application/pdf' in reply.headers['content-type']


def test_api_rechecks_quotes_and_does_not_trust_client_flags():
    data = form()
    resume, _ = parts()
    resume['fields']['skills'][0] = fact('Python', 'несуществующая цитата Python')
    # Иначе v0.7 законно восстановит Python из второй общей цитаты навыков.
    resume['fields']['skills'][1] = fact('FastAPI', 'FastAPI.')
    data['resume_extraction'] = json.dumps(resume)
    reply = client().post('/api/report/preview', data=data, files=upload())
    assert reply.status_code == 200
    assert reply.json()['overview']['literal_mentions'] == 1


def test_api_validates_input_and_never_echoes_cv_in_error():
    data = form()
    data['vacancy_source'] = '!!!'
    reply = client().post('/api/report/preview', data=data, files=upload())
    assert reply.status_code == 422
    assert RESUME not in reply.text
    data = form()
    data['candidate_label'] = 'x'*241
    reply = client().post('/api/report/pdf', data=data, files=upload())
    assert reply.status_code == 422


def test_api_wont_accept_only_client_side_matrix():
    reply = client().post('/api/report/preview', json={'version':'0.7', 'rows':[]})
    assert reply.status_code == 422


def test_many_requirements_produce_multipage_pdf():
    pymupdf = pytest.importorskip('pymupdf')
    matrix = evidence_matrix()
    first = dict(matrix['rows'][0])
    matrix['rows'].extend(dict(first, id=f'synthetic{i:03d}', requirement='Очень длинное требование ' + str(i))
                          for i in range(55))
    with pymupdf.open(stream=render_pdf(compose_report(matrix)), filetype='pdf') as doc:
        assert len(doc) >= 4
