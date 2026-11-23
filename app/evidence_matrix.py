"""v0.7: единая матрица доказательств по исходным документам.

Локальная агрегация результатов v0.3–v0.6: БЕЗ вызовов OpenAI и БЕЗ
автоматического утверждения семантики/RAG. Все цитаты проверяются снова
по оригинальному резюме/описанию вакансии, а стаж пересчитывается заново.
"""
from __future__ import annotations

import copy
import json
import re
from datetime import date
from typing import Any

from .llm_experience import (
    EvidenceFact, Employment, EmploymentOutput, _employment_rows,
    _requirements_evaluation, _selected_blocks,
)
from .llm_matching import MatchError, _key, _mentions_skill, match_extractions

MAX_JSON_CHARS = 300_000
MAX_FACTS = 100
MAX_JOBS = 16
MAX_RAG_CLAIMS = 10


class EvidenceMatrixError(ValueError):
    """Корректная ошибка входных данных без приватных исходных текстов."""


def _string(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _resume_lines(document: dict[str, Any]) -> list[dict[str, Any]]:
    blocks = document.get('blocks')
    if not isinstance(blocks, list) or not blocks:
        raise EvidenceMatrixError('В резюме не найдено текстовых блоков')
    return [b for b in blocks if isinstance(b, dict) and isinstance(b.get('source_text'), str)]


def _vacancy_lines(vacancy: dict[str, Any]) -> list[dict[str, Any]]:
    description = vacancy.get('description_text', '')
    skills = vacancy.get('key_skills', [])
    if not isinstance(description, str) or not isinstance(skills, list) or any(not isinstance(s, str) for s in skills):
        raise EvidenceMatrixError('Некорректный исходный текст вакансии')
    return ([{'source_text': x, 'page': None, 'source_field': 'key_skills'} for x in skills]
            + [{'source_text': line, 'page': None, 'source_field': 'description'} for line in description.splitlines()])


def _locate(quote: Any, blocks: list[dict[str, Any]]) -> dict[str, Any] | None:
    text = _string(quote)
    if not text or len(text) > 2500:
        return None
    for block in blocks:
        if text in block.get('source_text', ''):
            return block
    return None


def _verified_extract(extraction: dict[str, Any], blocks: list[dict[str, Any]], categories: tuple[str, ...]) -> dict[str, Any]:
    fields = extraction.get('fields')
    if not isinstance(fields, dict):
        raise EvidenceMatrixError('Неверный формат полей LLM-извлечения')
    result = {'fields': {}}
    for category in categories:
        source_facts = fields.get(category, [])
        if not isinstance(source_facts, list) or len(source_facts) > MAX_FACTS:
            raise EvidenceMatrixError('Слишком много фактов в извлечении')
        verified = []
        for raw in source_facts:
            if not isinstance(raw, dict):
                continue
            value, quote = _string(raw.get('value')), _string(raw.get('source_text'))
            if not value or len(value) > 800:
                continue
            found = _locate(quote, blocks)
            verified.append({
                'value': value, 'source_text': quote[:2500],
                'source_verified': found is not None,
                'source_field': found.get('source_field') if found else None,
                'page': found.get('page') if found else None,
            })
        result['fields'][category] = verified
    return result


def _proof(quote: str, blocks: list[dict[str, Any]], method: str) -> dict[str, Any] | None:
    found = _locate(quote, blocks)
    if not found:
        return None
    return {'quote': quote, 'page': found.get('page'),
            'source_field': found.get('source_field'), 'method': method,
            'source_verified': True}


def _row(category: str, requirement: str, vacancy_quote: str,
         vacancy_blocks: list[dict[str, Any]], *, status: str, method: str,
         resume_proofs: list[dict[str, Any]] | None = None, detail: str = '') -> dict[str, Any]:
    return {
        'id': '', 'category': category, 'requirement': requirement,
        'status': status, 'method': method,
        'vacancy_evidence': _proof(vacancy_quote, vacancy_blocks, 'original_vacancy'),
        'resume_evidence': resume_proofs or [],
        'detail': detail, 'human_review_required': True,
    }


def _rebuild_jobs(raw: dict[str, Any], document: dict[str, Any], today: date) -> list[dict[str, Any]]:
    source_jobs = raw.get('jobs', [])
    if not isinstance(source_jobs, list) or len(source_jobs) > MAX_JOBS:
        raise EvidenceMatrixError('Некорректный набор записей об опыте')
    jobs = []
    for item in source_jobs:
        if not isinstance(item, dict):
            continue
        try:
            tasks = [EvidenceFact(value=_string(f.get('value')), source_text=_string(f.get('source_text')))
                     for f in item.get('tasks', [])[:16] if isinstance(f, dict)]
            technologies = [EvidenceFact(value=_string(f.get('value')), source_text=_string(f.get('source_text')))
                            for f in item.get('technologies', [])[:16] if isinstance(f, dict)]
            jobs.append(Employment(role=_string(item.get('role')),
                                   role_source_text=_string(item.get('role_source_text')),
                                   period_source_text=_string(item.get('period_source_text')),
                                   start_month=_string(item.get('start_month')),
                                   end_month=_string(item.get('end_month')),
                                   is_current=item.get('is_current') is True,
                                   tasks=tasks, technologies=technologies))
        except (TypeError, ValueError, AttributeError) as exc:
            raise EvidenceMatrixError('Некорректные факты об опыте') from exc
    # Даты/цитаты по текущему исходному резюме, а не по флагам в результатах v0.5.
    selected, _ = _selected_blocks(document)
    return _employment_rows(EmploymentOutput(jobs=jobs), selected, today=today)


def _semantic_proofs(row: dict[str, Any], semantic: dict[str, Any] | None,
                     resume_blocks: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]], str]:
    if not semantic:
        return '', [], ''
    group = 'optional_matrix' if row['category'] == 'optional_skill' else 'required_matrix'
    candidates = semantic.get(group, [])
    if not isinstance(candidates, list):
        return '', [], ''
    proposed = next((x for x in candidates[:MAX_FACTS]
                     if isinstance(x, dict) and _key(x.get('requirement')) == _key(row['requirement'])
                     and _string(x.get('vacancy_source_text')) == _string(row['vacancy_evidence']['quote'])
                     ), None)
    if not proposed or proposed.get('status') not in ('semantic_suggestion', 'partial_suggestion'):
        return '', [], ''
    proofs = []
    for evidence in proposed.get('semantic_evidence', [])[:20]:
        if isinstance(evidence, dict):
            p = _proof(_string(evidence.get('quote')), resume_blocks, 'llm_semantic_proposal')
            if p and not _negative_skill_mention(p['quote'], row['requirement']) and p not in proofs:
                proofs.append(p)
    if not proofs:
        return '', [], ''
    status = 'semantic_proposal' if proposed['status'] == 'semantic_suggestion' else 'partial_proposal'
    return status, proofs, _string(proposed.get('semantic_explanation'))[:350]


