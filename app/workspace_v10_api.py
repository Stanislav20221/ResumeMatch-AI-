"""Authenticated local workspace API v1.0. Never accepts or persists uploaded CV bytes."""
from __future__ import annotations

import hmac
import os
from typing import Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from pydantic import BaseModel, Field

from .workspace_v10 import Workspace, WorkspaceDisabled, WorkspaceError


def require_workspace_token(
    response: Response, x_workspace_token: str | None = Header(default=None, alias='X-Workspace-Token')
) -> None:
    response.headers['Cache-Control'] = 'no-store, private'
    response.headers['Pragma'] = 'no-cache'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    expected = os.getenv('RESUMEMATCH_WORKSPACE_TOKEN', '')
    if len(expected) < 24:
        raise HTTPException(503, 'История отключена: задайте RESUMEMATCH_WORKSPACE_TOKEN в .env')
    if not x_workspace_token or not hmac.compare_digest(expected, x_workspace_token):
        raise HTTPException(401, 'Неверный ключ доступа к истории')


router = APIRouter(prefix='/api/workspace', tags=['Local encrypted workspace / v1.0'],
                   dependencies=[Depends(require_workspace_token)])


def store() -> Workspace:
    try:
        return Workspace()
    except WorkspaceDisabled as exc:
        raise HTTPException(503, str(exc)) from exc


class CandidateInput(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    note: str = Field(default='', max_length=1000)


class VacancyInput(BaseModel):
    title: str = Field(min_length=1, max_length=180)
    description: str = Field(default='', max_length=24000)
    key_skills: list[str] = Field(default_factory=list, max_length=100)


class ArchiveInput(BaseModel):
    kind: Literal['single', 'batch']
    title: str = Field(min_length=1, max_length=180)
    vacancy: VacancyInput
    candidate_labels: list[str] = Field(min_length=1, max_length=5)
    snapshot: dict[str, Any]
    save_consent: bool


def _handle_error(exc: WorkspaceError) -> None:
    raise HTTPException(422, str(exc)) from exc


@router.get('/candidates')
def get_candidates() -> dict:
    return {'items': store().candidates()}


@router.post('/candidates', status_code=201)
def create_candidate(payload: CandidateInput) -> dict:
    try:
        return store().candidate_create(payload.name, payload.note)
    except WorkspaceError as exc:
        _handle_error(exc)


@router.put('/candidates/{candidate_id}')
def update_candidate(candidate_id: str, payload: CandidateInput) -> dict:
    try:
        store().candidate_update(candidate_id, payload.name, payload.note)
        return {'updated': True}
    except WorkspaceError as exc:
        _handle_error(exc)


@router.delete('/candidates/{candidate_id}')
def remove_candidate(candidate_id: str) -> dict:
    try:
        store().candidate_delete(candidate_id)
        return {'deleted': True, 'affected_archives': 'associated archives were deleted'}
    except WorkspaceError as exc:
        _handle_error(exc)


@router.get('/vacancies')
def get_vacancies() -> dict:
    return {'items': store().vacancies()}


@router.post('/vacancies', status_code=201)
def create_vacancy(payload: VacancyInput) -> dict:
    try:
        return store().vacancy_create(payload.title, payload.description, payload.key_skills)
    except WorkspaceError as exc:
        _handle_error(exc)


@router.put('/vacancies/{vacancy_id}')
def update_vacancy(vacancy_id: str, payload: VacancyInput) -> dict:
    try:
        store().vacancy_update(vacancy_id, payload.title, payload.description, payload.key_skills)
        return {'updated': True}
    except WorkspaceError as exc:
        _handle_error(exc)


@router.delete('/vacancies/{vacancy_id}')
def remove_vacancy(vacancy_id: str) -> dict:
    try:
        store().vacancy_delete(vacancy_id)
        return {'deleted': True, 'affected_archives': 'associated archives were deleted'}
    except WorkspaceError as exc:
        _handle_error(exc)


@router.get('/archives')
def list_archives() -> dict:
    return {'items': store().archives()}


@router.post('/archives', status_code=201)
def create_archive(payload: ArchiveInput) -> dict:
    if not payload.save_consent:
        raise HTTPException(422, 'Для сохранения доказательств нужно явное согласие')
    try:
        return store().archive_create(
            kind=payload.kind, title=payload.title, vacancy=payload.vacancy.model_dump(),
            candidate_labels=payload.candidate_labels, snapshot=payload.snapshot,
        )
    except WorkspaceError as exc:
        _handle_error(exc)


@router.get('/archives/{archive_id}')
def get_archive(archive_id: str) -> dict:
    try:
        return store().archive_get(archive_id)
    except WorkspaceError as exc:
        _handle_error(exc)


@router.delete('/archives/{archive_id}')
def remove_archive(archive_id: str) -> dict:
    try:
        store().archive_delete(archive_id)
        return {'deleted': True}
    except WorkspaceError as exc:
        _handle_error(exc)


@router.post('/purge')
def purge_expired() -> dict:
    return {'expired_removed': store().purge()}
