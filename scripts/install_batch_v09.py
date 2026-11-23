"""Подключение пакетного сравнительного режима v0.9 поверх v0.8.

Повторный запуск безопасен. Перед изменениями сохраняются локальные копии.
"""
from __future__ import annotations

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def add_once(source: str, anchor: str, replacement: str, marker: str, filename: str) -> str:
    if marker in source:
        return source
    if source.count(anchor) != 1:
        raise SystemExit(f'Нельзя безопасно изменить {filename}: не найден единственный ориентир {marker}')
    return source.replace(anchor, replacement, 1)


def main() -> None:
    required = [
        'app/evidence_matrix.py', 'app/report_v08.py', 'app/batch_v09.py',
        'app/batch_v09_api.py', 'assets/batch_v09.html', 'assets/batch_v09.css',
        'assets/batch_v09.js', 'tests/test_batch_v09.py',
    ]
    for item in required:
        if not (ROOT / item).is_file():
            raise SystemExit(f'Отсутствует файл: {item}. Распакуй архив в корень проекта.')
    names = ['app/main.py', 'static/index.html', '.gitignore', 'README.md']
    originals = {name: (ROOT / name).read_text(encoding='utf-8') for name in names}

    main_src = originals['app/main.py']
    main_src = add_once(
        main_src,
        'from .report_v08_api import router as report_router',
        'from .report_v08_api import router as report_router\nfrom .batch_v09_api import router as batch_router',
        'from .batch_v09_api import router as batch_router', 'app/main.py',
    )
    main_src = add_once(
        main_src,
        'app.include_router(report_router)',
        'app.include_router(report_router)\napp.include_router(batch_router)',
        'app.include_router(batch_router)', 'app/main.py',
    )

    page = originals['static/index.html']
    css = (ROOT / 'assets/batch_v09.css').read_text(encoding='utf-8')
    markup = (ROOT / 'assets/batch_v09.html').read_text(encoding='utf-8')
    js = (ROOT / 'assets/batch_v09.js').read_text(encoding='utf-8')
    page = add_once(page, '</style>', css + '\n  </style>',
                    'BATCH_V09_CSS_START', 'static/index.html')
    anchor = '      <!-- JSON базового извлечения -->'
    page = add_once(page, anchor, markup + '\n' + anchor,
                    'BATCH_V09_HTML_START', 'static/index.html')
    anchor = "    $('form').addEventListener('submit', runLocalAnalysis);"
    page = add_once(page, anchor, js + '\n' + anchor,
                    'BATCH_V09_JS_START', 'static/index.html')
    anchor = '        renderResults(data);'
    page = add_once(page, anchor, anchor + '\n        batchPopulateVacancies();',
                    '        batchPopulateVacancies();', 'static/index.html')

    gitignore = originals['.gitignore']
    if '*.before_batch_v09' not in gitignore:
        gitignore += '\n# Резервные копии установщика v0.9\n*.before_batch_v09\n'
    readme = originals['README.md']
    if '<!-- BATCH_V09_README_START -->' not in readme:
        readme += (
            '\n\n<!-- BATCH_V09_README_START -->\n'
            '## Пакетный анализ резюме (v0.9)\n\n'
            'По одной выбранной вакансии можно сравнить до пяти резюме. Извлечение '
            'по каждому выполняется через OpenAI только при отдельном согласии; '
            'проверка датированного опыта доступна дополнительно. Все цитаты '
            'перепроверяются по соответствующим документам локально. '
            'Кандидаты не ранжируются, автоматического кадрового решения нет. '
            'Доступен локальный PDF каждого кандидата через v0.8.\n\n'
            'API: `POST /api/batch/compare`. '
            'См. [README_BATCH_v0.9.md](README_BATCH_v0.9.md).\n'
            '<!-- BATCH_V09_README_END -->\n'
        )
    updates = {'app/main.py': main_src, 'static/index.html': page,
               '.gitignore': gitignore, 'README.md': readme}
    changes = {name: value for name, value in updates.items() if originals[name] != value}
    # Все изменения вычислены заранее; если якоря не найдены, работа прерывается до записи.
    for name in changes:
        path = ROOT / name
        backup = path.with_name(path.name + '.before_batch_v09')
        if not backup.exists():
            shutil.copy2(path, backup)
    for name, value in changes.items():
        (ROOT / name).write_text(value, encoding='utf-8')
        print('Обновлено:', name)
    if not changes:
        print('v0.9 уже установлена: дополнительных изменений нет')
    print('Установка завершена. Теперь запусти pytest и Uvicorn.')


if __name__ == '__main__':
    main()
