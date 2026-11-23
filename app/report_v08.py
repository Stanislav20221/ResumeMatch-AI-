"""v0.8: локальная сводка и PDF по уже перепроверенной evidence matrix v0.7.

Этот модуль не вызывает LLM и не принимает внешние утверждения о квалификации
как доказанный факт. Вызывающий API обязан пересобрать матрицу по оригиналам.
"""
from __future__ import annotations

from collections import Counter
from datetime import date
from html import escape
from io import BytesIO
from pathlib import Path
from typing import Any

STATUS_LABELS = {
    'exact_mention': 'Дословно упомянуто',
    'semantic_proposal': 'Предложение LLM - проверить',
    'partial_proposal': 'Частичное предложение LLM',
    'duration_provisional': 'Стаж предварительно достаточен',
    'documented_below': 'Документированный срок ниже требования',
    'insufficient_evidence': 'Недостаточно доказательств',
    'not_confirmed': 'Прямого подтверждения нет',
    'not_run': 'Проверка не запускалась',
    'manual_review': 'Требуется ручная проверка',
    'invalid_source': 'Цитата источника не подтверждена',
}
CATEGORY_LABELS = {
    'required_skill': 'Обязательные навыки',
    'optional_skill': 'Желательные навыки',
    'experience': 'Требования к стажу',
    'responsibility': 'Профессиональные обязанности',
}
REVIEW_STATUSES = {'semantic_proposal', 'partial_proposal', 'duration_provisional',
                   'manual_review', 'invalid_source'}


class ReportError(ValueError):
    """Ошибка в данных/настройках отчёта без вывода приватного текста."""


def _short(value: Any, max_chars: int) -> str:
    if not isinstance(value, str):
        return ''
    return ' '.join(value.split())[:max_chars]


