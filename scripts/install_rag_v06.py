"""Safe, repeatable v0.6 installer. Run from the ResumeMatch AI project root."""
from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path.cwd()
MAIN = ROOT / "app" / "main.py"
PAGE = ROOT / "static" / "index.html"
REQUIREMENTS = ROOT / "requirements.txt"
GITIGNORE = ROOT / ".gitignore"
README = ROOT / "README.md"

RAG_HTML = r'''
      <!-- RAG_V06_START -->
      <div class="panel json-panel" id="rag-panel" style="margin:20px 0">
        <h2>Векторный поиск и RAG · FAISS</h2>
        <p class="info">Эмбеддинги OpenAI → временный FAISS-индекс → поиск по фрагментам → ответ LLM с проверенными дословными цитатами. Новые платные запросы выполняются только после согласия.</p>
        <div class="form-grid">
          <div class="field wide">
            <label for="rag-vacancy-select">Вакансия для векторного поиска</label>
            <select id="rag-vacancy-select"></select>
          </div>
          <div class="field wide">
            <label for="rag-question">Вопрос к резюме и вакансии</label>
            <input id="rag-question" maxlength="700" value="Подтверждает ли резюме опыт работы с FastAPI и REST API, который требуется в вакансии?">
          </div>
        </div>
        <label class="consent" for="rag-consent" style="margin-top:16px">
          <input type="checkbox" id="rag-consent">
          <span>Разрешаю отправить текст резюме и вакансии в OpenAI для получения эмбеддингов; также разрешаю отправлять введённые вопросы и найденные фрагменты при выполнении RAG-запросов. Запросы оплачиваются через OpenAI API.</span>
        </label>
        <div class="action">
          <button type="button" id="rag-build">Создать FAISS-индекс</button>
          <span class="hint">Индекс хранится в оперативной памяти сервера до 20 минут, не сохраняется на диск.</span>
        </div>
        <div class="action" style="justify-content:flex-start">
          <button type="button" id="rag-search" disabled>Найти фрагменты</button>
          <button type="button" id="rag-ask" disabled>Спросить RAG (OpenAI)</button>
          <button type="button" class="secondary" id="rag-delete" disabled>Удалить индекс</button>
        </div>
        <p class="info status" id="rag-status" role="status" aria-live="polite"></p>
        <div id="rag-answer" class="hidden"></div>
        <div id="rag-hits" class="hidden"></div>
        <p class="notice">FAISS возвращает семантически близкие фрагменты, но сходство не доказывает выполнение требований. Сервер подтверждает дословные цитаты; выводы LLM требуют ручной проверки.</p>
      </div>
      <!-- RAG_V06_END -->
'''

