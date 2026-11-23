"""v0.8: предпросмотр и PDF из заново перепроверенной матрицы v0.7."""
from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, Response, UploadFile

from .documents import DocumentError, MAX_FILE_BYTES, extract_document
from .evidence_matrix import EvidenceMatrixError, build_evidence_matrix
from .evidence_matrix_api import _json_object
from .report_v08 import ReportError, compose_report, render_pdf

router = APIRouter(prefix='/api/report', tags=['PDF report / v0.8'])


async def _make_report(
    resume: UploadFile, resume_extraction: str, vacancy_extraction: str,
    vacancy_source: str, semantic_result: str, experience_result: str,
    rag_result: str, vacancy_title: str, candidate_label: str,
) -> dict[str, Any]:
    if len(vacancy_title) > 300 or len(candidate_label) > 240:
        raise HTTPException(422, 'Слишком длинное название вакансии или подпись кандидата')
    try:
        raw = await resume.read(MAX_FILE_BYTES + 1)
        document = extract_document(resume.filename or '', raw)
        matrix = build_evidence_matrix(
            document,
            _json_object(vacancy_source),
            _json_object(resume_extraction),
            _json_object(vacancy_extraction),
            semantic_result=_json_object(semantic_result, optional=True),
            experience_result=_json_object(experience_result, optional=True),
            rag_result=_json_object(rag_result, optional=True),
        )
        return compose_report(matrix, vacancy_title=vacancy_title,
                              candidate_label=candidate_label)
    except (DocumentError, EvidenceMatrixError, ReportError) as exc:
        raise HTTPException(422, str(exc)) from exc
    finally:
        await resume.close()


@router.post('/preview')
async def report_preview(
    response: Response,
    resume: UploadFile = File(...),
    resume_extraction: str = Form(...),
    vacancy_extraction: str = Form(...),
    vacancy_source: str = Form(...),
    semantic_result: str = Form(''),
    experience_result: str = Form(''),
    rag_result: str = Form(''),
    vacancy_title: str = Form(''),
    candidate_label: str = Form(''),
) -> dict[str, Any]:
    response.headers['Cache-Control'] = 'no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return await _make_report(resume, resume_extraction, vacancy_extraction,
                              vacancy_source, semantic_result, experience_result,
                              rag_result, vacancy_title, candidate_label)


@router.post('/pdf')
async def report_pdf(
    resume: UploadFile = File(...),
    resume_extraction: str = Form(...),
    vacancy_extraction: str = Form(...),
    vacancy_source: str = Form(...),
    semantic_result: str = Form(''),
    experience_result: str = Form(''),
    rag_result: str = Form(''),
    vacancy_title: str = Form(''),
    candidate_label: str = Form(''),
) -> Response:
    report = await _make_report(resume, resume_extraction, vacancy_extraction,
                                vacancy_source, semantic_result, experience_result,
                                rag_result, vacancy_title, candidate_label)
    try:
        result = render_pdf(report)
    except ReportError as exc:
        raise HTTPException(500, str(exc)) from exc
    return Response(
        content=result,
        media_type='application/pdf',
        headers={
            'Cache-Control': 'no-store',
            'Pragma': 'no-cache',
            'X-Content-Type-Options': 'nosniff',
            'Content-Disposition': f'attachment; filename="ResumeMatch_report_{date.today():%Y%m%d}.pdf"',
        },
    )