def _negative_skill_mention(quote: str, skill: str) -> bool:
    # Предохранитель от явных отрицаний. Это не полноценная семантическая проверка:
    # остальные совпадения всё равно называются УПОМИНАНИЕМ, не опытом владения.
    for phrase in ('нет опыта', 'не работал', 'не работала', 'не использовал',
                   'не использовала', 'не владею', 'без опыта', 'no experience', 'never used'):
        if phrase in quote.casefold() and _mentions_skill(quote, skill):
            return True
    return False


def _skills(rows: list[dict[str, Any]], category: str, vacancy_blocks: list[dict[str, Any]],
            resume_blocks: list[dict[str, Any]], semantic: dict[str, Any] | None) -> list[dict[str, Any]]:
    result = []
    for raw in rows:
        name, vac_quote = raw['requirement'], raw['vacancy_source_text']
        vac_proof = _proof(vac_quote, vacancy_blocks, 'original_vacancy')
        resume_quote = _string(raw.get('resume_source_text'))
        proof = _proof(resume_quote, resume_blocks, 'literal_or_alias') if resume_quote else None
        verified_mention = bool(proof and _mentions_skill(resume_quote, name)
                                and not _negative_skill_mention(resume_quote, name))
        if not vac_proof:
            status, method, evidence, detail = 'invalid_source', 'source_check', [], 'Цитата вакансии не найдена в оригинале'
        elif raw['status'] == 'matched' and verified_mention:
            status, method, evidence = 'exact_mention', raw.get('match_method') or 'literal', [proof]
            detail = 'Название явно упомянуто в резюме. Владение и длительность не доказаны.'
        else:
            status, method, evidence, detail = 'not_confirmed', 'literal', [], 'Прямое подтверждение навыка не найдено'
            if raw['status'] == 'manual_review':
                status = 'manual_review'
                detail = 'Требуется ручная проверка извлечённого факта'
            if status == 'not_confirmed':
                suggestion, suggested_proofs, explanation = _semantic_proofs({
                    'category': category, 'requirement': name, 'vacancy_evidence': vac_proof
                }, semantic, resume_blocks)
                if suggestion:
                    status, method, evidence = suggestion, 'llm_semantic', suggested_proofs
                    detail = explanation or 'LLM предложила смысловое сходство; проверить вручную'
        result.append(_row(category, name, vac_quote, vacancy_blocks, status=status, method=method,
                           resume_proofs=evidence, detail=detail))
    return result


