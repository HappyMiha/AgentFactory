'use strict';
(() => {
  const byId = id => document.getElementById(id);
  const state = {language: 'uk', messages: {}, runs: [], runId: null, temporal: false};
  const query = new URLSearchParams(location.search);

  // Every visible string comes from the server's catalogue, so a missing
  // translation shows up as a missing key rather than as silent Ukrainian.
  function say(key, parameters) {
    let text = state.messages[key];
    if (text === undefined) return key;
    if (parameters) {
      for (const [name, value] of Object.entries(parameters)) {
        text = text.split(`{${name}}`).join(String(value));
      }
    }
    return text;
  }

  function applyTranslations() {
    document.documentElement.lang = state.language;
    document.title = `${say('work.title')} · ${say('app.name')}`;
    for (const node of document.querySelectorAll('[data-i18n]')) {
      node.textContent = say(node.dataset.i18n);
    }
    for (const node of document.querySelectorAll('[data-i18n-attr]')) {
      for (const pair of node.dataset.i18nAttr.split(';')) {
        const [attribute, key] = pair.split(':');
        if (attribute && key) node.setAttribute(attribute.trim(), say(key.trim()));
      }
    }
    for (const node of document.querySelectorAll('[data-lang]')) {
      node.setAttribute('aria-current', String(node.dataset.lang === state.language));
    }
  }

  function withLanguage(url) {
    return `${url}${url.includes('?') ? '&' : '?'}lang=${encodeURIComponent(state.language)}`;
  }

  function element(tag, text, className) {
    const node = document.createElement(tag);
    if (text !== undefined && text !== null) node.textContent = String(text);
    if (className) node.className = className;
    return node;
  }

  function replace(node, children) {
    node.replaceChildren(...children);
  }

  async function readJson(response) {
    try { return await response.json(); } catch { return {}; }
  }

  async function get(url) {
    const response = await fetch(withLanguage(url), {cache: 'no-store'});
    const payload = await readJson(response);
    if (!response.ok || payload.error) {
      const error = new Error(payload.error ? payload.error.message : `HTTP ${response.status}`);
      error.code = payload.error ? payload.error.code : 'http_error';
      throw error;
    }
    return payload;
  }

  async function loadMessages() {
    const chosen = query.get('lang');
    const response = await fetch(
      `/api/i18n${chosen ? `?lang=${encodeURIComponent(chosen)}` : ''}`,
      {cache: 'no-store'},
    );
    if (!response.ok) return;
    const payload = await response.json();
    state.language = payload.language;
    state.messages = payload.messages;
    applyTranslations();
  }

  async function loadRuns() {
    const payload = await get('/api/work/runs');
    state.runs = payload.runs || [];
    const select = byId('run');
    replace(select, state.runs.map(run => {
      const option = element('option', `#${run.run_id} · ${run.title}`);
      option.value = String(run.run_id);
      return option;
    }));
    const has = state.runs.length > 0;
    byId('empty').hidden = has;
    byId('detail').hidden = !has;
    byId('picker-form').hidden = !has;
    if (!has) {
      byId('summary').textContent = say('work.runs.empty');
      return;
    }
    if (!state.runs.some(run => String(run.run_id) === String(state.runId))) {
      state.runId = state.runs[0].run_id;
    }
    select.value = String(state.runId);
    await loadRun();
  }

  function showStage(report) {
    const stage = report.stage;
    byId('stage').textContent =
      `${stage.label} — ${say('work.stage', {index: stage.index, total: stage.total})}`;
    const done = stage.total > 0 ? Math.round(((stage.index - 1) / stage.total) * 100) : 0;
    byId('bar').style.width = `${done}%`;
    const liveness = byId('liveness');
    liveness.textContent = say(`work.liveness.${report.liveness}`);
    liveness.dataset.state = report.liveness;
    byId('heartbeat').textContent = report.heartbeat_age_seconds === null
      ? say('work.heartbeat.never')
      : say('work.heartbeat', {age: Math.round(report.heartbeat_age_seconds)});
  }

  function showBlockers(report) {
    replace(byId('blockers'), report.blockers.length
      ? report.blockers.map(blocker => {
          const item = element('li');
          item.append(element('strong', blocker.summary));
          item.append(element('span', blocker.action, 'action'));
          return item;
        })
      : [element('li', say('work.blockers.none'), 'clear')]);
    byId('next').textContent = report.next_action;
  }

  function money(value, unit) {
    return `${Number(value).toFixed(2)} ${unit}`;
  }

  function showMoney(report) {
    const spend = report.spend;
    const rows = [
      [say('work.spend.spent'), money(spend.spent, spend.unit)],
      [say('work.spend.reserved'), money(spend.reserved, spend.unit)],
      [say('work.spend.cap'), spend.cap === null
        ? say('work.spend.nocap') : money(spend.cap, spend.unit)],
    ];
    if (spend.remaining !== null) {
      rows.push([say('work.spend.remaining'), money(spend.remaining, spend.unit)]);
    }
    const nodes = [];
    for (const [term, value] of rows) {
      nodes.push(element('dt', term));
      nodes.push(element('dd', value));
    }
    replace(byId('money'), nodes);
    // An unknown finishing time is stated as unknown, with the reason, never
    // rounded up into a number that looks like knowledge.
    byId('estimate').textContent = report.estimate.known
      ? `${say('work.estimate.value', {minutes: Math.max(1, Math.round(report.estimate.seconds / 60))})} — ${report.estimate.basis}`
      : report.estimate.basis;
  }

  function operations(items) {
    return items.length
      ? items.map(item => element('li', item.label))
      : [element('li', say('work.stop.nothing'))];
  }

  function showStop(plan) {
    replace(byId('stops-now'), operations(plan.stops_now));
    replace(byId('finishes'), operations(plan.finishes_anyway));
    byId('spending').textContent = plan.spending;
    byId('wait').textContent = plan.longest_wait_seconds === null
      ? '' : say('work.stop.wait', {seconds: Math.round(plan.longest_wait_seconds)});
    replace(byId('stop-warnings'), plan.warnings.map(text => element('li', text)));
  }

  function showRestart(report) {
    byId('restart-note').textContent = report.note;
    // An empty list says nothing at all, so each one states its own emptiness.
    const listed = items => items.length
      ? items.map(item => element('li', `${item.identity} — ${item.detail}`))
      : [element('li', say('work.restart.empty'), 'none')];
    replace(byId('restart-check'), listed(report.to_check));
    replace(byId('restart-kept'), listed(report.preserved));
  }

  async function pauseAvailable() {
    // Pausing exists only under Temporal. Rather than offering a button that
    // silently does nothing, ask first and disable it with the reason.
    try {
      await get(`/api/runs/${state.runId}/temporal`);
      return true;
    } catch {
      return false;
    }
  }

  async function loadRun() {
    try {
      const report = await get(`/api/work/runs/${state.runId}`);
      showStage(report);
      showBlockers(report);
      showMoney(report);
      showStop(report.stop);
      showRestart(await get(`/api/work/runs/${state.runId}/after-restart`));
      byId('summary').textContent = report.next_action;
      state.temporal = await pauseAvailable();
      for (const id of ['pause', 'resume']) byId(id).disabled = !state.temporal;
      byId('pause-note').hidden = state.temporal;
    } catch (error) {
      byId('summary').textContent = say('work.error', {message: error.message});
    }
  }

  async function command(path, reason) {
    const response = await fetch(path, {
      method: 'POST',
      headers: {'Content-Type': 'application/json', 'X-Agent-Factory-Confirm': 'true'},
      body: JSON.stringify({confirmed: true, reason}),
    });
    const payload = await readJson(response);
    if (!response.ok || payload.error) {
      throw new Error(payload.error ? payload.error.message : `HTTP ${response.status}`);
    }
    return payload;
  }

  async function stopRun() {
    const result = byId('stop-result');
    if (!byId('stop-ack').checked) {
      result.textContent = say('work.stop.confirm');
      byId('stop-ack').focus();
      return;
    }
    try {
      await command(`/api/executions/runs/${state.runId}/cancel`,
                    byId('stop-reason').value.trim() || 'Stopped from the progress page');
      result.textContent = say('work.stop.done');
      await loadRuns();
    } catch (error) {
      result.textContent = say('work.error', {message: error.message});
    }
  }

  async function signal(action) {
    const result = byId('stop-result');
    try {
      await command(`/api/executions/runs/${state.runId}/${action}`,
                    byId('stop-reason').value.trim() || `${action} from the progress page`);
      await loadRun();
    } catch (error) {
      result.textContent = say('work.error', {message: error.message});
    }
  }

  function start() {
    byId('run').addEventListener('change', event => {
      state.runId = Number(event.target.value);
      loadRun();
    });
    byId('refresh').addEventListener('click', () => loadRuns());
    byId('stop').addEventListener('click', stopRun);
    byId('pause').addEventListener('click', () => signal('pause'));
    byId('resume').addEventListener('click', () => signal('resume'));
    loadMessages().then(loadRuns).catch(error => {
      byId('summary').textContent = say('work.error', {message: error.message});
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start);
  } else {
    start();
  }
})();
