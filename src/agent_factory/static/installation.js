(() => {
  const planning = location.pathname.match(/^\/planning\/(\d+)$/);
  const link = document.querySelector('#installation-link');
  if (planning && link) { link.href = '/installation/' + planning[1]; return; }
  if (!document.querySelector('#installation-review')) return;
  const mission = location.pathname.match(/^\/installation\/(\d+)$/)?.[1];
  if (!mission) return;
  const el = id => document.getElementById(id);
  el('plan-link').href = '/planning/' + mission;
  let review = null, canDecide = false, busy = false, pending = null, generation = 0, timer;
  const labels = {already_installed:'Уже встановлено',reuse:'Використати наявне',install:'Окреме встановлення',update:'Нова версія поруч зі старою',manual_action:'Потрібна ваша увага'};
  const reasons = {unsupported_platform:'Цей пакет ще не перевірено для вашої системи.',target_conflict:'Папка вже зайнята. Її вміст не буде замінено.',ambiguous_inventory_location:'Не вдалося однозначно визначити розташування наявної програми.',administrator_unavailable:'Потрібні права адміністратора.',offline_archive_missing:'Для роботи без інтернету потрібен перевірений завантажений пакет.',license_acceptance_required:'Потрібно окремо прийняти умови ліцензії.',dependency_needs_action:'Спочатку потрібно вирішити питання з іншою програмою.',available_disk_space_unknown:'Не вдалося визначити вільне місце.',insufficient_disk_budget:'Для цього плану бракує вільного місця.'};
  const errors = {save_game_plan_first:'Спочатку збережіть план гри.',engine_installation_not_supported:'План встановлення поки доступний лише для Godot.',game_plan_changed:'План гри змінився. Перегляньте його та складіть новий план встановлення.',plan_changed:'Умови встановлення змінилися. Складіть новий план і перегляньте його.',newer_plan_exists:'Уже є новіший план. Оновіть стан.',review_expired:'Час перегляду минув. Складіть новий план.',disk_space_changed:'Вільного місця стало менше. Складіть новий план.',manual_action_required:'Спочатку вирішіть позначені питання.',decision_already_saved:'Рішення вже збережено. Оновіть стан.',command_changed:'Ця дія вже має інший результат. Оновіть стан.'};
  const say = text => { el('status').textContent = text; };
  const make = (tag, text) => { const node = document.createElement(tag); node.textContent = text; return node; };
  const bytes = value => (value / 1024**3).toLocaleString('uk-UA',{maximumFractionDigits:2}) + ' ГіБ';
  const expired = () => !review || Date.now() >= Date.parse(review.expires_at);
  function controls() {
    const locked = busy || !!pending;
    el('prepare').disabled = locked; el('offline').disabled = locked; el('refresh').disabled = busy;
    const decisionLocked = locked || !canDecide || !review || !!review.decision || expired();
    el('approve').disabled = decisionLocked || !el('confirmed').checked || review?.plan.requires_manual_action;
    el('reject').disabled = decisionLocked;
    el('confirmed').disabled = decisionLocked;
    el('retry').hidden = !pending; el('retry').disabled = busy;
  }
  function render() {
    clearTimeout(timer); el('proposal').hidden = !review; el('confirmed').checked = false;
    el('access').textContent = canDecide ? '' : 'Для збереження рішення потрібен вхід власника з правом погодження. Перегляд плану доступний.';
    if (review) {
      const plan = review.plan;
      el('summary').textContent = `Завантаження: ${bytes(plan.download_required_bytes)}. Запланований запас місця: ${bytes(plan.disk_budget_bytes)}. Місце потрібне також для тимчасових копій під час перевірки та встановлення.`;
      el('expires').textContent = expired() ? 'Час перегляду минув. Складіть новий план.' : 'Перегляньте до ' + new Date(review.expires_at).toLocaleTimeString('uk-UA') + '.';
      const changeLabels = new Set((review.changed_fields || []).map(path => {
        if (path === 'context.project') return 'Збережена версія задуму або плану гри.';
        if (path.startsWith('context.')) return 'Комп’ютер або папка проєкту.';
        if (/url|sha256|source_evidence/.test(path)) return 'Джерело або контрольна сума пакета.';
        if (/bytes/.test(path)) return 'Обсяг завантаження, запас або доступність місця.';
        if (/permissions|admin/.test(path)) return 'Потрібні дозволи.';
        if (/license/.test(path)) return 'Умови ліцензії.';
        if (/target|observation/.test(path)) return 'Розташування або наявність програм.';
        return 'Склад, умови або доступність встановлення.';
      }));
      el('changes').hidden = !changeLabels.size; el('change-list').replaceChildren();
      for (const label of changeLabels) el('change-list').append(make('li',label));
      el('packages').replaceChildren(); el('issues').replaceChildren();
      for (const step of plan.steps) {
        const card = make('article',''); card.append(make('h3',(step.package === 'godot-editor' ? 'Godot — редактор' : 'Godot — шаблони збирання') + ' ' + step.version),make('p',labels[step.action]));
        const source = make('a','Офіційний пакет'); source.href = step.url; source.target = '_blank'; source.rel = 'noopener noreferrer'; card.append(source);
        card.append(make('p','Завантаження: ' + bytes(step.download_required_bytes)),make('p','Наявні програми залишаються на місці.'));
        for (const reason of step.reasons) card.append(make('p',reasons[reason] || 'Потрібна додаткова перевірка.'));
        const details = make('details',''); details.append(make('summary','Папка, ліцензія та перевірка пакета'),make('p','Папка всередині проєкту: ' + step.target),make('p',step.license),make('p',step.requires_admin ? 'Потрібні права адміністратора.' : 'Права адміністратора не запитуються.'),make('code','SHA-256: ' + step.sha256));
        const license = make('a','Умови ліцензії'); license.href = step.license_url; license.target='_blank'; license.rel='noopener noreferrer'; details.append(make('p',''),license); card.append(details); el('packages').append(card);
      }
      for (const issue of plan.issues) el('issues').append(make('li',reasons[issue] || 'Потрібна додаткова перевірка.'));
      el('decision').textContent = review.decision ? (review.decision.decision === 'approved' ? 'Погодження збережено. Встановлення не запускалося.' : 'План відхилено. Встановлення не запускалося.') : 'Рішення ще не збережено.';
      if (!expired()) timer = setTimeout(render, Math.min(Date.parse(review.expires_at) - Date.now() + 1, 86400000));
    }
    controls();
  }
  async function refresh() {
    const token = ++generation; busy = true; controls();
    try {
      const response = await fetch('/api/installation-plans/' + mission,{cache:'no-store'});
      if (token !== generation) return;
      if (!response.ok) throw new Error('access');
      const result = await response.json(); if (token !== generation) return;
      review = result.review; canDecide = result.can_decide;
      say(pending ? 'Результат оновлено. Перевірте попередню дію перед новою.' : 'Стан оновлено.');
    } catch (_) { review = null; canDecide = false; say('Не вдалося прочитати стан. Перевірте вхід і повторіть.'); }
    finally { if (token === generation) { busy = false; render(); } }
  }
  async function submit(path, body) {
    if (busy) return;
    pending = {path,body}; busy = true; ++generation; controls();
    try {
      const response = await fetch(path,{method:'POST',headers:{'Content-Type':'application/json','X-Agent-Factory-Confirm':'true'},body:JSON.stringify(body)});
      const result = await response.json();
      if (!response.ok) {
        pending = null; review = null;
        say(response.status === 401 || response.status === 403 ? 'Увійдіть як власник із правом погодження.' : errors[result.detail] || 'Не вдалося зберегти дію. Оновіть стан.');
      } else { review = result; pending = null; say('Збережено. Жодну програму не встановлено.'); }
    } catch (_) { say('Відповідь втрачено. Перевірте результат попередньої дії; нова дія не створюватиметься.'); }
    finally { busy = false; render(); }
  }
  el('prepare').onclick = () => submit('/api/installation-plans/' + mission,{command_id:crypto.randomUUID(),offline:el('offline').checked});
  el('refresh').onclick = refresh; el('confirmed').onchange = controls;
  for (const [id,decision] of [['approve','approved'],['reject','rejected']]) el(id).onclick = () => {
    if (!review || expired() || busy || pending || !canDecide || (decision === 'approved' && !el('confirmed').checked)) { controls(); return; }
    submit('/api/approvals/installation/' + mission,{command_id:crypto.randomUUID(),plan_id:review.id,digest:review.digest,decision});
  };
  el('retry').onclick = () => { if (pending) submit(pending.path,pending.body); };
  refresh();
})();
