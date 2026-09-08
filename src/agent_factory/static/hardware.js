'use strict';
(() => {
  const byId = id => document.getElementById(id);
  let latestReport = null;
  const unknown = 'Невідомо';
  function element(tag, text) {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    return node;
  }
  function bytes(value) {
    if (typeof value !== 'number' || !Number.isFinite(value) || value < 0) return unknown;
    if (value === 0) return '0 Б';
    const units = ['Б', 'КіБ', 'МіБ', 'ГіБ', 'ТіБ'];
    const unit = Math.min(Math.floor(Math.log(value) / Math.log(1024)), units.length - 1);
    return `${new Intl.NumberFormat('uk-UA', {maximumFractionDigits: 1}).format(value / (1024 ** unit))} ${units[unit]}`;
  }
  function valueOrUnknown(value) {
    return value === null || value === undefined || value === '' ? unknown : String(value);
  }
  function rows(card, entries) {
    const list = element('dl');
    for (const [label, value] of entries) {
      const row = element('div'), data = element('dd', value);
      if (value === unknown) data.className = 'unknown';
      row.append(element('dt', label), data);
      list.append(row);
    }
    card.append(list);
  }
  function card(title, id) {
    const node = element('section');
    node.className = 'card'; node.id = id;
    const heading = element('h3', title); heading.id = `${id}-title`;
    node.setAttribute('aria-labelledby', heading.id); node.append(heading);
    byId('hardware-cards').append(node);
    return node;
  }
  function render(report) {
    byId('hardware-cards').replaceChildren();
    const stamp = byId('observed-at'), date = new Date(report.observed_at);
    stamp.dateTime = report.observed_at;
    stamp.textContent = Number.isNaN(date.getTime()) ? unknown : new Intl.DateTimeFormat('uk-UA', {dateStyle: 'medium', timeStyle: 'medium'}).format(date);
    stamp.title = report.observed_at;
    rows(card('Система й процесор', 'system-card'), [
      ['Система', valueOrUnknown(report.os?.name)], ['Версія', valueOrUnknown(report.os?.release)],
      ['Архітектура', valueOrUnknown(report.os?.architecture)], ['Процесор', valueOrUnknown(report.cpu?.name)],
      ['Логічні ядра', valueOrUnknown(report.cpu?.logical_cores)]
    ]);
    rows(card('Оперативна пам’ять', 'memory-card'), [
      ['Усього', bytes(report.memory?.total_bytes)], ['Доступно зараз', bytes(report.memory?.available_bytes)]
    ]);
    const graphics = card('Відеокарти', 'gpu-card');
    if (report.gpu_status !== 'detected' || !report.gpus?.length) {
      graphics.append(element('p', 'Відеокарту не вдалося визначити. Це не означає, що її немає.'));
    }
    for (const gpu of report.gpus || []) {
      const name = element('p', valueOrUnknown(gpu.name)); name.className = 'gpu-name'; graphics.append(name);
      rows(graphics, [
        ['Тип', {integrated: 'Вбудована', discrete: 'Окрема'}[gpu.kind] || unknown],
        ['Власна пам’ять', bytes(gpu.dedicated_total_bytes)], ['Власна пам’ять вільна', bytes(gpu.dedicated_free_bytes)],
        ['Спільна пам’ять', bytes(gpu.shared_total_bytes)]
      ]);
    }
    rows(card('Диск робочого простору', 'disk-card'), [
      ['Усього на диску', bytes(report.disk?.total_bytes)], ['Вільно зараз', bytes(report.disk?.free_bytes)]
    ]);
    byId('software-list').replaceChildren();
    for (const software of report.software || []) {
      const item = element('li');
      const state = software.status === 'detected' ? 'Виявлено' : 'Не виявлено у відомих місцях';
      item.append(element('span', valueOrUnknown(software.label)), element('span', `${state} · версія: ${valueOrUnknown(software.version)}`));
      byId('software-list').append(item);
    }
    if (!report.software?.length) byId('software-list').append(element('li', 'Дані про програми недоступні.'));
    byId('unknown-note').hidden = !(report.unknowns?.length || report.gpu_status !== 'detected');
    byId('inventory').hidden = false;
    byId('download-report').disabled = false;
  }
  function status(message, state = '') {
    byId('status').textContent = message;
    byId('status').dataset.state = state;
  }
  byId('scan-pc').addEventListener('click', async () => {
    const button = byId('scan-pc');
    button.disabled = true; button.textContent = 'Перевіряємо…';
    byId('inventory').setAttribute('aria-busy', 'true');
    status('Читаємо характеристики ПК. Це може зайняти кілька секунд.');
    try {
      const response = await fetch('/api/hardware/scan', {
        method: 'POST', headers: {'Content-Type': 'application/json'}, body: '{}', cache: 'no-store'
      });
      if (response.status === 401) {
        latestReport = null;
        byId('hardware-cards').replaceChildren(); byId('software-list').replaceChildren();
        byId('inventory').hidden = true; byId('download-report').disabled = true;
        location.assign('/login');
        return;
      }
      if (!response.ok) {
        const messages = {403: 'Немає дозволу на цю перевірку. Перевірте доступ до Lokvetia Core.', 409: 'На цьому комп’ютері вже триває перевірка. Спробуйте ще раз після її завершення.'};
        throw new Error(messages[response.status] || 'Перевірка зараз недоступна. Спробуйте ще раз.');
      }
      const report = await response.json();
      if (report.schema_version !== 1 || report.source !== 'local_read_only' || typeof report.observed_at !== 'string') {
        throw new Error('Не вдалося прочитати звіт. Спробуйте ще раз.');
      }
      render(report); latestReport = report;
      status('Перевірку завершено. Звіт показує ресурси на вказаний час.');
    } catch (error) {
      status(`${error.message || 'Не вдалося отримати звіт.'}${latestReport ? ' Нижче залишається попередній звіт; його не оновлено.' : ''}`, 'error');
    } finally {
      button.disabled = false; button.textContent = 'Перевірити ПК';
      byId('inventory').setAttribute('aria-busy', 'false');
    }
  });
  byId('download-report').addEventListener('click', () => {
    if (!latestReport) return;
    const url = URL.createObjectURL(new Blob([JSON.stringify(latestReport, null, 2)], {type: 'application/json'}));
    const link = element('a'); link.href = url; link.download = 'lokvetia-core-hardware.json';
    document.body.append(link); link.click(); link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  });
})();
