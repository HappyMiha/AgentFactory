'use strict';
(() => {
  const byId = id => document.getElementById(id);
  const state = {sections: [], pending: null};

  function element(tag, text, className) {
    const node = document.createElement(tag);
    if (text !== undefined && text !== null) node.textContent = String(text);
    if (className) node.className = className;
    return node;
  }

  function actor() {
    return byId('actor').value.trim();
  }

  async function readJson(response) {
    try { return await response.json(); } catch { return {}; }
  }

  async function post(url, body) {
    const response = await fetch(url, {
      method: 'POST',
      headers: {'Content-Type': 'application/json', 'X-Agent-Factory-Confirm': 'true'},
      body: JSON.stringify(Object.assign({confirmed: true}, body)),
    });
    const payload = await readJson(response);
    if (!response.ok || payload.error) {
      const message = payload.error ? payload.error.message : `Помилка ${response.status}`;
      const error = new Error(message);
      error.code = payload.error ? payload.error.code : 'http_error';
      throw error;
    }
    return payload;
  }

  function control(field) {
    // Every generated control carries its own accessible name; the visible
    // heading above it is not programmatically associated with it.
    if (field.kind === 'boolean') {
      const input = element('input');
      input.type = 'checkbox';
      input.checked = field.value === 'true';
      input.dataset.read = 'checkbox';
      input.setAttribute('aria-label', field.label);
      return input;
    }
    if (field.kind === 'choice') {
      const select = element('select');
      select.setAttribute('aria-label', field.label);
      for (const option of field.choices) {
        const node = element('option', option);
        node.value = option;
        if (option === field.value) node.selected = true;
        select.append(node);
      }
      select.dataset.read = 'value';
      return select;
    }
    const input = element('input');
    input.type = field.kind === 'integer' || field.kind === 'decimal' ? 'number' : 'text';
    if (field.minimum !== null && field.minimum !== undefined) input.min = field.minimum;
    if (field.maximum !== null && field.maximum !== undefined) input.max = field.maximum;
    if (field.kind === 'decimal') input.step = 'any';
    input.value = field.value;
    input.dataset.read = 'value';
    input.setAttribute('aria-label', field.label);
    if (field.kind === 'list') input.placeholder = 'через кому';
    return input;
  }

  function readControl(node) {
    return node.dataset.read === 'checkbox' ? String(node.checked) : node.value.trim();
  }

  function badges(field) {
    const wrap = element('span');
    wrap.append(element('span', field.origin === 'override' ? 'змінено' : 'типове',
      field.origin === 'override' ? 'badge badge-changed' : 'badge badge-default'));
    if (field.risk === 'sensitive') wrap.append(' ', element('span', 'важливе', 'badge badge-sensitive'));
    if (!field.reconfigurable) wrap.append(' ', element('span', 'лише перегляд', 'badge badge-locked'));
    return wrap;
  }

  function originLine(field) {
    const parts = [`Типове: ${field.default || '—'}`, `Джерело типового: ${field.default_source}`];
    if (field.unit) parts.push(`Одиниці: ${field.unit}`);
    if (field.origin === 'override' && field.changed_by) {
      parts.push(`Змінив(ла) ${field.changed_by}${field.changed_at ? ` · ${field.changed_at}` : ''}`);
      if (field.changed_reason) parts.push(`Причина: ${field.changed_reason}`);
    }
    return element('p', parts.join(' · '), 'origin');
  }

  function renderField(field) {
    const node = element('div', undefined, 'field');
    const head = element('div', undefined, 'field-head');
    head.append(element('strong', field.label), badges(field));
    node.append(head, element('p', field.help));
    if (field.risk === 'sensitive' && field.consequence) {
      node.append(element('p', `Якщо змінити: ${field.consequence}`, 'origin'));
    }
    node.append(originLine(field));

    const status = element('p', '', 'field-ok');
    if (!field.reconfigurable) {
      const shown = element('p', `Чинне значення: ${field.value}`);
      node.append(shown);
      return node;
    }

    const controls = element('div', undefined, 'controls');
    const input = control(field);
    const reason = element('input');
    reason.type = 'text';
    reason.className = 'reason';
    reason.maxLength = 300;
    reason.placeholder = 'Причина (необовʼязково)';
    reason.setAttribute('aria-label', `Причина зміни: ${field.label}`);
    const save = element('button', 'Зберегти');
    save.type = 'button';
    save.setAttribute('aria-label', `Зберегти: ${field.label}`);
    const reset = element('button', 'Повернути типове');
    reset.type = 'button';
    reset.setAttribute('aria-label', `Повернути типове: ${field.label}`);
    reset.disabled = field.origin !== 'override';
    controls.append(input, reason, save, reset);
    node.append(controls, status);

    const report = (text, ok) => {
      status.textContent = text;
      status.className = ok ? 'field-ok' : 'field-error';
    };

    save.addEventListener('click', async () => {
      if (!actor()) { report('Спершу вкажіть, хто змінює.', false); byId('actor').focus(); return; }
      const value = readControl(input);
      const body = {value, actor: actor(), reason: reason.value.trim(), acknowledged_consequence: false};
      try {
        await post(`/api/settings/values/${encodeURIComponent(field.key)}`, body);
        await load(`Збережено: ${field.label}.`);
      } catch (error) {
        if (error.code === 'confirmation_required') {
          askConsequence(field, () => post(
            `/api/settings/values/${encodeURIComponent(field.key)}`,
            Object.assign({}, body, {acknowledged_consequence: true, reason: state.pending.reason}),
          ));
          return;
        }
        report(error.message, false);
      }
    });

    reset.addEventListener('click', async () => {
      if (!actor()) { report('Спершу вкажіть, хто змінює.', false); byId('actor').focus(); return; }
      const body = {actor: actor(), reason: reason.value.trim(), acknowledged_consequence: false};
      try {
        await post(`/api/settings/values/${encodeURIComponent(field.key)}/reset`, body);
        await load(`Повернуто типове: ${field.label}.`);
      } catch (error) {
        if (error.code === 'confirmation_required') {
          askConsequence(field, () => post(
            `/api/settings/values/${encodeURIComponent(field.key)}/reset`,
            Object.assign({}, body, {acknowledged_consequence: true, reason: state.pending.reason}),
          ));
          return;
        }
        report(error.message, false);
      }
    });
    return node;
  }

  function askConsequence(field, apply) {
    const dialog = byId('confirm');
    state.pending = {apply, reason: ''};
    byId('confirm-setting').textContent = field.label;
    byId('confirm-consequence').textContent = field.consequence;
    byId('confirm-reason').value = '';
    byId('confirm-ack').checked = false;
    dialog.showModal();
  }

  function findingList(findings) {
    const list = element('ul', undefined, 'findings');
    for (const finding of findings) {
      const item = element('li', undefined, `level-${finding.level}`);
      item.append(element('span', finding.summary));
      if (finding.detail) item.append(element('span', finding.detail, 'detail'));
      list.append(item);
    }
    return list;
  }

  function renderSection(section) {
    const node = element('section', undefined, 'section-card');
    const head = element('div', undefined, 'section-head');
    const title = element('h2', section.title);
    const verify = element('button', 'Перевірити розділ');
    verify.type = 'button';
    verify.setAttribute('aria-label', `Перевірити розділ: ${section.title}`);
    head.append(title, verify);
    node.append(head, element('p', section.summary));
    if (section.changed_count) {
      node.append(element('p', `Змінено від типового: ${section.changed_count}`, 'origin'));
    }
    const findings = findingList(section.findings);
    node.append(findings);
    verify.addEventListener('click', async () => {
      verify.disabled = true;
      try {
        const payload = await post(`/api/settings/sections/${encodeURIComponent(section.section)}/verify`, {});
        findings.replaceWith(findingList(payload.findings));
      } finally {
        verify.disabled = false;
      }
    });
    for (const field of section.fields) node.append(renderField(field));
    return node;
  }

  function renderHistory(changes) {
    const body = byId('history-rows');
    body.replaceChildren();
    byId('history-empty').hidden = changes.length > 0;
    for (const change of changes) {
      const row = element('tr');
      row.append(
        element('td', change.created_at),
        element('td', change.key),
        element('td', `${change.previous_value} → ${change.new_value}`),
        element('td', change.actor),
        element('td', change.reason || '—'),
      );
      body.append(row);
    }
  }

  async function load(message) {
    const response = await fetch('/api/settings/sections', {cache: 'no-store'});
    if (!response.ok) {
      byId('summary').textContent = `Не вдалося прочитати налаштування (${response.status}).`;
      return;
    }
    const payload = await response.json();
    state.sections = payload.sections;
    const host = byId('sections');
    host.replaceChildren();
    for (const section of payload.sections) host.append(renderSection(section));
    const changed = payload.changed_total;
    byId('summary').textContent = (message ? `${message} ` : '')
      + (changed
        ? `Значень, змінених від типового: ${changed}.`
        : 'Усі значення типові — нічого не перевизначено.');
    await loadHistory();
  }

  async function loadHistory() {
    const response = await fetch('/api/settings/changes?limit=50', {cache: 'no-store'});
    if (!response.ok) return;
    const payload = await response.json();
    renderHistory(payload.changes || []);
  }

  byId('confirm').addEventListener('close', async () => {
    const dialog = byId('confirm');
    const pending = state.pending;
    state.pending = null;
    if (dialog.returnValue !== 'confirm' || !pending) return;
    if (!byId('confirm-ack').checked) {
      byId('summary').textContent = 'Зміну не застосовано: наслідок не підтверджено.';
      return;
    }
    pending.reason = byId('confirm-reason').value.trim();
    state.pending = pending;
    try {
      await pending.apply();
      await load('Зміну застосовано з підтвердженням наслідку.');
    } catch (error) {
      byId('summary').textContent = error.message;
    } finally {
      state.pending = null;
    }
  });

  byId('who-form').addEventListener('submit', event => event.preventDefault());
  byId('refresh-history').addEventListener('click', loadHistory);
  load();
})();
