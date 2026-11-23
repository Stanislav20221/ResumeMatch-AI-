# ResumeMatch AI — исправление явных навыков (RAG)

## Что исправляется

Старый `app/llm_matching.py` сопоставлял **только `value`** из извлечённых LLM фактов.
Если модель вернула `value="FAISS"` и подтверждённый `source_text="RAG, FAISS, LangChain, ..."`,
навык **RAG терялся**, хотя явно указан рядом с FAISS.

Новая версия при построении матрицы использует также **строгое явное перечисление** в ранее проверенных цитатах
категории `skills`. Пример `RAG, FAISS, LangChain` → отдельные имена навыков.
Новые имена не добавляются в JSON оригинального LLM-извлечения, но могут быть найдены
на этапе точного сопоставления. В результате появляется поле `recovered_explicit_skills`.

Это не свободное семантическое сопоставление. Фразы вида «не работал с RAG» не засчитываются.
Само упоминание в разделе `projects` автоматически тоже не засчитывается, если не было
подтверждения в `skills`: для такого случая остаётся семантический анализ и проверка человеком.

`source_verified: true` на этапе `/api/llm/match` по-прежнему принимается из предыдущего извлечения;
эндпоинт не перечитывает резюме. Название навыка не доказывает длительность или уровень опыта.

## Установка в F:\MATRIX

1. Остановить Uvicorn через `Ctrl+C`.
2. В PowerShell сделать резервную копию существующего модуля:

```powershell
cd F:\MATRIX
Copy-Item .\app\llm_matching.py .\app\llm_matching.backup.py
```

3. Распаковать **содержимое** ZIP в `F:\MATRIX`, сохранив папки `app` и `tests`.
   Заменить только `app/llm_matching.py`. Файлы `app/llm.py`, `app/llm_semantic.py`,
   `static/index.html`, `.env`, `app/main.py` не изменять.
4. Запустить локальную проверку:

```powershell
.\.venv\Scripts\python.exe check_rag_fix.py
.\.venv\Scripts\python.exe -m pytest -q tests/test_llm_matching_rag_regression.py
.\.venv\Scripts\python.exe -m pytest -q
```

5. Запустить ранее настроенный сервер:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8765
```

6. В браузере повторить LLM-извлечение и построение матрицы.
   Если RAG содержится в одной из ранее проверенных **строк-перечней** категории `skills`,
   он должен отображаться как совпадение по перечню, без отдельного LLM-предложения.
   При любых изменениях формы обязательно запустить анализ повторно, чтобы не использовать старые JSON.

## Ожидаемый вывод `check_rag_fix.py`

```text
Доля точных совпадений: 100 %
Навыки, восстановленные из перечня: ['RAG']
RAG -> matched / literal_in_verified_skill_list
FAISS -> matched / exact_or_known_alias
RAG REGRESSION FIX PASSED
```

Локальный тестовый скрипт не отправляет ничего в OpenAI.