def _experience(rows: list[dict[str, Any]], vacancy: dict[str, Any], vacancy_source: dict[str, Any],
                vac_blocks: list[dict[str, Any]], resume_blocks: list[dict[str, Any]],
                exp: dict[str, Any] | None, document: dict[str, Any], today: date) -> list[dict[str, Any]]:
    if exp is None:
        return [_row('experience', r['value'], r['source_text'], vac_blocks, status='not_run',
                     method='not_run', detail='Запустите анализ стажа v0.5') for r in rows]
    jobs = _rebuild_jobs(exp, document, today)
    extraction = {'fields': {'experience': rows}}
    calculated = _requirements_evaluation(jobs, extraction, vacancy_source)
    result = []
    for fact in rows:
        item = next((r for r in calculated if r['requirement'] == fact['value']
                     and r['vacancy_source_text'] == fact['source_text']), None)
        vac_proof = _proof(fact['source_text'], vac_blocks, 'original_vacancy')
        if not vac_proof:
            row = _row('experience', fact['value'], fact['source_text'], vac_blocks,
                       status='invalid_source', method='source_check')
        elif not item:
            row = _row('experience', fact['value'], fact['source_text'], vac_blocks,
                       status='insufficient_evidence', method='dated_periods')
        else:
            status = {'duration_meets_provisionally': 'duration_provisional',
                      'documented_duration_below': 'documented_below',
                      'insufficient_data': 'insufficient_evidence',
                      'manual_review': 'manual_review',
                      'source_unverified': 'invalid_source'}.get(item['status'], 'manual_review')
            evidence = []
            for idx in item.get('job_indices', []):
                job = jobs[idx]
                for field in ('role_source_text', 'period_source_text'):
                    proof = _proof(_string(job.get(field)), resume_blocks, 'dated_job')
                    if proof and proof not in evidence:
                        evidence.append(proof)
                if item.get('skill'):
                    for tech in job['technologies']:
                        if tech['source_verified'] and _mentions_skill(tech['source_text'], item['skill']):
                            proof = _proof(tech['source_text'], resume_blocks, 'technology_in_job')
                            if proof and proof not in evidence:
                                evidence.append(proof)
            row = _row('experience', fact['value'], fact['source_text'], vac_blocks,
                       status=status, method='recalculated_dated_intervals', resume_proofs=evidence,
                       detail='Подсчёт консервативный, без пересечений. Привязку технологии и обязанностей к датам проверяет человек.')
            row['required_months'] = item.get('required_months')
            row['documented_months'] = item.get('documented_months')
            row['skill'] = item.get('skill')
        result.append(row)
    return result


