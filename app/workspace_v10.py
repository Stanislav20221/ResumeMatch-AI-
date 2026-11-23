"""v1.0: encrypted, opt-in, single-user local archive for evidence snapshots.

Original resumes are NEVER saved. Snapshots are not independently authenticated:
after reopening, the user is shown the saved output, not a new verification.
All user-provided content (including labels) is Fernet-encrypted at rest.
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from cryptography.fernet import Fernet, InvalidToken

ROOT = Path(__file__).resolve().parents[1]
MAX_SNAPSHOT_BYTES = 1_500_000
MAX_ITEMS = 200


class WorkspaceError(ValueError):
    pass


class WorkspaceDisabled(RuntimeError):
    pass


def _now() -> int:
    return int(time.time())


def _iso(stamp: int) -> str:
    return datetime.fromtimestamp(stamp, timezone.utc).isoformat(timespec='seconds')


def _token_id() -> str:
    return uuid.uuid4().hex


def _limit(value: str, field: str, maximum: int, minimum: int = 1) -> str:
    if not isinstance(value, str):
        raise WorkspaceError(f'{field}: требуется текст')
    result = value.strip()
    if not minimum <= len(result) <= maximum:
        raise WorkspaceError(f'{field}: длина должна быть от {minimum} до {maximum} символов')
    return result


class Workspace:
    def __init__(self, db_path: Path | None = None, key: str | None = None,
                 retention_days: int | None = None):
        secret = key if key is not None else os.getenv('RESUMEMATCH_HISTORY_KEY', '')
        if not secret:
            raise WorkspaceDisabled('История отключена: установите RESUMEMATCH_HISTORY_KEY в .env')
        try:
            self.cipher = Fernet(secret.encode('ascii'))
        except (ValueError, TypeError) as exc:
            raise WorkspaceDisabled('RESUMEMATCH_HISTORY_KEY должен быть корректным ключом Fernet') from exc
        path_text = os.getenv('RESUMEMATCH_DB_PATH', 'data/resumematch_history.sqlite3')
        location = db_path or Path(path_text)
        if location.is_symlink():
            raise WorkspaceDisabled('База истории не должна быть символьной ссылкой')
        if not location.is_absolute():
            location = ROOT / location
        self.path = location.resolve()
        if retention_days is None:
            try:
                retention_days = int(os.getenv('RESUMEMATCH_RETENTION_DAYS', '30'))
            except ValueError as exc:
                raise WorkspaceDisabled('RESUMEMATCH_RETENTION_DAYS должен быть числом') from exc
        if not 1 <= retention_days <= 365:
            raise WorkspaceDisabled('Допустимый срок хранения: 1–365 дней')
        self.retention_days = retention_days
        self._create_db()

    def _enc(self, value: Any) -> bytes:
        return self.cipher.encrypt(json.dumps(value, ensure_ascii=False, separators=(',', ':'),
                                              allow_nan=False).encode('utf-8'))

    def _dec(self, blob: bytes) -> Any:
        try:
            return json.loads(self.cipher.decrypt(blob))
        except (InvalidToken, UnicodeError, ValueError) as exc:
            raise WorkspaceDisabled('Не удалось расшифровать запись. Проверьте ключ истории в .env') from exc

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(str(self.path), timeout=10)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute('PRAGMA foreign_keys=ON')
            connection.execute('PRAGMA secure_delete=ON')
            with connection:
                yield connection
        finally:
            connection.close()

    def _create_db(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fresh = not self.path.exists()
        if self.path.is_symlink():
            raise WorkspaceDisabled('База истории не должна быть символьной ссылкой')
        with self._conn() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS workspace_metadata (
                name TEXT PRIMARY KEY, value BLOB NOT NULL
            );
            CREATE TABLE IF NOT EXISTS candidates (
                id TEXT PRIMARY KEY, name BLOB NOT NULL, note BLOB NOT NULL,
                created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS vacancies (
                id TEXT PRIMARY KEY, title BLOB NOT NULL, description BLOB NOT NULL,
                skills BLOB NOT NULL, created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS archives (
                id TEXT PRIMARY KEY, kind TEXT NOT NULL CHECK(kind IN ('single','batch')),
                vacancy_id TEXT NOT NULL REFERENCES vacancies(id) ON DELETE CASCADE,
                title BLOB NOT NULL, snapshot BLOB NOT NULL,
                created_at INTEGER NOT NULL, expires_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS archive_candidates (
                archive_id TEXT NOT NULL REFERENCES archives(id) ON DELETE CASCADE,
                candidate_id TEXT NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
                PRIMARY KEY (archive_id, candidate_id)
            );
            CREATE INDEX IF NOT EXISTS archives_expiry ON archives(expires_at);
            CREATE INDEX IF NOT EXISTS archive_candidates_candidate ON archive_candidates(candidate_id);
            ''')
            marker = db.execute("SELECT value FROM workspace_metadata WHERE name = 'keycheck'").fetchone()
            if marker is None:
                db.execute("INSERT INTO workspace_metadata(name, value) VALUES ('keycheck', ?)",
                           (self.cipher.encrypt(b'ResumeMatch-workspace-v1'),))
            else:
                try:
                    if self.cipher.decrypt(marker['value']) != b'ResumeMatch-workspace-v1':
                        raise WorkspaceDisabled('Неверный ключ шифрования истории')
                except InvalidToken as exc:
                    raise WorkspaceDisabled('Неверный ключ шифрования истории: сохраните старый ключ из .env') from exc
        if fresh and os.name == 'posix':
            self.path.chmod(0o600)

    def purge(self) -> int:
        with self._conn() as db:
            cursor = db.execute('DELETE FROM archives WHERE expires_at <= ?', (_now(),))
            return cursor.rowcount

    def candidate_create(self, name: str, note: str = '') -> dict[str, Any]:
        name = _limit(name, 'Имя/метка кандидата', 120)
        note = _limit(note, 'Заметка', 1000, 0)
        ident, now = _token_id(), _now()
        with self._conn() as db:
            db.execute('INSERT INTO candidates VALUES (?,?,?,?,?)',
                       (ident, self._enc(name), self._enc(note), now, now))
        return {'id': ident, 'name': name, 'note': note, 'created_at': _iso(now)}

    def vacancy_create(self, title: str, description: str = '',
                       key_skills: list[str] | None = None) -> dict[str, Any]:
        title = _limit(title, 'Название вакансии', 180)
        description = _limit(description, 'Описание вакансии', 24000, 0)
        if not isinstance(key_skills, list) or len(key_skills) > 100:
            raise WorkspaceError('Некорректный перечень навыков')
        skills = [_limit(x, 'Навык', 150) for x in key_skills]
        ident, now = _token_id(), _now()
        with self._conn() as db:
            db.execute('INSERT INTO vacancies VALUES (?,?,?,?,?,?)',
                       (ident, self._enc(title), self._enc(description), self._enc(skills), now, now))
        return {'id': ident, 'title': title, 'description': description,
                'key_skills': skills, 'created_at': _iso(now)}

    def candidates(self) -> list[dict[str, Any]]:
        with self._conn() as db:
            rows = db.execute('SELECT * FROM candidates ORDER BY created_at DESC LIMIT ?',
                              (MAX_ITEMS,)).fetchall()
        return [{'id': r['id'], 'name': self._dec(r['name']), 'note': self._dec(r['note']),
                 'created_at': _iso(r['created_at'])} for r in rows]

    def vacancies(self) -> list[dict[str, Any]]:
        with self._conn() as db:
            rows = db.execute('SELECT * FROM vacancies ORDER BY created_at DESC LIMIT ?',
                              (MAX_ITEMS,)).fetchall()
        return [{'id': r['id'], 'title': self._dec(r['title']),
                 'description': self._dec(r['description']),
                 'key_skills': self._dec(r['skills']),
                 'created_at': _iso(r['created_at'])} for r in rows]

    def candidate_update(self, ident: str, name: str, note: str) -> None:
        name = _limit(name, 'Имя/метка кандидата', 120)
        note = _limit(note, 'Заметка', 1000, 0)
        with self._conn() as db:
            cursor = db.execute('UPDATE candidates SET name=?, note=?, updated_at=? WHERE id=?',
                                (self._enc(name), self._enc(note), _now(), ident))
            if cursor.rowcount == 0:
                raise WorkspaceError('Кандидат не найден')

    def vacancy_update(self, ident: str, title: str, description: str,
                       key_skills: list[str]) -> None:
        title = _limit(title, 'Название вакансии', 180)
        description = _limit(description, 'Описание вакансии', 24000, 0)
        if not isinstance(key_skills, list) or len(key_skills) > 100:
            raise WorkspaceError('Некорректный перечень навыков')
        skills = [_limit(x, 'Навык', 150) for x in key_skills]
        with self._conn() as db:
            cursor = db.execute('UPDATE vacancies SET title=?, description=?, skills=?, updated_at=? WHERE id=?',
                                (self._enc(title), self._enc(description), self._enc(skills), _now(), ident))
            if cursor.rowcount == 0:
                raise WorkspaceError('Вакансия не найдена')

    def candidate_delete(self, ident: str) -> None:
        with self._conn() as db:
            db.execute('DELETE FROM archives WHERE id IN (SELECT archive_id FROM archive_candidates WHERE candidate_id=?)',
                       (ident,))
            cursor = db.execute('DELETE FROM candidates WHERE id=?', (ident,))
            if not cursor.rowcount:
                raise WorkspaceError('Кандидат не найден')

    def vacancy_delete(self, ident: str) -> None:
        with self._conn() as db:
            cursor = db.execute('DELETE FROM vacancies WHERE id=?', (ident,))
            if not cursor.rowcount:
                raise WorkspaceError('Вакансия не найдена')

    def archive_create(self, *, kind: str, title: str, vacancy: dict[str, Any],
                       candidate_labels: list[str], snapshot: dict[str, Any]) -> dict[str, Any]:
        """Atomic save: all related entities are committed together or not at all."""
        if kind not in ('single', 'batch'):
            raise WorkspaceError('Неизвестный тип сохранённого анализа')
        title = _limit(title, 'Название записи', 180)
        if not isinstance(candidate_labels, list) or not 1 <= len(candidate_labels) <= 5:
            raise WorkspaceError('Нужно от одного до пяти кандидатов')
        if kind == 'single' and len(candidate_labels) != 1:
            raise WorkspaceError('Одиночный отчёт должен относиться к одному кандидату')
        labels = [_limit(x, 'Метка кандидата', 120) for x in candidate_labels]
        if not isinstance(vacancy, dict):
            raise WorkspaceError('Некорректная вакансия')
        vac_title = _limit(vacancy.get('title', ''), 'Название вакансии', 180)
        description = _limit(vacancy.get('description', ''), 'Описание вакансии', 24000, 0)
        raw_skills = vacancy.get('key_skills', [])
        if not isinstance(raw_skills, list) or len(raw_skills) > 100:
            raise WorkspaceError('Некорректные навыки вакансии')
        skills = [_limit(x, 'Навык', 150) for x in raw_skills]
        if not isinstance(snapshot, dict):
            raise WorkspaceError('Снимок анализа должен быть объектом')
        if kind == 'batch' and (not isinstance(snapshot.get('comparison'), list) or
                                not isinstance(snapshot.get('candidates'), list)):
            raise WorkspaceError('Некорректный снимок пакетной матрицы')
        if kind == 'single' and (not isinstance(snapshot.get('rows'), list) or
                                 not isinstance(snapshot.get('overview'), dict)):
            raise WorkspaceError('Некорректный снимок отчёта')
        try:
            raw_snapshot = json.dumps(snapshot, ensure_ascii=False, separators=(',', ':'),
                                      allow_nan=False).encode('utf-8')
        except (TypeError, ValueError) as exc:
            raise WorkspaceError('Снимок содержит недопустимые данные') from exc
        if len(raw_snapshot) > MAX_SNAPSHOT_BYTES:
            raise WorkspaceError('Снимок слишком большой (лимит 1,5 МБ)')
        now, ident, vac_id = _now(), _token_id(), _token_id()
        expiry = now + self.retention_days * 86400
        candidate_ids = [_token_id() for _ in labels]
        with self._conn() as db:
            db.execute('INSERT INTO vacancies VALUES (?,?,?,?,?,?)',
                       (vac_id, self._enc(vac_title), self._enc(description), self._enc(skills), now, now))
            for cand_id, cand_name in zip(candidate_ids, labels):
                db.execute('INSERT INTO candidates VALUES (?,?,?,?,?)',
                           (cand_id, self._enc(cand_name), self._enc(''), now, now))
            db.execute('INSERT INTO archives VALUES (?,?,?,?,?,?,?)',
                       (ident, kind, vac_id, self._enc(title), self._enc(snapshot), now, expiry))
            db.executemany('INSERT INTO archive_candidates VALUES (?,?)',
                           [(ident, cand_id) for cand_id in candidate_ids])
        return {'id': ident, 'kind': kind, 'title': title, 'vacancy_id': vac_id,
                'candidate_ids': candidate_ids, 'created_at': _iso(now),
                'expires_at': _iso(expiry)}

    def archives(self) -> list[dict[str, Any]]:
        self.purge()
        with self._conn() as db:
            rows = db.execute('SELECT id,kind,vacancy_id,title,created_at,expires_at FROM archives '
                              'WHERE expires_at > ? ORDER BY created_at DESC, rowid DESC LIMIT ?',
                              (_now(), MAX_ITEMS)).fetchall()
        return [{'id': r['id'], 'kind': r['kind'], 'title': self._dec(r['title']),
                 'vacancy_id': r['vacancy_id'], 'created_at': _iso(r['created_at']),
                 'expires_at': _iso(r['expires_at'])} for r in rows]

    def archive_get(self, ident: str) -> dict[str, Any]:
        self.purge()
        with self._conn() as db:
            row = db.execute('SELECT * FROM archives WHERE id=? AND expires_at > ?',
                             (ident, _now())).fetchone()
            if row is None:
                raise WorkspaceError('Запись истории не найдена или срок её хранения истёк')
            memberships = db.execute('SELECT c.id, c.name FROM archive_candidates ac '
                                     'JOIN candidates c ON c.id=ac.candidate_id '
                                     'WHERE ac.archive_id=? ORDER BY ac.rowid', (ident,)).fetchall()
        return {'id': row['id'], 'kind': row['kind'], 'title': self._dec(row['title']),
                'vacancy_id': row['vacancy_id'], 'snapshot': self._dec(row['snapshot']),
                'candidates': [{'id': r['id'], 'name': self._dec(r['name'])} for r in memberships],
                'created_at': _iso(row['created_at']), 'expires_at': _iso(row['expires_at']),
                'notice': 'Архивный снимок. При открытии не выполняется повторная проверка исходных документов.'}

    def archive_delete(self, ident: str) -> None:
        with self._conn() as db:
            cursor = db.execute('DELETE FROM archives WHERE id=?', (ident,))
            if not cursor.rowcount:
                raise WorkspaceError('Запись истории не найдена')
