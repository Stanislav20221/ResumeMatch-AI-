    // BATCH_V09_JS_START — пакетный режим не изменяет старые результаты LLM.
    let batchContext = null;
    let batchBusy = false;

    const batchStatusLabels = {
      exact_mention: 'Дословно упомянуто', not_confirmed: 'Не подтверждено текстом',
      semantic_proposal: 'Предложение LLM', partial_proposal: 'Частичное предложение',
      duration_provisional: 'Длительность предварительно достаточна',
      documented_below: 'Документировано меньше требуемого',
      insufficient_evidence: 'Недостаточно данных', not_run: 'Проверка не запускалась',
      manual_review: 'Требует ручной проверки', invalid_source: 'Исходная цитата не подтверждена'
    };
    const batchGroupLabels = {
      required_skill: 'Обязательный навык', optional_skill: 'Желательный навык',
      experience: 'Стаж', responsibility: 'Обязанность'
    };

    function batchStatus(message, error = false) {
      const node = $('batch-status');
      node.textContent = message;
      node.classList.toggle('error-text', error);
    }
    function batchReset() {
      if (batchBusy) return;
      batchContext = null;
      $('batch-output').replaceChildren();
      $('batch-output').classList.add('hidden');
      batchStatus('');
    }
    function batchPopulateVacancies() {
      if (batchBusy) return;
      const select = $('batch-vacancy');
      const previous = select.value;
      select.replaceChildren();
      const vacancies = latest?.matches || [];
      vacancies.forEach((item, index) => {
        const option = document.createElement('option');
        option.value = String(index);
        option.textContent = item.vacancy.name || `Вакансия ${index + 1}`;
        select.append(option);
      });
      if (vacancies[Number(previous)]) select.value = previous;
      else if (vacancies.length) select.value = '0';
      batchReset();
    }
    async function batchResponse(response) {
      if (!response.ok) {
        let message = `HTTP ${response.status}`;
        try {
          const body = await response.json();
          if (body.detail) message = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail);
        } catch (_) {}
        throw new Error(message);
      }
      return await response.json();
    }
    function batchStale(original, snapshot, files, index) {
      if (latest !== original || analyzedInputSnapshot !== snapshot ||
          snapshot !== getCurrentInputSnapshot() || Number($('batch-vacancy').value) !== index ||
          $('batch-resumes').files.length !== files.length ||
          files.some((file, i) => {
            const current = $('batch-resumes').files[i];
            return !current || current.name !== file.name || current.size !== file.size ||
              current.lastModified !== file.lastModified;
          })) {
        throw new Error('Исходные файлы, вакансии или параметры изменились. Запусти пакет заново.');
      }
    }
    function batchProof(title, proof) {
      const node = make('div', '', 'batch-quote');
      node.append(make('strong', `${title}: `));
      node.append(make('span', proof?.quote || 'Цитата отсутствует'));
      if (proof?.page != null) node.append(make('span', ` · стр. ${proof.page}`));
      return node;
    }
    function batchRender(data) {
      const container = $('batch-output');
      container.replaceChildren();
      container.append(make('h3', 'Сводная матрица требований'));
      container.append(make('p', `Обработано резюме: ${data.candidate_count}. Порядок — по загрузке, не по «рейтингу».`, 'info'));
      const wrap = make('div', '', 'batch-grid-wrap');
      const table = make('table', '', 'batch-grid');
      const head = document.createElement('thead');
      const headRow = document.createElement('tr');
      headRow.append(make('th', 'Требование вакансии'));
      for (const candidate of data.candidates) headRow.append(make('th', candidate.label));
      head.append(headRow); table.append(head);
      const body = document.createElement('tbody');
      for (const entry of data.comparison) {
        const tr = document.createElement('tr');
        const requirement = make('td');
        requirement.append(make('strong', entry.requirement));
        requirement.append(make('div', batchGroupLabels[entry.category] || entry.category, 'info'));
        tr.append(requirement);
        for (const item of entry.candidates) {
          const td = make('td');
          td.append(make('span', batchStatusLabels[item.status] || item.status, 'batch-pill'));
          if (item.verified_resume_quotes) td.append(make('div', `Проверенных цитат: ${item.verified_resume_quotes}`, 'hint'));
          tr.append(td);
        }
        body.append(tr);
      }
      table.append(body); wrap.append(table); container.append(wrap);
      container.append(make('h3', 'Доказательства по каждому резюме'));
      data.candidates.forEach((candidate, index) => {
        const card = document.createElement('details');
        card.className = 'batch-candidate';
        const summary = document.createElement('summary');
        summary.textContent = `${candidate.label} · явные упоминания обязательных навыков ${candidate.summary.required_skills_literal}/${candidate.summary.required_skills_total}`;
        card.append(summary);
        const buttons = make('div', '', 'action batch-actions');
        const download = make('button', 'Скачать PDF по этому резюме');
        download.type = 'button'; download.className = 'secondary';
        download.addEventListener('click', () => batchDownloadPDF(index, download));
        buttons.append(download);
        card.append(buttons);
        for (const row of candidate.rows) {
          const item = make('div', '', 'batch-row');
          item.append(make('strong', `${row.requirement} — ${batchStatusLabels[row.status] || row.status}`));
          if (row.detail) item.append(make('p', row.detail, 'info'));
          const evidence = document.createElement('details');
          evidence.append(make('summary', 'Источники и цитаты'));
          evidence.append(batchProof('Вакансия', row.vacancy_evidence));
          if (!row.resume_evidence?.length) evidence.append(make('p', 'Проверенных цитат резюме нет.', 'hint'));
          for (const proof of row.resume_evidence || []) evidence.append(batchProof('Резюме', proof));
          item.append(evidence);
          card.append(item);
        }
        container.append(card);
      });
      container.append(make('p', data.disclaimer, 'notice'));
      container.classList.remove('hidden');
    }

    async function batchDownloadPDF(index, button) {
      const ctx = batchContext;
      if (!ctx) return;
      button.disabled = true;
      try {
        const form = new FormData();
        form.append('resume', ctx.files[index]);
        form.append('resume_extraction', JSON.stringify(ctx.extractions[index]));
        form.append('vacancy_extraction', JSON.stringify(ctx.vacancyExtraction));
        form.append('vacancy_source', JSON.stringify(ctx.vacancySource));
        form.append('vacancy_title', ctx.vacancy.name || 'Вакансия');
        form.append('candidate_label', ctx.labels[index]);
        if (ctx.experiences[index]) form.append('experience_result', JSON.stringify(ctx.experiences[index]));
        const resp = await fetch('/api/report/pdf', {method:'POST', body:form, cache:'no-store'});
        if (!resp.ok) { await batchResponse(resp); throw new Error(`HTTP ${resp.status}`); }
        if (batchContext !== ctx) throw new Error('Результаты изменились, повтори экспорт');
        const blob = await resp.blob();
        if (!blob.type.includes('application/pdf')) throw new Error('Получен файл неправильного формата');
        const url = URL.createObjectURL(blob);
        const anchor = document.createElement('a');
        anchor.href = url; anchor.download = `ResumeMatch_candidate_${index + 1}.pdf`;
        document.body.append(anchor); anchor.click(); anchor.remove();
        setTimeout(() => URL.revokeObjectURL(url), 2000);
      } catch (error) {
        batchStatus(`Не удалось скачать PDF: ${error.message}`, true);
      } finally { button.disabled = false; }
    }

    async function batchRun() {
      if (batchBusy) return;
      const files = Array.from($('batch-resumes').files || []);
      if (!latest?.matches?.length || analyzedInputSnapshot !== getCurrentInputSnapshot()) {
        batchStatus('Сначала выполни обычный анализ резюме и загрузи вакансии.', true); return;
      }
      if (!files.length || files.length > 5) {
        batchStatus('Выбери от 1 до 5 резюме.', true); return;
      }
      if (files.some(f => f.size > 6 * 1024 * 1024 || !/\.(pdf|docx|txt)$/i.test(f.name))) {
        batchStatus('Каждый файл должен быть PDF, DOCX или TXT размером не более 6 МБ.', true); return;
      }
      if (!$('batch-cloud-consent').checked) {
        batchStatus('Для передачи резюме в OpenAI необходимо отдельное согласие.', true); return;
      }
      const original = latest;
      const snapshot = analyzedInputSnapshot;
      const index = Number($('batch-vacancy').value);
      const vacancy = latest.matches[index]?.vacancy;
      if (!vacancy) { batchStatus('Выбери вакансию для сравнения.', true); return; }
      const vacancySource = {
        description_text: vacancy.description_text || '', key_skills: vacancy.key_skills || []
      };
      const doExperience = $('batch-experience').checked;
      const labels = files.map((_, i) => `Кандидат ${i + 1}`);
      const extracts = [];
      const experiences = [];
      const button = $('batch-run');
      batchBusy = true; batchContext = null;
      button.disabled = true; batchStatus('Подготавливаем извлечение требований вакансии...');
      $('batch-output').replaceChildren(); $('batch-output').classList.add('hidden');
      try {
        // Используем исходное извлечение только для той же вакансии.
        let vacancyExtraction = latest?.llm?.vacancy_id === vacancy.id ? latest.llm.vacancy : null;
        if (!vacancyExtraction) {
          const response = await fetch('/api/llm/vacancy', {
            method:'POST', headers:{'Content-Type':'application/json'},
            body:JSON.stringify({...vacancySource, cloud_consent:true}), cache:'no-store'
          });
          vacancyExtraction = await batchResponse(response);
          batchStale(original, snapshot, files, index);
        }
        for (let i = 0; i < files.length; i++) {
          batchStatus(`OpenAI: извлекаем факты из резюме ${i + 1} из ${files.length}...`);
          const form = new FormData(); form.append('resume', files[i]); form.append('cloud_consent', 'true');
          const response = await fetch('/api/llm/resume', {method:'POST', body:form, cache:'no-store'});
          const data = await batchResponse(response);
          batchStale(original, snapshot, files, index);
          if (!data.extraction?.fields) throw new Error(`Резюме ${i + 1}: LLM не вернула структурированные факты`);
          extracts.push(data.extraction);
          let exp = null;
          if (doExperience) {
            batchStatus(`OpenAI: проверяем стаж и обязанности ${i + 1} из ${files.length}...`);
            const ef = new FormData();
            ef.append('resume', files[i]);
            ef.append('vacancy_source', JSON.stringify(vacancySource));
            ef.append('vacancy_extraction', JSON.stringify(vacancyExtraction));
            ef.append('cloud_consent', 'true');
            exp = await batchResponse(await fetch('/api/llm/experience-match', {method:'POST',body:ef, cache:'no-store'}));
            batchStale(original, snapshot, files, index);
          }
          experiences.push(exp);
        }
        batchStatus('Перепроверяем исходные цитаты всех резюме локально...');
        const compareForm = new FormData();
        for (const file of files) compareForm.append('resumes', file);
        compareForm.append('resume_extractions', JSON.stringify(extracts));
        compareForm.append('vacancy_extraction', JSON.stringify(vacancyExtraction));
        compareForm.append('vacancy_source', JSON.stringify(vacancySource));
        compareForm.append('experience_results', JSON.stringify(experiences));
        compareForm.append('candidate_labels', JSON.stringify(labels));
        const response = await fetch('/api/batch/compare', {method:'POST', body:compareForm, cache:'no-store'});
        const result = await batchResponse(response);
        batchStale(original, snapshot, files, index);
        batchContext = {files, extractions:extracts, experiences, vacancy, vacancyExtraction, vacancySource, labels};
        batchRender(result);
        batchStatus(`Готово: ${result.candidate_count} резюме. Цитаты перепроверены, решение о найме не автоматизировано.`);
      } catch (error) {
        batchContext = null;
        batchStatus(`Пакетный анализ прерван: ${error.message}. Уже выполненные OpenAI-запросы могут тарифицироваться.`, true);
      } finally { batchBusy = false; button.disabled = false; }
    }
    $('batch-run').addEventListener('click', batchRun);
    $('batch-resumes').addEventListener('change', batchReset);
    $('batch-vacancy').addEventListener('change', batchReset);
    $('batch-experience').addEventListener('change', batchReset);
    $('form').addEventListener('submit', batchReset);
    // BATCH_V09_JS_END