def _responsibilities(rows: list[dict[str, Any]], vac_blocks: list[dict[str, Any]],
                      resume_blocks: list[dict[str, Any]], exp: dict[str, Any] | None,
                      jobs: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    result = []
    known_tasks = set()
    if jobs:
        known_tasks = {x['source_text'] for job in jobs if job.get('role_source_verified')
                       for x in job.get('tasks', []) if x.get('source_verified')}
    reviews = exp.get('responsibility_reviews', []) if isinstance(exp, dict) else []
    if not isinstance(reviews, list):
        reviews = []
    for fact in rows:
        item = next((r for r in reviews if isinstance(r, dict)
                     and _string(r.get('requirement')) == fact['value']
                     and _string(r.get('vacancy_source_text')) == fact['source_text']), None)
        vac_proof = _proof(fact['source_text'], vac_blocks, 'original_vacancy')
        if not vac_proof:
            status, evidence, detail = 'invalid_source', [], 'Текст вакансии не подтверждает требование'
        elif exp is None:
            status, evidence, detail = 'not_run', [], 'Запустите сопоставление обязанностей v0.5'
        else:
            evidence = []
            raw_evidence = (item or {}).get('evidence', [])
            if not isinstance(raw_evidence, list):
                raw_evidence = []
            for raw in raw_evidence[:20]:
                if isinstance(raw, dict):
                    quote = _string(raw.get('quote'))
                    if quote not in known_tasks:
                        continue
                    proof = _proof(quote, resume_blocks, 'llm_duty_proposal')
                    if proof and proof not in evidence:
                        evidence.append(proof)
            verdict = item.get('verdict') if item else None
            if verdict == 'supported' and evidence:
                status = 'semantic_proposal'
            elif verdict == 'partial' and evidence:
                status = 'partial_proposal'
            else:
                status = 'insufficient_evidence'
            detail = 'LLM предложила смысловую связь; цитаты проверены, вывод требует ручной оценки' if evidence else 'Нет проверенного сопоставления обязанностей'
        result.append(_row('responsibility', fact['value'], fact['source_text'], vac_blocks,
                           status=status, method='llm_duty_proposal' if exp is not None else 'not_run',
                           resume_proofs=evidence, detail=detail))
    return result


def _rag_observations(rag: dict[str, Any] | None, resume_blocks: list[dict[str, Any]],
                      vacancy_blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if rag is None:
        return []
    observations = []
    claims = rag.get('claims', [])
    if not isinstance(claims, list):
        return []
    for claim in claims[:MAX_RAG_CLAIMS]:
        if not isinstance(claim, dict):
            continue
        citations = []
        claim_citations = claim.get('citations', [])
        if not isinstance(claim_citations, list):
            continue
        for raw in claim_citations[:10]:
            if not isinstance(raw, dict):
                continue
            side = raw.get('document_type')
            if side not in ('resume', 'vacancy'):
                continue
            source = resume_blocks if side == 'resume' else vacancy_blocks
            proof = _proof(_string(raw.get('quote')), source, 'rag_original_quote')
            if proof:
                proof['document_type'] = side
                proof['chunk_id'] = _string(raw.get('chunk_id'))[:64]
                if proof not in citations:
                    citations.append(proof)
        # Не публикуем утверждение без реальных цитат именно резюме.
        if not any(c['document_type'] == 'resume' for c in citations):
            continue
        observations.append({'statement': _string(claim.get('statement'))[:500],
                             'citations': citations, 'status': 'manual_review',
                             'affects_score': False})
    return observations


def build_evidence_matrix(document: dict[str, Any], vacancy_source: dict[str, Any],
                          resume_extraction: dict[str, Any], vacancy_extraction: dict[str, Any],
                          *, semantic_result: dict[str, Any] | None = None,
                          experience_result: dict[str, Any] | None = None,
                          rag_result: dict[str, Any] | None = None,
                          today: date | None = None) -> dict[str, Any]:
    """Возвращает единую матрицу; не вызывает OpenAI и не сохраняет документы."""
    for object_ in (resume_extraction, vacancy_extraction, vacancy_source):
        if not isinstance(object_, dict):
            raise EvidenceMatrixError('Ожидались JSON-объекты извлечения и вакансии')
    for optional in (semantic_result, experience_result, rag_result):
        if optional is not None and not isinstance(optional, dict):
            raise EvidenceMatrixError('Необязательные результаты должны быть JSON-объектами')
    payload = {'resume_extraction': resume_extraction, 'vacancy_extraction': vacancy_extraction,
               'vacancy_source': vacancy_source, 'semantic_result': semantic_result,
               'experience_result': experience_result, 'rag_result': rag_result}
    if len(json.dumps(payload, ensure_ascii=False)) > MAX_JSON_CHARS:
        raise EvidenceMatrixError('Данные для матрицы слишком велики')
    resume_blocks, vac_blocks = _resume_lines(document), _vacancy_lines(vacancy_source)
    resume = _verified_extract(resume_extraction, resume_blocks,
                               ('skills', 'experience', 'projects', 'education'))
    vacancy = _verified_extract(vacancy_extraction, vac_blocks,
                                ('required_skills', 'optional_skills', 'experience', 'responsibilities', 'conditions'))
    try:
        exact = match_extractions(resume, vacancy)
    except MatchError as exc:
        raise EvidenceMatrixError(str(exc)) from exc
    skills = (_skills(exact['required_matrix'], 'required_skill', vac_blocks, resume_blocks, semantic_result)
              + _skills(exact['optional_matrix'], 'optional_skill', vac_blocks, resume_blocks, semantic_result))
    skill_count = sum(r['category'] == 'required_skill' for r in skills)
    exact_count = sum(r['category'] == 'required_skill' and r['status'] == 'exact_mention' for r in skills)
    uncertain_count = sum(r['category'] == 'required_skill' and r['status'] in ('invalid_source', 'manual_review') for r in skills)
    exact_score = round(100 * exact_count / skill_count) if skill_count and not uncertain_count else None
    now = today or date.today()
    exp_jobs = _rebuild_jobs(experience_result, document, now) if experience_result is not None else None
    exp_rows = _experience(vacancy['fields']['experience'], vacancy, vacancy_source, vac_blocks,
                           resume_blocks, experience_result, document, now)
    duty_rows = _responsibilities(vacancy['fields']['responsibilities'], vac_blocks,
                                  resume_blocks, experience_result, exp_jobs)
    all_rows = skills + exp_rows + duty_rows
    for i, row in enumerate(all_rows, 1):
        row['id'] = f'm{i:03d}'
    return {
        'version': '0.7', 'rows': all_rows,
        'summary': {'required_skills_total': skill_count,
                    'required_skills_literal': exact_count,
                    'literal_skill_score_percent': exact_score,
                    'experience_requirements': len(exp_rows),
                    'responsibilities': len(duty_rows),
                    'proposals_for_review': sum(r['status'] in ('semantic_proposal', 'partial_proposal', 'duration_provisional') for r in all_rows),
                    'sources_revalidated': True,
                    'experience_analyzed': experience_result is not None,
                    'semantic_analyzed': semantic_result is not None,
                    'rag_analyzed': rag_result is not None},
        'rag_observations': _rag_observations(rag_result, resume_blocks, vac_blocks),
        'disclaimer': ('Матрица формируется локально: цитаты повторно сверяются с исходными документами. '
                       'Дословное упоминание не доказывает владение; расчет стажа предварительный, '
                       'даты/привязка технологии к работе требуют проверки человеком. '
                       'RAG-наблюдения и смысловые предложения LLM не влияют на процент навыков. '
                       'Отсутствие подтверждения не означает отсутствия навыка.'),
    }
