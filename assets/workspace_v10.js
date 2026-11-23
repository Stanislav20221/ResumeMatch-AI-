    // WORKSPACE_V10_JS_START — токен только в памяти страницы; никаких localStorage/cookies.
    let workspaceToken = null;

    function workspaceText(tag, value, className = '') {
      const element = document.createElement(tag);
      if (className) element.className = className;
      element.textContent = String(value ?? '');
      return element;
    }
    function workspaceStatus(message, error = false) {
      const element = $('workspace-status');
      element.textContent = message;
      element.classList.toggle('error-text', error);
    }
    async function workspaceRequest(path, method = 'GET', data = undefined) {
      if (!workspaceToken) throw new Error('Сначала откройте доступ к истории');
      const headers = {'X-Workspace-Token': workspaceToken};
      if (data !== undefined) headers['Content-Type'] = 'application/json';
      const response = await fetch('/api/workspace' + path, {
        method, headers, body: data === undefined ? undefined : JSON.stringify(data), cache: 'no-store'
      });
      if (!response.ok) {
        let message = `HTTP ${response.status}`;
        try {
          const result = await response.json();
          if (result.detail) message = typeof result.detail === 'string' ? result.detail : JSON.stringify(result.detail);
        } catch (_) {}
        throw new Error(message);
      }
      return response.json();
    }
    function workspaceItem(title, description = '') {
      const node = workspaceText('div', '', 'workspace-item');
      node.append(workspaceText('strong', title));
      if (description) node.append(workspaceText('p', description));
      return node;
    }
    function workspaceButton(label, callback) {
      const button = workspaceText('button', label);
      button.type = 'button';
      button.className = 'secondary';
      button.addEventListener('click', async () => {
        button.disabled = true;
        try { await callback(); }
        catch (error) { workspaceStatus(`Ошибка истории: ${error.message}`, true); }
        finally { button.disabled = false; }
      });
      return button;
    }
    function workspaceButtons(...buttons) {
      const box = workspaceText('div', '', 'workspace-buttons');
      box.append(...buttons);
      return box;
    }

    function workspaceRenderCandidates(data) {
      const target = $('workspace-candidates'); target.replaceChildren();
      if (!data.items.length) target.append(workspaceText('p', 'Кандидатов пока нет.', 'workspace-empty'));
      data.items.forEach(item => {
        const box = workspaceItem(item.name, item.note);
        box.append(workspaceButtons(
          workspaceButton('Изменить', async () => {
            const name = prompt('Новая метка кандидата', item.name);
            if (name === null) return;
            const note = prompt('Новая заметка', item.note || '');
            if (note === null) return;
            await workspaceRequest('/candidates/' + encodeURIComponent(item.id), 'PUT', {name, note});
            await workspaceRefresh();
          }),
          workspaceButton('Удалить', async () => {
            if (!confirm('Удалить кандидата и все связанные архивные отчёты без возможности восстановления?')) return;
            await workspaceRequest('/candidates/' + encodeURIComponent(item.id), 'DELETE');
            await workspaceRefresh();
          })
        ));
        target.append(box);
      });
    }
    function workspaceRenderVacancies(data) {
      const target = $('workspace-vacancies'); target.replaceChildren();
      if (!data.items.length) target.append(workspaceText('p', 'Вакансий пока нет.', 'workspace-empty'));
      data.items.forEach(item => {
        const box = workspaceItem(item.title, (item.description || '').slice(0, 180));
        box.append(workspaceButtons(
          workspaceButton('Изменить', async () => {
            const title = prompt('Название вакансии', item.title);
            if (title === null) return;
            const description = prompt('Описание вакансии', item.description || '');
            if (description === null) return;
            await workspaceRequest('/vacancies/' + encodeURIComponent(item.id), 'PUT', {
              title, description, key_skills: item.key_skills || []
            });
            await workspaceRefresh();
          }),
          workspaceButton('Удалить', async () => {
            if (!confirm('Удалить вакансию и связанные архивные отчёты без возможности восстановления?')) return;
            await workspaceRequest('/vacancies/' + encodeURIComponent(item.id), 'DELETE');
            await workspaceRefresh();
          })
        ));
        target.append(box);
      });
    }
    function workspaceQuote(title, text) {
      const block = workspaceText('p', `${title}: ${text || 'цитата отсутствует'}`, 'info');
      return block;
    }
    function workspaceRenderArchiveDetails(data) {
      const target = $('workspace-archive-detail');
      target.replaceChildren();
      target.append(workspaceText('h3', data.title));
      target.append(workspaceText('p', data.notice, 'notice'));
      const snapshot = data.snapshot || {};
      if (data.kind === 'batch') {
        target.append(workspaceText('p', 'Кандидаты: ' + (data.candidates || []).map(c => c.name).join(', '), 'info'));
        const wrap = workspaceText('div', '', 'workspace-archive-grid');
        const table = document.createElement('table');
        const head = document.createElement('thead');
        const trh = document.createElement('tr');
        trh.append(workspaceText('th', 'Требование'));
        (snapshot.candidates || []).forEach(c => trh.append(workspaceText('th', c.label)));
        head.append(trh); table.append(head);
        const body = document.createElement('tbody');
        (snapshot.comparison || []).forEach(line => {
          const tr = document.createElement('tr');
          tr.append(workspaceText('td', line.requirement));
          (line.candidates || []).forEach(item => {
            tr.append(workspaceText('td', (typeof batchStatusLabels === 'object' && batchStatusLabels[item.status]) || item.status));
          });
          body.append(tr);
        });
        table.append(body); wrap.append(table); target.append(wrap);
        (snapshot.candidates || []).forEach(candidate => {
          const details = document.createElement('details');
          details.append(workspaceText('summary', `${candidate.label} — сохранённые подтверждения`));
          (candidate.rows || []).forEach(row => {
            const item = workspaceItem(`${row.requirement}: ${row.status}`, row.detail);
            (row.resume_evidence || []).forEach(ref => item.append(workspaceQuote('Резюме', ref.quote)));
            if (row.vacancy_evidence?.quote) item.append(workspaceQuote('Вакансия', row.vacancy_evidence.quote));
            details.append(item);
          });
          target.append(details);
        });
      } else {
        const summary = snapshot.overview || {};
        target.append(workspaceText('p', `Дословные упоминания: ${summary.literal_mentions ?? '—'}/${summary.required_skills ?? '—'}. Проверок на ручное рассмотрение: ${summary.review_items ?? '—'}.`, 'info'));
        (snapshot.conclusion || []).forEach(line => target.append(workspaceText('p', line)));
        (snapshot.rows || []).forEach(row => {
          const item = workspaceItem(`${row.requirement} — ${row.status_label || row.status}`, row.detail);
          (row.resume_quotes || []).forEach(proof => item.append(workspaceQuote('Резюме', proof.quote)));
          if (row.vacancy_quote) item.append(workspaceQuote('Вакансия', row.vacancy_quote));
          target.append(item);
        });
      }
      target.classList.remove('hidden');
    }
    function workspaceRenderArchives(data) {
      const target = $('workspace-archives'); target.replaceChildren();
      if (!data.items.length) target.append(workspaceText('p', 'Сохранённых анализов пока нет.', 'workspace-empty'));
      data.items.forEach(item => {
        const description = `Тип: ${item.kind === 'batch' ? 'пакет' : 'одиночный отчёт'} · Создан: ${item.created_at.slice(0, 10)} · Удаление после: ${item.expires_at.slice(0, 10)}`;
        const box = workspaceItem(item.title, description);
        box.append(workspaceButtons(
          workspaceButton('Открыть', async () => {
            const result = await workspaceRequest('/archives/' + encodeURIComponent(item.id));
            workspaceRenderArchiveDetails(result);
          }),
          workspaceButton('Удалить', async () => {
            if (!confirm('Безвозвратно удалить архивный снимок?')) return;
            await workspaceRequest('/archives/' + encodeURIComponent(item.id), 'DELETE');
            $('workspace-archive-detail').replaceChildren();
            $('workspace-archive-detail').classList.add('hidden');
            await workspaceRefresh();
          })
        ));
        target.append(box);
      });
    }
    async function workspaceRefresh() {
      const [archives, candidates, vacancies] = await Promise.all([
        workspaceRequest('/archives'), workspaceRequest('/candidates'), workspaceRequest('/vacancies')
      ]);
      workspaceRenderArchives(archives);
      workspaceRenderCandidates(candidates);
      workspaceRenderVacancies(vacancies);
    }
    async function workspaceConnect() {
      workspaceToken = $('workspace-token').value;
      $('workspace-token').value = '';
      try {
        await workspaceRefresh();
        $('workspace-content').classList.remove('hidden');
        $('workspace-logout').disabled = false;
        workspaceStatus('История открыта. Ключ хранится только в памяти этой страницы.');
      } catch (error) {
        workspaceLogout();
        workspaceStatus(`Не удалось открыть историю: ${error.message}`, true);
      }
    }
    function workspaceLogout() {
      workspaceToken = null;
      $('workspace-token').value = '';
      $('workspace-content').classList.add('hidden');
      $('workspace-logout').disabled = true;
      ['workspace-archives', 'workspace-candidates', 'workspace-vacancies', 'workspace-archive-detail'].forEach(id => $(id).replaceChildren());
      $('workspace-archive-detail').classList.add('hidden');
      $('workspace-consent').checked = false;
    }
    async function workspaceSave(kind) {
      if (!$('workspace-consent').checked) throw new Error('Подтвердите согласие на локальное сохранение');
      let record;
      if (kind === 'single') {
        const {form, original, selectedIndex} = reportFormPayload();
        const selected = latest.matches[selectedIndex].vacancy;
        const response = await fetch('/api/report/preview', {method:'POST', body:form, cache:'no-store'});
        if (!response.ok) {
          const details = await response.json().catch(() => ({}));
          throw new Error(details.detail || `HTTP ${response.status}`);
        }
        const report = await response.json();
        reportCheckStale(original, selectedIndex);
        record = {
          kind: 'single', title: `Отчёт · ${selected.name || 'Вакансия'}`,
          vacancy: {title: selected.name || 'Вакансия', description: selected.description_text || '', key_skills: selected.key_skills || []},
          candidate_labels: [report.candidate_label || 'Кандидат'], snapshot: report, save_consent: true
        };
      } else {
        const ctx = batchContext;
        if (!ctx) throw new Error('Сначала выполните пакетное сравнение v0.9');
        if (!latest?.matches?.some(item => item.vacancy.id === ctx.vacancy.id)) throw new Error('Вакансия изменилась');
        const form = new FormData();
        ctx.files.forEach(file => form.append('resumes', file));
        form.append('resume_extractions', JSON.stringify(ctx.extractions));
        form.append('vacancy_extraction', JSON.stringify(ctx.vacancyExtraction));
        form.append('vacancy_source', JSON.stringify(ctx.vacancySource));
        form.append('experience_results', JSON.stringify(ctx.experiences));
        form.append('candidate_labels', JSON.stringify(ctx.labels));
        const response = await fetch('/api/batch/compare', {method:'POST', body:form, cache:'no-store'});
        if (!response.ok) {
          const details = await response.json().catch(() => ({}));
          throw new Error(details.detail || `HTTP ${response.status}`);
        }
        const matrix = await response.json();
        if (batchContext !== ctx) throw new Error('Результат изменился, повтори анализ');
        record = {
          kind: 'batch', title: `Пакет · ${ctx.vacancy.name || 'Вакансия'}`,
          vacancy: {title: ctx.vacancy.name || 'Вакансия', description: ctx.vacancySource.description_text || '', key_skills: ctx.vacancySource.key_skills || []},
          candidate_labels: ctx.labels, snapshot: matrix, save_consent: true
        };
      }
      const saved = await workspaceRequest('/archives', 'POST', record);
      workspaceStatus(`Сохранено в локальной истории. Идентификатор: ${saved.id.slice(0, 8)}. Срок хранения до ${saved.expires_at.slice(0, 10)}.`);
      await workspaceRefresh();
    }
    $('workspace-connect').addEventListener('click', workspaceConnect);
    $('workspace-logout').addEventListener('click', () => { workspaceLogout(); workspaceStatus('Доступ закрыт.'); });
    $('workspace-refresh').addEventListener('click', async () => {
      try { await workspaceRefresh(); workspaceStatus('История обновлена.'); }
      catch (error) { workspaceStatus(`Ошибка обновления: ${error.message}`, true); }
    });
    $('workspace-save-report').addEventListener('click', async () => {
      const button = $('workspace-save-report'); button.disabled = true;
      try { await workspaceSave('single'); }
      catch (error) { workspaceStatus(`Не удалось сохранить отчёт: ${error.message}`, true); }
      finally { button.disabled = false; }
    });
    $('workspace-save-batch').addEventListener('click', async () => {
      const button = $('workspace-save-batch'); button.disabled = true;
      try { await workspaceSave('batch'); }
      catch (error) { workspaceStatus(`Не удалось сохранить пакет: ${error.message}`, true); }
      finally { button.disabled = false; }
    });
    $('workspace-add-candidate').addEventListener('click', async () => {
      try {
        await workspaceRequest('/candidates', 'POST', {
          name: $('workspace-candidate-name').value, note: $('workspace-candidate-note').value
        });
        $('workspace-candidate-name').value = ''; $('workspace-candidate-note').value = '';
        await workspaceRefresh();
      } catch (error) { workspaceStatus(`Ошибка сохранения кандидата: ${error.message}`, true); }
    });
    $('workspace-add-vacancy').addEventListener('click', async () => {
      try {
        await workspaceRequest('/vacancies', 'POST', {
          title: $('workspace-vacancy-title').value,
          description: $('workspace-vacancy-description').value, key_skills: []
        });
        $('workspace-vacancy-title').value = ''; $('workspace-vacancy-description').value = '';
        await workspaceRefresh();
      } catch (error) { workspaceStatus(`Ошибка сохранения вакансии: ${error.message}`, true); }
    });
    // WORKSPACE_V10_JS_END