RAG_JS = r'''
    // RAG_V06_JS_START — изолировано от существующей LLM-матрицы
    let ragSessionId = null;
    let ragSnapshot = null;
    let ragSelectedVacancyId = null;

    function ragStatus(text, error = false) {
      const element = $('rag-status');
      element.textContent = text;
      element.classList.toggle('error-text', error);
    }

    function ragClearResults() {
      $('rag-answer').replaceChildren();
      $('rag-answer').classList.add('hidden');
      $('rag-hits').replaceChildren();
      $('rag-hits').classList.add('hidden');
    }

    function ragReset() {
      if (ragSessionId) {
        // Best effort: server session also has a 20-minute TTL.
        fetch('/api/rag/delete', {
          method: 'POST', headers: {'Content-Type':'application/json'},
          body: JSON.stringify({session_id: ragSessionId})
        }).catch(() => {});
      }
      ragSessionId = null;
      ragSnapshot = null;
      ragSelectedVacancyId = null;
      ['rag-search','rag-ask','rag-delete'].forEach(id => { $(id).disabled = true; });
      ragClearResults();
      ragStatus('');
    }

    function ragPopulateVacancies() {
      const select = $('rag-vacancy-select');
      select.replaceChildren();
      (latest?.matches || []).forEach((item, i) => {
        const option = document.createElement('option');
        option.value = String(i);
        option.textContent = item.vacancy.name || `Вакансия ${i + 1}`;
        select.append(option);
      });
    }

    function ragCheckReady() {
      if (!latest?.matches?.length || analyzedInputSnapshot !== getCurrentInputSnapshot())
        throw new Error('Сначала выполните базовый анализ с актуальными параметрами.');
      if (!$('rag-consent').checked)
        throw new Error('Для новых OpenAI-запросов нужно отдельное согласие.');
      const index = Number($('rag-vacancy-select').value);
      const vacancy = latest.matches[index]?.vacancy;
      if (!vacancy || !$('resume').files[0]) throw new Error('Выберите вакансию и резюме.');
      return vacancy;
    }

    async function ragBuildIndex() {
      const button = $('rag-build');
      button.disabled = true;
      try {
        const vacancy = ragCheckReady();
        ragReset();
        ragStatus('Создаются эмбеддинги и локальный FAISS-индекс...');
        const snapshot = getCurrentInputSnapshot();
        const selectedId = vacancy.id;
        const form = new FormData();
        form.append('resume', $('resume').files[0]);
        form.append('vacancy_description', vacancy.description_text || '');
        form.append('vacancy_key_skills', JSON.stringify(vacancy.key_skills || []));
        form.append('cloud_consent', 'true');
        const result = await getJsonResponse(await fetch('/api/rag/index', {method:'POST', body:form}));
        if (snapshot !== getCurrentInputSnapshot() || latest.matches[Number($('rag-vacancy-select').value)]?.vacancy?.id !== selectedId) {
          fetch('/api/rag/delete', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({session_id:result.session_id})}).catch(() => {});
          throw new Error('Данные изменились во время индексации. Повторите анализ.');
        }
        ragSessionId = result.session_id;
        ragSnapshot = snapshot;
        ragSelectedVacancyId = selectedId;
        ['rag-search','rag-ask','rag-delete'].forEach(id => { $(id).disabled = false; });
        ragStatus(`Готово: ${result.chunks_total} фрагментов, ${result.vector_dimensions} измерений, модель ${result.embedding_model}.`);
      } catch (error) {
        ragStatus(`Ошибка создания индекса: ${error.message}`, true);
      } finally {
        button.disabled = false;
      }
    }

    function ragRenderHits(hits) {
      const target = $('rag-hits');
      target.replaceChildren();
      target.append(make('h3', `Найденные фрагменты (${hits.length})`));
      if (!hits.length) target.append(make('p', 'Подходящих фрагментов не найдено.'));
      hits.forEach(hit => {
        const box = make('div', '', 'experience-card');
        box.append(make('strong', `${hit.chunk_id} · ${hit.document_type === 'resume' ? 'Резюме' : 'Вакансия'} · cos=${hit.similarity}`));
        if (hit.page != null) box.append(make('div', `Страница ${hit.page}`, 'hint'));
        box.append(make('div', hit.text, 'experience-evidence'));
        target.append(box);
      });
      target.classList.remove('hidden');
    }

    async function ragRun(ask) {
      const button = $(ask ? 'rag-ask' : 'rag-search');
      button.disabled = true;
      try {
        const vacancy = ragCheckReady();
        if (!ragSessionId || ragSnapshot !== getCurrentInputSnapshot() || ragSelectedVacancyId !== vacancy.id)
          throw new Error('Индекс устарел. Создайте новый для выбранных документов.');
        const question = $('rag-question').value.trim();
        if (question.length < 3 || question.length > 700) throw new Error('Введите вопрос от 3 до 700 символов.');
        ragClearResults();
        ragStatus(ask ? 'Поиск доказательств и генерация ответа OpenAI...' : 'Поиск по векторам FAISS...');
        const response = await fetch(ask ? '/api/rag/ask' : '/api/rag/search', {
          method:'POST', headers:{'Content-Type':'application/json'},
          body:JSON.stringify({session_id:ragSessionId, question, top_k:6, scope:'both', cloud_consent:true})
        });
        const result = await getJsonResponse(response);
        if (ask) {
          const target = $('rag-answer');
          target.append(make('h3', 'Ответ с источниками'));
          target.append(make('p', result.answer || 'Недостаточно подтверждений.'));
          (result.claims || []).forEach(claim => {
            const card = make('div', '', 'experience-card');
            card.append(make('strong', claim.statement));
            claim.citations.forEach(ref => {
              card.append(make('div', `${ref.chunk_id} · ${ref.document_type === 'resume' ? 'Резюме' : 'Вакансия'}${ref.page ? ' · стр. '+ref.page : ''}: «${ref.quote}»`, 'experience-evidence'));
            });
            target.append(card);
          });
          target.append(make('p', 'Выводы LLM требуют проверки человеком.', 'hint'));
          target.classList.remove('hidden');
          ragRenderHits(result.retrieved_chunks || []);
        } else ragRenderHits(result.matches || []);
        ragStatus('Готово. Результаты получены из временного индекса.');
      } catch (error) {
        ragStatus(`Ошибка RAG: ${error.message}`, true);
      } finally {
        button.disabled = false;
      }
    }

    $('rag-build').addEventListener('click', ragBuildIndex);
    $('rag-search').addEventListener('click', () => ragRun(false));
    $('rag-ask').addEventListener('click', () => ragRun(true));
    $('rag-delete').addEventListener('click', () => { ragReset(); ragStatus('Временный индекс удалён из памяти сервера.'); });
    $('rag-vacancy-select').addEventListener('change', ragReset);
    $('resume').addEventListener('change', ragReset);
    // RAG_V06_JS_END
'''


def backup_and_write(path: Path, content: str) -> None:
    if content == path.read_text(encoding="utf-8"):
        return
    backup = path.with_name(path.name + ".before_rag_v06")
    if not backup.exists():
        backup.write_bytes(path.read_bytes())
        print(f"Резервная копия: {backup.relative_to(ROOT)}")
    path.write_text(content, encoding="utf-8")
    print(f"Обновлено: {path.relative_to(ROOT)}")