def compose_report(matrix: dict[str, Any], *, vacancy_title: str = '',
                   candidate_label: str = '', today: date | None = None) -> dict[str, Any]:
    """Преобразует проверенную матрицу в нейтральный отчет.

    Не строит «оценку кандидата» и не выводит рекомендацию о найме.
    """
    if not isinstance(matrix, dict) or matrix.get('version') != '0.7':
        raise ReportError('Для отчёта требуется доказательная матрица v0.7')
    raw_rows = matrix.get('rows')
    if not isinstance(raw_rows, list) or len(raw_rows) > 500:
        raise ReportError('Неподдерживаемый размер матрицы')

    rows: list[dict[str, Any]] = []
    for original in raw_rows:
        if not isinstance(original, dict):
            raise ReportError('Некорректная строка матрицы')
        category, status = original.get('category'), original.get('status')
        if category not in CATEGORY_LABELS or status not in STATUS_LABELS:
            raise ReportError('Неизвестный тип требования или статус')
        original_proofs = original.get('resume_evidence') or []
        if not isinstance(original_proofs, list) or len(original_proofs) > 50:
            raise ReportError('Некорректные цитаты резюме')
        proofs = []
        for evidence in original_proofs:
            if not isinstance(evidence, dict) or evidence.get('source_verified') is not True:
                continue
            quote = _short(evidence.get('quote'), 2000)
            if quote:
                proofs.append({'quote': quote, 'page': evidence.get('page'),
                               'method': _short(evidence.get('method'), 90)})
        vacancy_evidence = original.get('vacancy_evidence')
        vac_quote = ''
        if isinstance(vacancy_evidence, dict) and vacancy_evidence.get('source_verified') is True:
            vac_quote = _short(vacancy_evidence.get('quote'), 2000)
        if status not in ('not_run', 'invalid_source') and not vac_quote:
            # Сломанная ссылка на вакансию не может выглядеть положительным доказательством.
            status = 'invalid_source'
        # Положительные и предварительные статусы нельзя печатать без цитаты резюме.
        if status in ('exact_mention', 'semantic_proposal', 'partial_proposal', 'duration_provisional') and not proofs:
            status = 'insufficient_evidence'
        rows.append({
            'id': _short(original.get('id'), 30), 'category': category,
            'category_label': CATEGORY_LABELS[category],
            'requirement': _short(original.get('requirement'), 500),
            'status': status, 'status_label': STATUS_LABELS[status],
            'method': _short(original.get('method'), 120),
            'detail': _short(original.get('detail'), 750),
            'vacancy_quote': vac_quote,
            'resume_quotes': proofs,
            'required_months': original.get('required_months') if type(original.get('required_months')) is int else None,
            'documented_months': original.get('documented_months') if type(original.get('documented_months')) is int else None,
        })
    rag_raw = matrix.get('rag_observations') or []
    if not isinstance(rag_raw, list) or len(rag_raw) > 30:
        raise ReportError('Некорректные RAG-наблюдения')
    rag = []
    for observation in rag_raw:
        if not isinstance(observation, dict):
            continue
        quotes = []
        citations = observation.get('citations') or []
        if not isinstance(citations, list):
            continue
        for citation in citations[:10]:
            if not isinstance(citation, dict) or citation.get('source_verified') is not True:
                continue
            side = citation.get('document_type')
            if side not in ('resume', 'vacancy'):
                continue
            quoted = _short(citation.get('quote'), 1500)
            if quoted:
                quotes.append({'document_type': side, 'quote': quoted})
        # Минимум один источник именно из резюме.
        if any(q['document_type'] == 'resume' for q in quotes):
            rag.append({'statement': _short(observation.get('statement'), 500),
                        'citations': quotes, 'status': 'Ручная проверка', 'affects_score': False})

    statuses = Counter(r['status'] for r in rows)
    required = [r for r in rows if r['category'] == 'required_skill']
    exact = sum(r['status'] == 'exact_mention' for r in required)
    # НЕ называем это вероятностью найма или оценкой кандидата.
    uncertain = any(r['status'] in ('manual_review', 'invalid_source') for r in required)
    mention_percent = round(100 * exact / len(required)) if required and not uncertain else None
    duration = [r for r in rows if r['category'] == 'experience']
    pending = statuses['not_run']
    needs_review = sum(statuses[s] for s in REVIEW_STATUSES) + len(rag)
    conclusion = [
        f'В резюме дословно упомянуты {exact} из {len(required)} обязательных навыков вакансии.'
        if required else 'В вакансии не выделены обязательные навыки для подсчёта упоминаний.',
        f'Требований к стажу: {len(duration)}; предварительно достаточный срок: '
        f'{statuses["duration_provisional"]}. Даты и привязку технологии к работе необходимо проверить.',
        f'Для ручной проверки: {needs_review} выводов/наблюдений; не выполнено проверок: {pending}.',
        'Отсутствие подтверждения не означает отсутствия навыка. Решение о соответствии и найме принимает человек.',
    ]
    return {
        'version': '0.8',
        'report_date': (today or date.today()).isoformat(),
        'candidate_label': _short(candidate_label, 120) or 'Не указано',
        'vacancy_title': _short(vacancy_title, 160) or 'Выбранная вакансия',
        'overview': {
            'total_requirements': len(rows),
            'required_skills': len(required),
            'literal_mentions': exact,
            'literal_mention_percent': mention_percent,
            'duration_requirements': len(duration),
            'duration_provisional': statuses['duration_provisional'],
            'pending_checks': pending,
            'review_items': needs_review,
            'rag_observations': len(rag),
        },
        'rows': rows,
        'rag_observations': rag,
        'conclusion': conclusion,
        'notes': [
            'Показатель дословных упоминаний - не оценка компетентности и не вероятность трудоустройства.',
            'Статусы LLM/RAG и достаточность стажа предварительные. Истинность утверждений требует проверки человеком.',
            'Цитаты сверены локально с загруженным исходным резюме и текстом вакансии при построении матрицы v0.7.',
            'Этот отчет сформирован локально и не требует нового обращения к OpenAI API.',
        ],
    }


