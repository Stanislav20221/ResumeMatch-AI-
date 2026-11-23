"""Идемпотентная установка локального PDF-отчёта v0.8 поверх v0.7."""
from __future__ import annotations

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(text: str, needle: str, replacement: str, marker: str, filename: str) -> str:
    if marker in text:
        return text
    if text.count(needle) != 1:
        raise SystemExit(f'Нельзя безопасно изменить {filename}: ожидалось одно место вставки для {marker}')
    return text.replace(needle, replacement, 1)


def main() -> None:
    for path in (
        'app/evidence_matrix.py', 'app/evidence_matrix_api.py',
        'app/report_v08.py', 'app/report_v08_api.py',
        'assets/report.html', 'assets/report.css', 'assets/report.js',
        'tests/test_report_v08.py',
    ):
        if not (ROOT / path).is_file():
            raise SystemExit(f'Нет обязательного файла: {path}. Сначала распакуй архив в корень F:\\MATRIX')
    inputs = {name: (ROOT / name).read_text(encoding='utf-8')
              for name in ('app/main.py', 'static/index.html', 'requirements.txt', '.gitignore', 'README.md')}

    main_src = inputs['app/main.py']
    main_src = replace_once(
        main_src,
        'from .evidence_matrix_api import router as evidence_router',
        'from .evidence_matrix_api import router as evidence_router\nfrom .report_v08_api import router as report_router',
        'from .report_v08_api import router as report_router', 'app/main.py',
    )
    main_src = replace_once(
        main_src, 'app.include_router(evidence_router)',
        'app.include_router(evidence_router)\napp.include_router(report_router)',
        'app.include_router(report_router)', 'app/main.py',
    )

    html = inputs['static/index.html']
    css = (ROOT / 'assets/report.css').read_text(encoding='utf-8')
    markup = (ROOT / 'assets/report.html').read_text(encoding='utf-8')
    js = (ROOT / 'assets/report.js').read_text(encoding='utf-8')
    html = replace_once(html, '</style>', css + '\n  </style>', 'REPORT_V08_CSS_START', 'static/index.html')
    anchor = '          <!-- EVIDENCE_V07_HTML_END -->'
    html = replace_once(html, anchor, anchor + '\n' + markup,
                        'REPORT_V08_HTML_START', 'static/index.html')
    anchor = "    $('form').addEventListener('submit', runLocalAnalysis);"
    html = replace_once(html, anchor, js + '\n' + anchor,
                        'REPORT_V08_JS_START', 'static/index.html')

    requirements = inputs['requirements.txt']
    if not any(line.strip().lower().startswith('reportlab') for line in requirements.splitlines()):
        requirements = requirements.rstrip() + '\n# v0.8: локальный PDF-экспорт\nreportlab>=4.4,<5\n'
    ignore = inputs['.gitignore']
    if '*.before_report_v08' not in ignore:
        ignore = ignore.rstrip() + '\n\n# Резервные копии установщика отчётов v0.8\n*.before_report_v08\n'
    readme = inputs['README.md']
    if '<!-- REPORT_V08_README_START -->' not in readme:
        readme += (
            '\n\n<!-- REPORT_V08_README_START -->\n'
            '## Итоговый отчёт и PDF (v0.8)\n\n'
            'Сервер повторно строит доказательную матрицу v0.7 по исходному резюме и вакансии, '
            'затем формирует локальный PDF с цитатами, статусами и нейтральным заключением. '
            'Новых вызовов OpenAI нет. Совпадение названия навыка не доказывает компетентность; '
            'выводы LLM и RAG требуют ручной проверки.\n\n'
            'Маршруты: `POST /api/report/preview` и `POST /api/report/pdf`. '
            'Подробности: [README_REPORT_v0.8.md](README_REPORT_v0.8.md).\n'
            '<!-- REPORT_V08_README_END -->\n'
        )

    updates = {
        'app/main.py': main_src, 'static/index.html': html,
        'requirements.txt': requirements, '.gitignore': ignore,
        'README.md': readme,
    }
    changed = [(name, data) for name, data in updates.items() if inputs[name] != data]
    for name, _ in changed:
        original = ROOT / name
        backup = original.with_name(original.name + '.before_report_v08')
        if not backup.exists():
            shutil.copy2(original, backup)
    for name, data in changed:
        (ROOT / name).write_text(data, encoding='utf-8')
        print('Обновлено:', name)
    if not changed:
        print('v0.8 уже подключена; дополнительных изменений нет')
    print('Готово. Установи зависимости, затем запусти pytest.')


if __name__ == '__main__':
    main()
