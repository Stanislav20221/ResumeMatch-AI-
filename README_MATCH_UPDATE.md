# ResumeMatch AI — LLM-матрица v0.3

Локальное сопоставление **уже полученных** JSON из `/api/llm/resume` и `/api/llm/vacancy`.

## Файлы обновления

- `app/llm_matching.py` — детерминированное сопоставление навыков + работа с цитатами.
- `app/llm_match_api.py` — endpoint `POST /api/llm/match`.
- `static/index.html` — предыдущий интерфейс с дополнительной матрицей после LLM-анализа.
- `tests/test_llm_matching.py` — 10 офлайн-тестов.

В архиве **нет** `main.py`, `.env`, `.venv`, API-ключей и любых пользовательских данных.

## Установка в `F:\MATRIX`

1. Остановить Uvicorn (`Ctrl+C`).
2. Сделать резервную копию:

```powershell
Copy-Item F:\MATRIX\static\index.html F:\MATRIX\static\index.backup.html
Copy-Item F:\MATRIX\app\main.py F:\MATRIX\app\main.backup.py
```

3. Распаковать **содержимое** архива в `F:\MATRIX`, с заменой `static/index.html`. Не удалять другие файлы проекта.
4. В `app/main.py` в блоке импортов добавить:

```python
from .llm_match_api import router as llm_match_router
```

5. В `app/main.py` сразу после `app = FastAPI(...)` добавить:

```python
app.include_router(llm_match_router)
```

Не удалять ранее добавленный `app.include_router(llm_router)` для резюме/вакансий.

6. Запустить тесты и сервер:

```powershell
cd F:\MATRIX
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8765
```

7. Открыть `http://127.0.0.1:8765/docs` и убедиться, что добавился `POST /api/llm/match`.
8. Обновить браузер `Ctrl+F5`. Запустить старый анализ и затем LLM-анализ с разрешением на отправку тестовых данных в OpenAI.

## Логика расчёта

- Каждый подтверждённый обязательный навык считается один раз.
- `source_verified` у требований и навыков резюме должен быть `true`; дополнительно проверяется, что цитата содержит название навыка или его известный синоним.
- Поскольку `/match` получает JSON от клиента, а не исходный документ, **самостоятельной повторной проверки цитат по исходному файлу нет**. Доверие к `source_verified` зависит от предыдущего этапа извлечения.
- Если в обязательных требованиях есть цитаты, требующие проверки, процент скрывается (`null`).
- Желаемые навыки, стаж, обязанности и условия **не входят в процент**. Их оцениваем отдельно.
- Не подтверждено в резюме ≠ кандидат не владеет навыком.
- Семантическое сопоставление и проверка квалификации — будущий этап.

## Пример прямого запроса к новому endpoint

```json
{
  "resume": {
    "fields": {"skills": [{"value": "Python", "source_text": "Python", "source_verified": true}]}
  },
  "vacancy": {
    "fields": {"required_skills": [{"value": "Python", "source_text": "Требования: Python", "source_verified": true}]}
  }
}
```

Ожидается `score_percent: 100`.

## Проверка в изолированной копии

При наложении обновления на ранее созданную структуру ResumeMatch AI было пройдено **34 офлайн-теста** без внешних API-запросов.