def _font_files() -> tuple[str, str]:
    """Системные TTF с кириллицей. Файлы шрифтов в проект не включаются."""
    locations = [
        (r'C:\Windows\Fonts\arial.ttf', r'C:\Windows\Fonts\arialbd.ttf'),
        (r'C:\Windows\Fonts\segoeui.ttf', r'C:\Windows\Fonts\segoeuib.ttf'),
        ('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
         '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'),
        ('/usr/local/share/fonts/DejaVuSans.ttf',
         '/usr/local/share/fonts/DejaVuSans-Bold.ttf'),
        ('/System/Library/Fonts/Supplemental/Arial.ttf',
         '/System/Library/Fonts/Supplemental/Arial Bold.ttf'),
    ]
    for normal, bold in locations:
        if Path(normal).is_file() and Path(bold).is_file():
            return normal, bold
    raise ReportError('Не найден системный TTF-шрифт с кириллицей (Arial/Segoe UI/DejaVu Sans)')


def render_pdf(report: dict[str, Any]) -> bytes:
    """PDF в памяти; без файлового сохранения, сети и исполнения HTML из документов."""
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import HRFlowable, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    normal, bold = _font_files()
    if 'ResumeMatchReportSans' not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont('ResumeMatchReportSans', normal))
    if 'ResumeMatchReportSansBold' not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont('ResumeMatchReportSansBold', bold))

    navy = colors.HexColor('#17345c')
    ink = colors.HexColor('#26374b')
    muted = colors.HexColor('#627186')
    line = colors.HexColor('#e0e8f1')
    bg = colors.HexColor('#f2f6fb')
    accent = colors.HexColor('#2459b0')
    body_style = ParagraphStyle('RMbody', fontName='ResumeMatchReportSans', fontSize=9.4,
                                leading=14, textColor=ink, spaceAfter=6, splitLongWords=1, wordWrap='CJK')
    small_style = ParagraphStyle('RMsmall', parent=body_style, fontSize=8.3, leading=12, textColor=muted)
    label_style = ParagraphStyle('RMlabel', parent=body_style, fontSize=9, leading=13,
                                 fontName='ResumeMatchReportSansBold', textColor=navy)
    title_style = ParagraphStyle('RMtitle', parent=body_style, fontSize=20, leading=26,
                                 fontName='ResumeMatchReportSansBold', textColor=navy, spaceAfter=10)
    h_style = ParagraphStyle('RMhead', parent=label_style, fontSize=13, leading=18, spaceBefore=14, spaceAfter=8)
    status_style = ParagraphStyle('RMstatus', parent=body_style, fontSize=8.5, leading=12,
                                  fontName='ResumeMatchReportSansBold', textColor=accent)

    def p(value: Any, style=body_style) -> Paragraph:
        # Escape: quotes and names are untrusted text, never ReportLab markup.
        text = escape(_short(value, 2500), quote=True) or '—'
        return Paragraph(text, style)

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=46, rightMargin=46,
                            topMargin=55, bottomMargin=50,
                            title='ResumeMatch AI - отчёт о соответствии', author='ResumeMatch AI')
    story = [p('ResumeMatch AI / Отчёт по вакансии', title_style),
             p('Доказательный отчёт v0.8 · ' + report['report_date'], small_style),
             Spacer(1, 12),
             p('Вакансия: ' + report['vacancy_title'], label_style),
             p('Кандидат: ' + report['candidate_label'], body_style),
             HRFlowable(width='100%', thickness=1, color=line), Spacer(1, 14)]

    overview = report['overview']
    def tile(label: str, value: str) -> list[Paragraph]:
        return [p(value, label_style), p(label, small_style)]
    cells = [
        [tile('Обязательных навыков', str(overview['required_skills'])),
         tile('Дословных упоминаний', f"{overview['literal_mentions']} / {overview['required_skills']}")],
        [tile('Ручных проверок', str(overview['review_items'])),
         tile('Не запущено проверок', str(overview['pending_checks']))],
    ]
    grid = Table(cells, colWidths=[250, 250], hAlign='LEFT')
    grid.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), bg),
        ('BOX', (0, 0), (-1, -1), .5, line),
        ('INNERGRID', (0, 0), (-1, -1), .5, line),
        ('LEFTPADDING', (0, 0), (-1, -1), 14),
        ('RIGHTPADDING', (0, 0), (-1, -1), 14),
        ('TOPPADDING', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
    ]))
    story += [grid, Spacer(1, 10)]
    share = overview.get('literal_mention_percent')
    story.append(p('Доля дословных упоминаний обязательных навыков: '
                   + (f'{share}%' if share is not None else 'не рассчитывается'), label_style))
    story.append(p('Это не итоговая оценка квалификации или вероятность найма.', small_style))
    story.append(p('Итоговое заключение', h_style))
    for sentence in report['conclusion']:
        story.append(p('• ' + sentence))

    for category, heading in CATEGORY_LABELS.items():
        group = [r for r in report['rows'] if r['category'] == category]
        if not group:
            continue
        story.append(p(heading, h_style))
        for row in group:
            block = [p(f"{row['id'] or '—'} · {row['requirement']}", label_style),
                     p(row['status_label'], status_style)]
            if category == 'experience' and row['required_months'] is not None:
                documented = row['documented_months']
                block.append(p(f"Требуется: {row['required_months']} мес. · Документировано: "
                               + (str(documented) + ' мес.' if documented is not None else 'нет данных'), small_style))
            if row['detail']:
                block.append(p(row['detail'], small_style))
            block.append(p('Цитата вакансии: ' + (row['vacancy_quote'] or 'не подтверждена'), small_style))
            if row['resume_quotes']:
                for quote in row['resume_quotes'][:4]:
                    page = (' · стр. ' + str(quote['page'])) if quote.get('page') is not None else ''
                    block.append(p('Цитата резюме' + page + ': «' + quote['quote'] + '»', small_style))
                if len(row['resume_quotes']) > 4:
                    block.append(p(f"Ещё {len(row['resume_quotes']) - 4} цитат доступны в интерактивной матрице.", small_style))
            else:
                block.append(p('Проверяемых цитат резюме нет.', small_style))
            block.extend([Spacer(1, 8), HRFlowable(width='100%', thickness=.4, color=line), Spacer(1, 6)])
            # Короткие карточки не разрываются между страницами; длинные
            # корректно переносятся отдельными абзацами.
            estimate = (len(row['requirement']) + len(row['detail']) + len(row['vacancy_quote'])
                        + sum(len(q['quote']) for q in row['resume_quotes'][:4]))
            if estimate < 1100:
                story.append(KeepTogether(block))
            else:
                story.append(KeepTogether(block[:2]))
                story.extend(block[2:])

    if report['rag_observations']:
        story.append(p('RAG-наблюдения (не влияют на процент)', h_style))
        for item in report['rag_observations']:
            story.append(p(item['statement'], label_style))
            for citation in item['citations'][:4]:
                label = 'Резюме' if citation['document_type'] == 'resume' else 'Вакансия'
                story.append(p(label + ': «' + citation['quote'] + '»', small_style))
            story.append(p('Интерпретация требует проверки человеком.', small_style))
            story.append(Spacer(1, 5))

    story.append(p('Методология и ограничения', h_style))
    for note in report['notes']:
        story.append(p('• ' + note, small_style))

    def footer(canvas, pdf_doc):
        canvas.saveState()
        canvas.setStrokeColor(line)
        canvas.line(46, 38, A4[0]-46, 38)
        canvas.setFont('ResumeMatchReportSans', 8)
        canvas.setFillColor(muted)
        canvas.drawString(46, 24, 'ResumeMatch AI · v0.8 · Локальный отчёт')
        canvas.drawRightString(A4[0]-46, 24, str(pdf_doc.page))
        canvas.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buffer.getvalue()
