# ResumeMatch AI v0.6.1 — совместимость RAG с разными версиями llm.py

Исправлена ошибка импорта:
`ImportError: cannot import name 'vacancy_blocks' from 'app.llm'`.

`app/rag.py` теперь сам формирует блоки вакансии из `key_skills` и
`description_text` и не импортирует `vacancy_blocks` из `app.llm`.

## Установка (PowerShell)

1. `cd F:\MATRIX`
2. `Copy-Item .\app\rag.py .\app\rag.py.bak`
3. Распакуйте архив в `F:\MATRIX` с заменой **только** `app/rag.py`.
4. ` .\.venv\Scripts\python.exe -m pytest -q`
5. ` .\.venv\Scripts\python.exe scripts\check_faiss_v06.py`

Никаких платных вызовов OpenAI при запуске тестов нет.
Не меняйте `app/llm.py`; все остальные модули v0.6 остаются как были.

Патч протестирован на копии проекта: 76 passed, 1 skipped.
Дополнительная проверка при отсутствии функции в llm.py: 10 passed.
