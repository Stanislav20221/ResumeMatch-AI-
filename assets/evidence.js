    // EVIDENCE_V07_JS_START
    function evidenceReset() {
      $('evidence-results').classList.add('hidden');
      $('evidence-results').replaceChildren();
      $('evidence-status').textContent = '';
      $('evidence-status').classList.remove('error-text');
    }

    function evidenceSource(title, proof) {
      const block = make('div', '', 'evidence-source');
      block.append(make('b', `${title}: `));
      block.append(make('span', proof?.quote || 'Нет цитаты'));
      if (proof?.page != null) block.append(make('span', ` · стр. ${proof.page}`, 'info'));
      if (proof?.method) block.append(make('div', `Проверка: ${proof.method}`, 'info'));
      return block;
    }

    const evidenceLabels = {
      exact_mention: 'Дословно упомянуто', semantic_proposal: 'Предложение LLM',
      partial_proposal: 'Частичное совпадение', duration_provisional: 'Стаж предварительно достаточен',
      documented_below: 'Подтверждённый срок меньше', insufficient_evidence: 'Недостаточно данных',
      not_confirmed: 'Не подтверждено', not_run: 'Проверка не запускалась',
      manual_review: 'Ручная проверка', invalid_source: 'Источник не подтверждён'
    };

    function evidenceRender(data) {
      const target = $('evidence-results');
      target.replaceChildren();
      const summary = make('div', '', 'evidence-summary');
      for (const [value, label] of [
        [data.summary.literal_skill_score_percent == null ? '—' : `${data.summary.literal_skill_score_percent}%`, 'Доля дословных упоминаний обязательных навыков'],
        [`${data.rows.length}`, 'Требований в матрице'],
        [`${data.summary.proposals_for_review}`, 'Предложений на ручную проверку']
      ]) {
        const card = make('div');
        card.append(make('b', value));
        card.append(make('span', label));
        summary.append(card);
      }
      target.append(summary);
      target.append(make('p', 'Все цитаты сверены с текущими исходными документами на сервере. Результат не является оценкой профессиональной квалификации.', 'info'));
      const groups = [
        ['required_skill', 'Обязательные навыки'],
        ['optional_skill', 'Желательные навыки'],
        ['experience', 'Требования к стажу'],
        ['responsibility', 'Обязанности']
      ];
      for (const [kind, heading] of groups) {
        const rows = data.rows.filter(row => row.category === kind);
        if (!rows.length) continue;
        target.append(make('h4', heading));
        for (const row of rows) {
          const card = make('article', '', 'evidence-row');
          const header = make('div', '', 'evidence-row-header');
          header.append(make('strong', `${row.id}. ${row.requirement}`));
          header.append(make('span', evidenceLabels[row.status] || row.status, `evidence-status ${row.status}`));
          card.append(header);
          if (row.category === 'experience' && row.required_months != null) {
            card.append(make('p', `Требуется ${row.required_months} мес. · Документировано: ${row.documented_months == null ? 'неизвестно' : row.documented_months + ' мес.'}`, 'evidence-detail'));
          }
          if (row.detail) card.append(make('p', row.detail, 'evidence-detail'));
          const details = make('details');
          details.append(make('summary', 'Исходные подтверждения и методы'));
          details.append(evidenceSource('Вакансия', row.vacancy_evidence));
          for (const proof of row.resume_evidence || []) details.append(evidenceSource('Резюме', proof));
          if (!(row.resume_evidence || []).length) details.append(make('p', 'Проверяемых цитат резюме нет.', 'info'));
          card.append(details);
          target.append(card);
        }
      }
      if (data.rag_observations?.length) {
        target.append(make('h4', 'RAG: наблюдения с проверенными цитатами (не влияют на баллы)'));
        for (const item of data.rag_observations) {
          const card = make('article', '', 'evidence-row');
          card.append(make('strong', item.statement));
          for (const citation of item.citations || [])
            card.append(evidenceSource(citation.document_type === 'resume' ? 'Резюме' : 'Вакансия', citation));
          card.append(make('p', 'Смысловой вывод RAG требует проверки человеком.', 'evidence-detail'));
          target.append(card);
        }
      }
      target.append(make('p', data.disclaimer, 'notice'));
      target.classList.remove('hidden');
    }

    async function runEvidenceMatrix() {
      const status = $('evidence-status');
      const button = $('run-evidence');
      const original = latest;
      const selectedIndex = Number($('llm-vacancy-select').value);
      const vacancy = latest?.matches?.[selectedIndex]?.vacancy;
      const file = $('resume').files[0];
      if (!latest?.llm?.resume || !latest?.llm?.vacancy || !file || !vacancy || vacancy.id !== latest.llm.vacancy_id) {
        status.textContent = 'Сначала выполните LLM-анализ выбранной вакансии.';
        return;
      }
      if (analyzedInputSnapshot !== getCurrentInputSnapshot()) {
        status.textContent = 'Форма изменилась. Повторите основной и LLM-анализ.';
        return;
      }
      button.disabled = true;
      evidenceReset();
      status.textContent = 'Повторно сверяем исходные цитаты и пересчитываем периоды локально...';
      try {
        const form = new FormData();
        form.append('resume', file);
        form.append('resume_extraction', JSON.stringify(latest.llm.resume));
        form.append('vacancy_extraction', JSON.stringify(latest.llm.vacancy));
        form.append('vacancy_source', JSON.stringify({
          description_text: vacancy.description_text || '',
          key_skills: vacancy.key_skills || []
        }));
        if (latest.llm.semantic) form.append('semantic_result', JSON.stringify(latest.llm.semantic));
        if (latest.llm.experience) form.append('experience_result', JSON.stringify(latest.llm.experience));
        if (latest.llm.rag) form.append('rag_result', JSON.stringify(latest.llm.rag));
        const result = await getJsonResponse(await fetch('/api/evidence/matrix', {method:'POST', body: form}));
        if (latest !== original || analyzedInputSnapshot !== getCurrentInputSnapshot() ||
            selectedIndex !== Number($('llm-vacancy-select').value))
          throw new Error('Исходные данные изменились во время формирования матрицы.');
        latest.llm.evidence = result;
        evidenceRender(result);
        status.textContent = 'Готово. Матрица собрана локально; ручная проверка выводов обязательна.';
      } catch (error) {
        status.textContent = `Ошибка сборки матрицы: ${error.message}`;
        status.classList.add('error-text');
      } finally {
        button.disabled = false;
      }
    }
    $('run-evidence').addEventListener('click', runEvidenceMatrix);
    $('run-llm').addEventListener('click', evidenceReset);
    $('run-semantic').addEventListener('click', evidenceReset);
    $('run-experience').addEventListener('click', evidenceReset);
    $('form').addEventListener('submit', evidenceReset);
    $('llm-vacancy-select').addEventListener('change', evidenceReset);
    // EVIDENCE_V07_JS_END
