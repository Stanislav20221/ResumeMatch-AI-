    // REPORT_V08_JS_START
    function reportReset() {
      const target = $('report-preview');
      if (target) { target.replaceChildren(); target.classList.add('hidden'); }
      const status = $('report-status');
      if (status) { status.textContent = ''; status.classList.remove('error-text'); }
    }

    function reportFormPayload() {
      const selectedIndex = Number($('llm-vacancy-select').value);
      const vacancy = latest?.matches?.[selectedIndex]?.vacancy;
      const file = $('resume').files[0];
      if (!latest?.llm?.resume || !latest?.llm?.vacancy || !file || !vacancy ||
          vacancy.id !== latest.llm.vacancy_id) {
        throw new Error('Сначала выполните LLM-анализ резюме и выбранной вакансии.');
      }
      if (analyzedInputSnapshot !== getCurrentInputSnapshot()) {
        throw new Error('Исходные данные изменились. Повторите анализ.');
      }
      const form = new FormData();
      form.append('resume', file);
      form.append('resume_extraction', JSON.stringify(latest.llm.resume));
      form.append('vacancy_extraction', JSON.stringify(latest.llm.vacancy));
      form.append('vacancy_source', JSON.stringify({
        description_text: vacancy.description_text || '',
        key_skills: vacancy.key_skills || []
      }));
      form.append('vacancy_title', vacancy.name || 'Выбранная вакансия');
      form.append('candidate_label', $('report-candidate').value || '');
      if (latest.llm.semantic) form.append('semantic_result', JSON.stringify(latest.llm.semantic));
      if (latest.llm.experience) form.append('experience_result', JSON.stringify(latest.llm.experience));
      if (latest.llm.rag) form.append('rag_result', JSON.stringify(latest.llm.rag));
      return {form, original: latest, selectedIndex};
    }

    function reportCheckStale(original, selectedIndex) {
      if (latest !== original || analyzedInputSnapshot !== getCurrentInputSnapshot() ||
          Number($('llm-vacancy-select').value) !== selectedIndex) {
        throw new Error('Выбранная вакансия или исходные данные изменились. Повторите запрос.');
      }
    }

    function reportRender(data) {
      const target = $('report-preview');
      target.replaceChildren();
      target.append(make('h4', data.vacancy_title || 'Отчёт по вакансии'));
      target.append(make('p', `Кандидат: ${data.candidate_label}. Дата: ${data.report_date}.`, 'info'));
      const stats = make('div', '', 'report-stats');
      const overview = data.overview;
      for (const [number, name] of [
        [`${overview.literal_mentions}/${overview.required_skills}`, 'Дословно упомянутые обязательные навыки'],
        [`${overview.review_items}`, 'Ручных проверок'],
        [`${overview.pending_checks}`, 'Проверок не запускалось']
      ]) {
        const tile = make('div', '', 'report-stat');
        tile.append(make('strong', number));
        tile.append(make('span', name));
        stats.append(tile);
      }
      target.append(stats);
      target.append(make('p', 'Доля дословных упоминаний: ' +
        (overview.literal_mention_percent == null ? 'не рассчитывается' : `${overview.literal_mention_percent}%`) +
        '. Не является оценкой компетентности.', 'info'));
      const conclusion = make('div', '', 'report-conclusion');
      conclusion.append(make('h4', 'Итоговое заключение'));
      for (const line of data.conclusion || []) conclusion.append(make('p', '• ' + line));
      target.append(conclusion);
      target.append(make('p', 'Полная матрица, даты и проверенные цитаты включены в PDF.', 'hint'));
      target.classList.remove('hidden');
    }

    async function runReport(format) {
      const button = $(format === 'pdf' ? 'report-pdf-button' : 'report-preview-button');
      const status = $('report-status');
      const preview = $('report-preview-button');
      const pdf = $('report-pdf-button');
      const initial = latest;
      try {
        const {form, original, selectedIndex} = reportFormPayload();
        preview.disabled = pdf.disabled = true;
        status.classList.remove('error-text');
        status.textContent = 'Заново проверяем цитаты и формируем отчёт локально...';
        const response = await fetch(format === 'pdf' ? '/api/report/pdf' : '/api/report/preview', {
          method: 'POST', body: form, cache: 'no-store'
        });
        if (!response.ok) {
          let detail = `Ошибка HTTP ${response.status}`;
          try { const body = await response.json(); if (body.detail) detail = String(body.detail); } catch (_) {}
          throw new Error(detail);
        }
        reportCheckStale(original, selectedIndex);
        if (format === 'pdf') {
          const blob = await response.blob();
          reportCheckStale(original, selectedIndex);
          if (blob.type && !blob.type.includes('application/pdf')) throw new Error('Сервер не вернул PDF');
          const url = URL.createObjectURL(blob);
          const anchor = document.createElement('a');
          anchor.href = url;
          anchor.download = `ResumeMatch_report_${new Date().toISOString().slice(0,10)}.pdf`;
          document.body.append(anchor);
          anchor.click();
          anchor.remove();
          setTimeout(() => URL.revokeObjectURL(url), 2000);
          status.textContent = 'PDF сформирован. Он сохранён на твоём устройстве.';
        } else {
          const data = await response.json();
          reportCheckStale(original, selectedIndex);
          reportRender(data);
          status.textContent = 'Предпросмотр готов. Цитаты пересчитаны по исходным документам.';
        }
      } catch (error) {
        status.textContent = `Не удалось сформировать отчёт: ${error.message}`;
        status.classList.add('error-text');
      } finally {
        preview.disabled = pdf.disabled = false;
      }
    }

    $('report-preview-button').addEventListener('click', () => runReport('preview'));
    $('report-pdf-button').addEventListener('click', () => runReport('pdf'));
    $('report-candidate').addEventListener('input', reportReset);
    $('llm-vacancy-select').addEventListener('change', reportReset);
    $('form').addEventListener('submit', reportReset);
    $('run-llm').addEventListener('click', reportReset);
    $('run-semantic').addEventListener('click', reportReset);
    $('run-experience').addEventListener('click', reportReset);
    $('run-evidence').addEventListener('click', reportReset);
    // REPORT_V08_JS_END
