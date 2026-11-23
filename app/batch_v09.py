"""v0.9: локальное сравнение доказательств для нескольких резюме.

Модель не вызывается здесь. Матрицы проверяются заново для каждого
исходного файла, не переиспользуются RAG/семантические выводы другого кандидата.
Никакой сортировки кандидатов или решения о найме.
"""
from __future__ import annotations

import json
from typing import Any

from .evidence_matrix import EvidenceMatrixError, _negative_skill_mention, build_evidence_matrix

MAX_CANDIDATES = 5
MAX_PAYLOAD_CHARS = 500_000
MAX_LABEL_LENGTH = 80
NEGATIVE_CONTEXT = ('не указан', 'не указано', 'отсутствует', 'не подтвержден',
                    'не подтверждён', 'not listed', 'not mentioned', 'not used')


def _downgrade_negative_context(matrix: dict[str, Any], document: dict[str, Any]) -> None:
    """Do not count a short quote found only in explicitly negative source lines.

    A literal substring by itself cannot disambiguate 'no FastAPI experience'.
    This is a narrow safeguard, not a full semantic confidence judgment.
    """
    blocks = [b.get('source_text', '') for b in document.get('blocks', []) if isinstance(b, dict)]
    for row in matrix['rows']:
        if row['category'] not in ('required_skill', 'optional_skill') or row['status'] != 'exact_mention':
            continue
        proofs = row.get('resume_evidence') or []
        if not proofs:
            continue
        lines = [line for proof in proofs for line in blocks
                 if proof.get('quote') and proof['quote'] in line]
        if lines and all(_negative_skill_mention(line, row['requirement']) or
                         any(phrase in line.casefold() for phrase in NEGATIVE_CONTEXT)
                         for line in lines):
            row['status'] = 'manual_review'
            row['detail'] = ('Навык встречается только в явно отрицательном контексте. '
                             'Такое упоминание не доказывает опыт.')
            row['resume_evidence'] = []



class BatchError(ValueError):
    """Безопасное сообщение о некорректной пакетной обработке."""


def _validate_list(name: str, items: Any, count: int, *, optional: bool = False) -> list[Any]:
    if optional and items is None:
        return [None] * count
    if not isinstance(items, list) or len(items) != count:
        raise BatchError(f'Поле {name}: ожидается список из {count} элементов')
    return items


def compare_documents(
    documents: list[dict[str, Any]],
    vacancy_source: dict[str, Any],
    vacancy_extraction: dict[str, Any],
    resume_extractions: list[dict[str, Any]],
    *,
    experience_results: list[dict[str, Any] | None] | None = None,
    labels: list[str] | None = None,
) -> dict[str, Any]:
    """Revalidate every candidate against its own source; never rank candidates."""
    count = len(documents)
    if not 1 <= count <= MAX_CANDIDATES:
        raise BatchError(f'В пакете допускается от 1 до {MAX_CANDIDATES} резюме')
    if not isinstance(vacancy_source, dict) or not isinstance(vacancy_extraction, dict):
        raise BatchError('Ожидается исходная вакансия и её LLM-извлечение')
    extracts = _validate_list('resume_extractions', resume_extractions, count)
    experiences = _validate_list('experience_results', experience_results, count, optional=True)
    labels = _validate_list('labels', labels, count, optional=True)
    if len(json.dumps({'v': vacancy_source, 'vx': vacancy_extraction,
                       'rx': extracts, 'ex': experiences}, ensure_ascii=False)) > MAX_PAYLOAD_CHARS:
        raise BatchError('Суммарный объём данных для матриц слишком велик')

    results: list[dict[str, Any]] = []
    comparison: list[dict[str, Any]] = []
    for index, (document, extraction, experience, label) in enumerate(
        zip(documents, extracts, experiences, labels, strict=True), start=1
    ):
        if not isinstance(document, dict) or not isinstance(extraction, dict):
            raise BatchError(f'Кандидат {index}: некорректный формат документа или LLM-фактов')
        if experience is not None and not isinstance(experience, dict):
            raise BatchError(f'Кандидат {index}: некорректный анализ стажа')
        if label is not None and (not isinstance(label, str) or len(label) > MAX_LABEL_LENGTH):
            raise BatchError(f'Кандидат {index}: некорректная подпись')
        candidate_label = label.strip() if isinstance(label, str) and label.strip() else f'Кандидат {index}'
        try:
            matrix = build_evidence_matrix(
                document, vacancy_source, extraction, vacancy_extraction,
                experience_result=experience,
            )
        except EvidenceMatrixError as exc:
            raise BatchError(f'Кандидат {index}: {exc}') from exc
        _downgrade_negative_context(matrix, document)
        literal_count = sum(r['category'] == 'required_skill' and r['status'] == 'exact_mention'
                            for r in matrix['rows'])
        candidate_id = f'c{index:02d}'
        results.append({
            'id': candidate_id,
            'label': candidate_label,
            'summary': {
                'required_skills_total': matrix['summary']['required_skills_total'],
                'required_skills_literal': literal_count,
                'experience_analyzed': matrix['summary']['experience_analyzed'],
                'sources_revalidated': matrix['summary']['sources_revalidated'],
            },
            'rows': matrix['rows'],
            'disclaimer': matrix['disclaimer'],
        })
        for row_index, row in enumerate(matrix['rows']):
            if index == 1:
                comparison.append({
                    'row_id': row['id'], 'category': row['category'],
                    'requirement': row['requirement'],
                    'vacancy_evidence': row['vacancy_evidence'],
                    'candidates': [],
                })
            else:
                # Защита от расхождения требований в выдаче по разным резюме.
                if row_index >= len(comparison) or (
                    comparison[row_index]['category'] != row['category']
                    or comparison[row_index]['requirement'] != row['requirement']
                    or comparison[row_index]['vacancy_evidence'] != row['vacancy_evidence']
                ):
                    raise BatchError('Требования вакансии изменились во время сравнения')
            comparison[row_index]['candidates'].append({
                'candidate_id': candidate_id,
                'status': row['status'],
                'verified_resume_quotes': len(row.get('resume_evidence') or []),
                'human_review_required': row['human_review_required'],
            })
        if len(matrix['rows']) != len(comparison):
            raise BatchError('Требования вакансии изменились во время сравнения')

    return {
        'version': '0.9',
        'candidate_count': count,
        'candidates': results,
        'comparison': comparison,
        'automated_ranking': False,
        'cloud_calls': 0,
        'disclaimer': (
            'Сравнение носит справочный характер и сохраняет порядок загрузки файлов. '
            'Дословное совпадение навыка не доказывает владение. '
            'Отсутствие цитаты не означает отсутствие компетенции. '
            'Стаж и обязанности, если не проверялись отдельно, отображаются как «не запускалось». '
            'Решение о найме принимает человек; выводы не должны быть единственным основанием.'
        ),
    }
