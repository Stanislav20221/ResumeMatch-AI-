"""Isolated offline tests: no OpenAI, no real documents, temporary SQLite only."""
import os
import sqlite3
import tempfile
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.workspace_v10 import Workspace, WorkspaceDisabled, WorkspaceError
from app.workspace_v10_api import router


@pytest.fixture
def setup_workspace(monkeypatch, tmp_path):
    key = Fernet.generate_key().decode('ascii')
    token = 'a-unique-local-secret-token-for-tests-123'
    monkeypatch.setenv('RESUMEMATCH_WORKSPACE_TOKEN', token)
    monkeypatch.setenv('RESUMEMATCH_HISTORY_KEY', key)
    monkeypatch.setenv('RESUMEMATCH_DB_PATH', str(tmp_path / 'private.sqlite3'))
    monkeypatch.setenv('RESUMEMATCH_RETENTION_DAYS', '30')
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    return client, token, tmp_path / 'private.sqlite3', key


def headers(token):
    return {'X-Workspace-Token': token}


def fake_archive(kind='single'):
    if kind == 'single':
        snapshot = {'overview': {'literal_mentions': 2}, 'rows': [
            {'requirement': 'FastAPI', 'status': 'exact_mention',
             'resume_quotes': [{'quote': 'секретное резюме: FastAPI'}]}]}
        labels = ['Кандидат Иван']
    else:
        snapshot = {'comparison': [{'requirement': 'Python', 'candidates': [{'status':'exact_mention'}]}],
                    'candidates': [{'label': 'Тестовый кандидат', 'rows': []}]}
        labels = ['Кандидат Иван', 'Кандидат Пётр']
    return {'kind': kind, 'title': 'Тест отчёт', 'vacancy': {'title':'Python вакансии',
           'description':'описание секретной вакансии', 'key_skills':['Python']},
           'candidate_labels': labels, 'snapshot':snapshot, 'save_consent':True}


def test_auth_required(setup_workspace):
    client, token, _, _ = setup_workspace
    assert client.get('/api/workspace/archives').status_code == 401
    assert client.get('/api/workspace/archives', headers=headers('wrong')).status_code == 401
    assert client.get('/api/workspace/archives', headers=headers(token)).status_code == 200


def test_no_history_without_secrets(monkeypatch, tmp_path):
    monkeypatch.delenv('RESUMEMATCH_HISTORY_KEY', raising=False)
    with pytest.raises(WorkspaceDisabled):
        Workspace(db_path=tmp_path/'db.sqlite3')
    assert not (tmp_path/'db.sqlite3').exists()


def test_no_consent_rejected(setup_workspace):
    client, token, path, _ = setup_workspace
    data = fake_archive(); data['save_consent'] = False
    assert client.post('/api/workspace/archives', json=data, headers=headers(token)).status_code == 422
    assert not path.exists()


def test_archive_ciphertext_and_open(setup_workspace):
    client, token, path, _ = setup_workspace
    response = client.post('/api/workspace/archives', json=fake_archive(), headers=headers(token))
    assert response.status_code == 201, response.text
    ident = response.json()['id']
    assert path.exists()
    contents = path.read_bytes()
    assert 'секретное резюме'.encode('utf-8') not in contents
    assert 'Кандидат Иван'.encode('utf-8') not in contents
    assert 'описание секретной вакансии'.encode('utf-8') not in contents
    record = client.get('/api/workspace/archives/'+ident, headers=headers(token)).json()
    assert record['snapshot']['rows'][0]['resume_quotes'][0]['quote'].startswith('секретное')
    assert 'не выполняется' in record['notice']
    assert len(client.get('/api/workspace/candidates', headers=headers(token)).json()['items']) == 1
    assert len(client.get('/api/workspace/vacancies', headers=headers(token)).json()['items']) == 1


