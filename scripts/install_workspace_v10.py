"""Install the optional, encrypted local workspace v1.0 on ResumeMatch AI v0.9.

Idempotent, with pre-flight checks and local backups. Does not alter .env.
Run: python scripts/install_workspace_v10.py from the project root.
"""
from __future__ import annotations

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def insert_once(text: str, needle: str, replacement: str, marker: str, filename: str) -> str:
    if marker in text:
        return text
    if text.count(needle) != 1:
        raise SystemExit(f'Не найден единственный ориентир {marker} в {filename}; ничего не изменено')
    return text.replace(needle, replacement, 1)


def install() -> list[str]:
    required = [
        'app/main.py', 'app/batch_v09.py', 'app/batch_v09_api.py',
        'app/report_v08.py', 'app/report_v08_api.py',
        'app/workspace_v10.py', 'app/workspace_v10_api.py',
        'assets/workspace_v10.html', 'assets/workspace_v10.css',
        'assets/workspace_v10.js', 'static/index.html',
        'requirements.txt', '.gitignore', '.env.example', 'README.md',
    ]
    missing = [name for name in required if not (ROOT / name).is_file()]
    if missing:
        raise SystemExit('Не найдены файлы: ' + ', '.join(missing))
    targets = ['app/main.py', 'static/index.html', 'requirements.txt',
               '.gitignore', '.env.example', 'README.md']
    before = {name: (ROOT / name).read_text(encoding='utf-8') for name in targets}

    main = before['app/main.py']
    main = insert_once(main,
        'from .batch_v09_api import router as batch_router',
        'from .batch_v09_api import router as batch_router\nfrom .workspace_v10_api import router as workspace_router',
        'from .workspace_v10_api import router as workspace_router', 'app/main.py')
    main = insert_once(main,
        'app.include_router(batch_router)',
        'app.include_router(batch_router)\napp.include_router(workspace_router)',
        'app.include_router(workspace_router)', 'app/main.py')

    page = before['static/index.html']
    if 'BATCH_V09_JS_START' not in page or 'REPORT_V08_JS_START' not in page:
        raise SystemExit('Не найдены блоки v0.8/v0.9 в интерфейсе; установка остановлена')
    css = (ROOT / 'assets/workspace_v10.css').read_text(encoding='utf-8')
    markup = (ROOT / 'assets/workspace_v10.html').read_text(encoding='utf-8')
    js = (ROOT / 'assets/workspace_v10.js').read_text(encoding='utf-8')
    page = insert_once(page, '</style>', css + '\n  </style>',
                       'WORKSPACE_V10_CSS_START', 'static/index.html')
    page = insert_once(page,
        '      <!-- JSON базового извлечения -->',
        markup + '\n      <!-- JSON базового извлечения -->',
        'WORKSPACE_V10_HTML_START', 'static/index.html')
    page = insert_once(page,
        "    $('form').addEventListener('submit', runLocalAnalysis);",
        js + "\n    $('form').addEventListener('submit', runLocalAnalysis);",
        'WORKSPACE_V10_JS_START', 'static/index.html')

    req = before['requirements.txt']
    if not any(line.strip().startswith('cryptography') for line in req.splitlines()):
        req = req.rstrip() + '\n\n# v1.0: шифрование локальной истории в SQLite\ncryptography>=44,<48\n'

    ignore = before['.gitignore']
    if 'data/' not in ignore.splitlines():
        ignore = ignore.rstrip() + '\n\n# Локальная база истории с конфиденциальными данными\ndata/\n'
    if '*.before_workspace_v10' not in ignore:
        ignore = ignore.rstrip() + '\n*.before_workspace_v10\n'

    env = before['.env.example']
    if 'RESUMEMATCH_HISTORY_KEY=' not in env:
        env = env.rstrip() + ("\n\n# v1.0: обязательно сгенерируйте собственные значения в локальном .env\n"
                               "RESUMEMATCH_WORKSPACE_TOKEN=\n"
                               "RESUMEMATCH_HISTORY_KEY=\n"
                               "RESUMEMATCH_RETENTION_DAYS=30\n"
                               "RESUMEMATCH_DB_PATH=data/resumematch_history.sqlite3\n")

    readme = before['README.md']
    if '<!-- WORKSPACE_V10_START -->' not in readme:
        readme += ("\n\n<!-- WORKSPACE_V10_START -->\n"
                   "## Локальная история и управление данными (v1.0)\n\n"
                   "Добровольное сохранение зашифрованных снимков одиночных PDF-отчётов и "
                   "пакетных матриц в SQLite, работа с карточками кандидатов и вакансий, "
                   "просмотр и удаление истории, TTL 30 дней по умолчанию. "
                   "Оригиналы PDF/DOCX/TXT не сохраняются. "
                   "Только для локального single-user запуска на 127.0.0.1. "
                   "[Инструкция по настройке](README_WORKSPACE_v1.0.md).\n"
                   "<!-- WORKSPACE_V10_END -->\n")
    updated = {'app/main.py': main, 'static/index.html': page,
               'requirements.txt': req, '.gitignore': ignore,
               '.env.example': env, 'README.md': readme}
    changes = {name: new for name, new in updated.items() if new != before[name]}
    for filename in changes:
        source = ROOT / filename
        backup = source.with_name(source.name + '.before_workspace_v10')
        if not backup.exists():
            shutil.copy2(source, backup)
    for filename, content in changes.items():
        (ROOT / filename).write_text(content, encoding='utf-8')
        print('Обновлено:', filename)
    if not changes:
        print('v1.0 уже установлена: изменений не требуется')
    return list(changes)


if __name__ == '__main__':
    install()
    print('Готово. Настройте секреты в .env, установите зависимости и запустите тесты.')
