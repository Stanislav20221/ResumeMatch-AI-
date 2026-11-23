"""Безопасное идемпотентное подключение evidence matrix v0.7 к текущей v0.6.1."""
from __future__ import annotations

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def edit(path: Path, old: str, new: str, marker: str) -> None:
    text = path.read_text(encoding='utf-8')
    if marker in text:
        print('Уже установлено:', path.relative_to(ROOT))
        return
    if text.count(old) != 1:
        raise SystemExit(f'Неоднозначная структура {path}; обновление не применено')
    backup = path.with_name(path.name + '.before_evidence_v07')
    if not backup.exists():
        shutil.copy2(path, backup)
    path.write_text(text.replace(old, new, 1), encoding='utf-8')
    print('Обновлено:', path.relative_to(ROOT))


def main():
    for path in ('app/evidence_matrix.py', 'app/evidence_matrix_api.py', 'tests/test_evidence_matrix.py'):
        if not (ROOT / path).is_file():
            raise SystemExit(f'Не найден файл из архива: {path}')
    main_file = ROOT / 'app/main.py'
    edit(main_file, 'from .rag_api import router as rag_router',
         'from .rag_api import router as rag_router\nfrom .evidence_matrix_api import router as evidence_router',
         'from .evidence_matrix_api import router as evidence_router')
    edit(main_file, 'app.include_router(rag_router)',
         'app.include_router(rag_router)\napp.include_router(evidence_router)',
         'app.include_router(evidence_router)')

    html = ROOT / 'static/index.html'
    css = (ROOT / 'assets/evidence.css').read_text(encoding='utf-8')
    markup = (ROOT / 'assets/evidence.html').read_text(encoding='utf-8')
    js = (ROOT / 'assets/evidence.js').read_text(encoding='utf-8')
    edit(html, '</style>', css + '\n  </style>', 'EVIDENCE_V07_CSS_START')
    anchor = '          </section>\n        </div>\n      </div>\n\n      <p class="notice">'
    edit(html, anchor,
         '          </section>\n' + markup + '        </div>\n      </div>\n\n      <p class="notice">',
         'EVIDENCE_V07_HTML_START')
    edit(html, "    $('form').addEventListener('submit', runLocalAnalysis);",
         js + "\n    $('form').addEventListener('submit', runLocalAnalysis);",
         'EVIDENCE_V07_JS_START')

    # RAG-вывод относится к выбранной вакансии, а не к произвольному индексу.
    # Не пересчитываем процент и не превращаем наблюдения RAG в автоматический verdict.
    edit(html, '    function ragReset() {',
         '    function ragReset() {\n      if (latest?.llm) delete latest.llm.rag;',
         'function ragReset() {\n      if (latest?.llm) delete latest.llm.rag;')
    edit(html, "        ragSessionId = result.session_id;",
         "        if (latest?.llm) delete latest.llm.rag;\n        ragSessionId = result.session_id;",
         'if (latest?.llm) delete latest.llm.rag;')
    edit(html, "        if (ask) {\n          const target = $('rag-answer');",
         "        if (ask && latest?.llm?.vacancy_id === vacancy.id && "
         "ragSnapshot === getCurrentInputSnapshot() && ragSelectedVacancyId === vacancy.id) {\n"
         "          latest.llm.rag = result;\n        }\n"
         "        if (ask) {\n          const target = $('rag-answer');",
         'latest.llm.rag = result;')
    ignore_file = ROOT / '.gitignore'
    if ignore_file.is_file():
        ignore = ignore_file.read_text(encoding='utf-8')
        if '*.before_evidence_v07' not in ignore:
            ignore_file.write_text(ignore.rstrip() + '\n\n# Резервные копии установщика v0.7\n*.before_evidence_v07\n', encoding='utf-8')
    print('Готово. Перезапусти приложение и запусти pytest.')


if __name__ == '__main__':
    main()