def test_batch_archive_and_delete_vacancy(setup_workspace):
    client, token, path, _ = setup_workspace
    saved = client.post('/api/workspace/archives', json=fake_archive('batch'),
                        headers=headers(token)).json()
    assert len(saved['candidate_ids']) == 2
    listings = client.get('/api/workspace/archives', headers=headers(token)).json()
    assert len(listings['items']) == 1
    assert client.delete('/api/workspace/vacancies/'+saved['vacancy_id'], headers=headers(token)).status_code == 200
    assert client.get('/api/workspace/archives', headers=headers(token)).json()['items'] == []


def test_delete_candidate_cascades_related_archive(setup_workspace):
    client, token, _, _ = setup_workspace
    saved = client.post('/api/workspace/archives', json=fake_archive(),
                        headers=headers(token)).json()
    assert client.delete('/api/workspace/candidates/'+saved['candidate_ids'][0],
                         headers=headers(token)).status_code == 200
    assert client.get('/api/workspace/archives', headers=headers(token)).json()['items'] == []


def test_candidate_and_vacancy_management(setup_workspace):
    client, token, _, _ = setup_workspace
    c = client.post('/api/workspace/candidates', json={'name':'Аноним 1'},
                    headers=headers(token)).json()
    assert client.put('/api/workspace/candidates/'+c['id'],
                      json={'name':'Аноним 2', 'note':'пометка'},
                      headers=headers(token)).status_code == 200
    assert client.get('/api/workspace/candidates', headers=headers(token)).json()['items'][0]['name'] == 'Аноним 2'
    v = client.post('/api/workspace/vacancies', json={'title':'Вакансия 1'},
                    headers=headers(token)).json()
    assert client.put('/api/workspace/vacancies/'+v['id'],
                      json={'title':'Вакансия 2', 'description':'требования', 'key_skills':['Python']},
                      headers=headers(token)).status_code == 200
    assert client.get('/api/workspace/vacancies', headers=headers(token)).json()['items'][0]['title'] == 'Вакансия 2'
    assert client.delete('/api/workspace/candidates/'+c['id'], headers=headers(token)).status_code == 200


def test_retention_expiry_purge(setup_workspace):
    client, token, path, _ = setup_workspace
    saved = client.post('/api/workspace/archives', json=fake_archive(), headers=headers(token)).json()
    with sqlite3.connect(str(path)) as db:
        db.execute('UPDATE archives SET expires_at = 1 WHERE id = ?', (saved['id'],))
    assert client.get('/api/workspace/archives', headers=headers(token)).json()['items'] == []
    assert client.get('/api/workspace/archives/'+saved['id'], headers=headers(token)).status_code == 422


def test_invalid_key_cannot_read_archive(setup_workspace):
    client, token, path, original_key = setup_workspace
    saved = client.post('/api/workspace/archives', json=fake_archive(), headers=headers(token)).json()
    with pytest.raises(WorkspaceDisabled):
        Workspace(db_path=path, key=Fernet.generate_key().decode()).archive_get(saved['id'])
    assert Workspace(db_path=path, key=original_key).archive_get(saved['id'])['id'] == saved['id']


def test_snapshot_validation_and_limits(setup_workspace):
    client, token, _, _ = setup_workspace
    payload = fake_archive(); payload['snapshot'] = {'rows':[]}
    assert client.post('/api/workspace/archives', json=payload, headers=headers(token)).status_code == 422
    payload = fake_archive(); payload['snapshot']['oversize'] = 'x' * 1_500_000
    assert client.post('/api/workspace/archives', json=payload, headers=headers(token)).status_code == 422


def test_no_openai_api_calls_or_cv_upload_in_archive_router():
    from app.workspace_v10_api import router as history_router
    paths = {(r.path, tuple(r.methods or [])) for r in history_router.routes}
    assert not any('/upload' in name for name, _ in paths)


def test_security_headers(setup_workspace):
    client, token, _, _ = setup_workspace
    result = client.get('/api/workspace/archives', headers=headers(token))
    assert result.headers.get('cache-control') == 'no-store, private'
