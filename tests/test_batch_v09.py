"""v0.9: сравнение документов и API без сетевых/платных вызовов."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.batch_v09 import BatchError, compare_documents
from app.batch_v09_api import router
from app.documents import extract_document

VACANCY = {
    'description_text': 'Нужны Python и FastAPI. Опыт разработки на Python от 3 лет.',
    'key_skills': ['Python', 'FastAPI'],
}
VACANCY_LLM = {'fields': {
    'required_skills': [
        {'value': 'Python', 'source_text': 'Python'},
        {'value': 'FastAPI', 'source_text': 'FastAPI'},
    ],
    'optional_skills': [],
    'experience': [{'value': 'Python от 3 лет', 'source_text': 'Опыт разработки на Python от 3 лет.'}],
    'responsibilities': [], 'conditions': [],
}}


def resume(text):
    return extract_document('demo.txt', text.encode('utf-8'))


def extraction(*facts):
    return {'fields': {'skills': [{'value': x, 'source_text': x} for x in facts],
                       'experience': [], 'education': [], 'projects': []}}


def compare(resumes=None, extracts=None, **kwargs):
    docs = resumes or [resume('Python\nFastAPI'), resume('Python')]
    facts = extracts or [extraction('Python', 'FastAPI'), extraction('Python')]
    return compare_documents(docs, VACANCY, VACANCY_LLM, facts, **kwargs)


def test_two_candidates_have_independent_quotes_and_no_ranking():
    data = compare()
    assert data['version'] == '0.9'
    assert data['candidate_count'] == 2
    assert data['automated_ranking'] is False
    assert data['cloud_calls'] == 0
    assert [x['label'] for x in data['candidates']] == ['Кандидат 1', 'Кандидат 2']
    assert data['candidates'][0]['summary']['required_skills_literal'] == 2
    assert data['candidates'][1]['summary']['required_skills_literal'] == 1
    fastapi = next(x for x in data['comparison'] if x['requirement'] == 'FastAPI')
    assert [x['status'] for x in fastapi['candidates']] == ['exact_mention', 'not_confirmed']
    assert all(row['summary']['sources_revalidated'] for row in data['candidates'])
    assert all(x['human_review_required'] for c in data['candidates'] for x in c['rows'])
    assert all(x['status'] == 'not_run' for c in data['candidates'] for x in c['rows'] if x['category'] == 'experience')


def test_fabricated_citation_is_not_a_skill_proof():
    data = compare(resumes=[resume('Python'), resume('Нет опыта FastAPI')],
                   extracts=[extraction('Python', 'FastAPI'), extraction('FastAPI')])
    assert data['candidates'][0]['summary']['required_skills_literal'] == 1
    assert data['candidates'][1]['summary']['required_skills_literal'] == 0
    rows = data['candidates'][0]['rows']
    assert next(r for r in rows if r['requirement'] == 'FastAPI')['resume_evidence'] == []


def test_short_quote_in_not_listed_context_is_not_proof():
    data = compare(resumes=[resume('Опыт FastAPI не указан'), resume('Python')],
                   extracts=[extraction('FastAPI'), extraction('Python')])
    item = next(r for r in data['candidates'][0]['rows'] if r['requirement'] == 'FastAPI')
    assert item['status'] == 'manual_review'
    assert data['candidates'][0]['summary']['required_skills_literal'] == 0


def test_does_not_reuse_proofs_from_first_candidate():
    data = compare(resumes=[resume('FastAPI'), resume('Docker')],
                   extracts=[extraction('FastAPI'), extraction('FastAPI')])
    assert next(r for r in data['candidates'][1]['rows'] if r['requirement'] == 'FastAPI')['status'] != 'exact_mention'


def test_rejects_six_candidates():
    with pytest.raises(BatchError, match='от 1 до 5'):
        compare_documents([resume('Python')] * 6, VACANCY, VACANCY_LLM,
                          [extraction('Python')] * 6)


def test_rejects_mismatched_extractions():
    with pytest.raises(BatchError, match='resume_extractions'):
        compare_documents([resume('Python'), resume('FastAPI')], VACANCY, VACANCY_LLM,
                          [extraction('Python')])


def test_rejects_fake_experience_payload():
    with pytest.raises(BatchError, match='анализ стажа'):
        compare(experience_results=[None, 'fake'])


def test_rejects_too_long_label():
    with pytest.raises(BatchError, match='подпись'):
        compare(labels=['X' * 90, 'Кандидат 2'])


def test_keeps_upload_order_without_sorting():
    data = compare(resumes=[resume('Docker'), resume('Python\nFastAPI')],
                   extracts=[extraction('Docker'), extraction('Python', 'FastAPI')],
                   labels=['Первый', 'Второй'])
    assert [c['label'] for c in data['candidates']] == ['Первый', 'Второй']
    assert data['candidates'][0]['summary']['required_skills_literal'] == 0
    assert data['candidates'][1]['summary']['required_skills_literal'] == 2


app = FastAPI()
app.include_router(router)
client = TestClient(app)


def api_payload(files=None):
    files = files or [('resumes', ('a.txt', b'Python\nFastAPI', 'text/plain')),
                      ('resumes', ('b.txt', b'Python', 'text/plain'))]
    data = {
        'vacancy_source': json.dumps(VACANCY, ensure_ascii=False),
        'vacancy_extraction': json.dumps(VACANCY_LLM, ensure_ascii=False),
        'resume_extractions': json.dumps([extraction('Python', 'FastAPI'), extraction('Python')], ensure_ascii=False),
        'candidate_labels': json.dumps(['Кандидат 1', 'Кандидат 2'], ensure_ascii=False),
    }
    return files, data


def test_api_returns_matrices_no_store_and_never_calls_cloud():
    files, data = api_payload()
    response = client.post('/api/batch/compare', files=files, data=data)
    assert response.status_code == 200, response.text
    assert response.headers['cache-control'] == 'no-store'
    assert response.json()['cloud_calls'] == 0
    assert response.json()['candidate_count'] == 2


def test_api_rejects_unsupported_file():
    files, data = api_payload([('resumes', ('bad.exe', b'not a cv', 'application/octet-stream')),
                               ('resumes', ('good.txt', b'Python', 'text/plain'))])
    response = client.post('/api/batch/compare', files=files, data=data)
    assert response.status_code == 422


def test_api_rejects_invalid_json():
    files, data = api_payload()
    data['resume_extractions'] = '{broken'
    response = client.post('/api/batch/compare', files=files, data=data)
    assert response.status_code == 422


def test_api_rejects_more_than_five_files():
    files, data = api_payload([('resumes', (f'{i}.txt', b'Python', 'text/plain')) for i in range(6)])
    response = client.post('/api/batch/compare', files=files, data=data)
    assert response.status_code == 422


def test_ui_installation_has_markers_and_is_idempotent():
    page = Path(__file__).parents[1] / 'static' / 'index.html'
    main = Path(__file__).parents[1] / 'app' / 'main.py'
    if 'BATCH_V09_HTML_START' not in page.read_text(encoding='utf-8'):
        pytest.skip('Интерфейс v0.9 ещё не установлен: запусти scripts/install_batch_v09.py')
    assert page.read_text(encoding='utf-8').count('BATCH_V09_JS_START') == 1
    assert page.read_text(encoding='utf-8').count('BATCH_V09_HTML_START') == 1
    assert main.read_text(encoding='utf-8').count('app.include_router(batch_router)') == 1