def main() -> int:
    if not (MAIN.is_file() and PAGE.is_file() and REQUIREMENTS.is_file()):
        print("Ошибка: запускайте скрипт из корня проекта F:\\MATRIX", file=sys.stderr)
        return 2

    original_main = MAIN.read_text(encoding="utf-8")
    main_text = original_main
    import_line = 'from .rag_api import router as rag_router\n'
    if import_line not in main_text:
        # Never place imports before a module docstring or __future__.
        marker = 'from .vacancies import VacancyError, search_hh\n'
        if marker not in main_text:
            print("Не найден ориентир импортов в app/main.py — без изменений", file=sys.stderr)
            return 2
        main_text = main_text.replace(marker, marker + import_line, 1)
    router_call = 'app.include_router(rag_router)\n'
    if router_call not in main_text:
        lines = main_text.splitlines(keepends=True)
        positions = [i for i, line in enumerate(lines) if line.startswith('app = FastAPI(')]
        if len(positions) != 1:
            print("Неоднозначное место создания FastAPI — без изменений", file=sys.stderr)
            return 2
        lines.insert(positions[0] + 1, router_call)
        main_text = ''.join(lines)

    original_page = PAGE.read_text(encoding="utf-8")
    page_text = original_page
    if 'RAG_V06_START' not in page_text:
        anchor = '      <!-- JSON базового извлечения -->'
        if anchor not in page_text:
            print("Не найден раздел результатов в static/index.html — без изменений", file=sys.stderr)
            return 2
        page_text = page_text.replace(anchor, RAG_HTML + '\n' + anchor, 1)
    if 'RAG_V06_JS_START' not in page_text:
        anchor = "    $('form').addEventListener('submit', runLocalAnalysis);"
        if anchor not in page_text:
            print("Не найдены обработчики событий в static/index.html — без изменений", file=sys.stderr)
            return 2
        page_text = page_text.replace(anchor, RAG_JS + '\n' + anchor, 1)
    if 'ragPopulateVacancies();' not in page_text:
        anchor = '        renderResults(data);'
        if anchor not in page_text:
            print("Не найдена функция базового анализа в HTML — без изменений", file=sys.stderr)
            return 2
        page_text = page_text.replace(anchor, anchor + '\n        ragReset();\n        ragPopulateVacancies();', 1)

    req = REQUIREMENTS.read_text(encoding="utf-8")
    if 'faiss-cpu' not in req:
        req += '\n# v0.6 RAG: exact FAISS similarity search in RAM\nfaiss-cpu>=1.13,<2\nnumpy>=2.0,<3\n'
    ignore = GITIGNORE.read_text(encoding="utf-8") if GITIGNORE.exists() else ''
    if '*.before_rag_v06' not in ignore:
        ignore += '\n# Local backups created by the RAG installer\n*.before_rag_v06\n'

    if README.is_file():
        readme = README.read_text(encoding="utf-8")
        readme = readme.replace(
            "- **Векторный поиск, эмбеддинги и полноценный RAG/FAISS-пайплайн пока не реализованы.** Наличие навыков `RAG` и `FAISS` в деморезюме не означает, что само приложение использует эти технологии.",
            "- **v0.6:** добавлен отдельный пайплайн эмбеддингов OpenAI, FAISS-поиска и RAG-ответов с проверенными дословными цитатами. Он не изменяет автоматически оценку соответствия вакансии."
        )
        readme = readme.replace(
            "**FAISS/RAG и LLM-сопоставления пока нет**.",
            "**В v0.6 добавлен отдельный FAISS/RAG-анализ документов; оценки навыков не подменяются выводами LLM**."
        )
        readme = readme.replace(
            "- Полноценный retrieval/RAG по длинным документам с адресными ссылками на фрагменты.",
            "- Масштабирование retrieval/RAG на большие корпуса документов и постоянные индексы."
        )
        if "<!-- RAG_V06_README_START -->" not in readme:
            readme += ("\n\n<!-- RAG_V06_README_START -->\n"
                       "## Векторный поиск и RAG/FAISS (v0.6)\n\n"
                       "Добавлены эмбеддинги `text-embedding-3-small`, временный индекс `FAISS IndexFlatIP`, "
                       "поиск цитируемых фрагментов резюме и вакансии и RAG-ответы через OpenAI. "
                       "Цитаты проверяются по исходному тексту, смысл выводов проверяет человек. "
                       "Результаты не влияют автоматически на балл соответствия.\n\n"
                       "**Установка и API:** [README_RAG_v0.6.md](README_RAG_v0.6.md).\n"
                       "<!-- RAG_V06_README_END -->\n")
    else:
        readme = None

    backup_and_write(MAIN, main_text)
    backup_and_write(PAGE, page_text)
    backup_and_write(REQUIREMENTS, req)
    if GITIGNORE.exists():
        backup_and_write(GITIGNORE, ignore)
    if readme is not None:
        backup_and_write(README, readme)
    print('Готово. Запустите pytest и Uvicorn; реальные OpenAI-запросы только после согласия в UI.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
