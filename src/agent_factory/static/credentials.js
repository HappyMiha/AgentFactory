const notice = document.querySelector('#notice');
const secretInput = document.querySelector('#secret');
let busy = false;
let supported = false;
let setup = {};
let expiryTimer;
let refreshGeneration = 0;
let catalog = null;
const productSelect = document.querySelector('#connection-product');
const catalogCurrent = () => catalog?.current === true && Date.now() >= Date.parse(catalog.reviewed_on) && Date.now() < Date.parse(catalog.review_due);
function invalidateSetup() { refreshGeneration++; setup = {}; catalog = null; updateSetup(); }
const canSetUp = provider => setup[provider]?.allowed === true && Date.parse(setup[provider].expires_at) > Date.now();
function updateSetup() {
  clearTimeout(expiryTimer);
  const allowed = supported && canSetUp(document.querySelector('#provider').value);
  const deadlines = Object.values(setup).filter(item => item.allowed === true).map(item => Date.parse(item.expires_at) - Date.now()).filter(ms => ms > 0);
  if (catalogCurrent()) deadlines.push(Date.parse(catalog.review_due) - Date.now());
  if (deadlines.length) expiryTimer = setTimeout(updateSetup, Math.min(...deadlines, 86400000) + 1);
  document.querySelector('#connect').hidden = !Object.keys(setup).some(canSetUp);
  secretInput.disabled = !allowed || busy;
  document.querySelector('#save').disabled = !allowed || busy;
  if (!allowed) { secretInput.value = ''; document.querySelector('#confirmed').checked = false; }
  document.querySelector('#eligibility-notice').textContent = allowed
    ? 'Перевірка дорослого для цього підключення чинна. Збереження ключа не дозволяє дитячий доступ, запуск чи витрати.'
    : 'Нове підключення закрите до перевірки дорослого, акаунта та правил даних. Задум і офлайн-демо доступні за посиланням вище.';
  renderGuide();
}
function renderGuide() {
  const root = document.querySelector('#connection-guide'); root.replaceChildren();
  productSelect.disabled = !catalog || busy;
  const guideNotice = document.querySelector('#connection-guide-notice');
  if (!catalog) { guideNotice.textContent = 'Інструкції недоступні. Оновіть стан після перевірки доступу.'; return; }
  guideNotice.textContent = catalogCurrent() ? catalog.notice : 'Інструкції потребують нового огляду. Вибір підключення за цими порадами призупинено.';
  const make = (tag, text) => { const node = document.createElement(tag); node.textContent = text; return node; };
  root.append(make('p', `Огляд ${catalog.reviewed_on}; повторна перевірка до ${catalog.review_due}.`));
  const product = catalog.products.find(item => item.id === productSelect.value);
  if (!product || !catalogCurrent()) return;
  root.append(make('h3', product.title), make('p', product.explanation));
  const steps = make('ol', ''); for (const step of product.steps) steps.append(make('li', step)); root.append(steps);
  for (const url of product.sources) {
    const link = make('a', 'Офіційна інструкція: ' + new URL(url).hostname);
    link.href = url; link.target = '_blank'; link.rel = 'noopener noreferrer';
    const paragraph = make('p', ''); paragraph.append(link); root.append(paragraph);
  }
  root.append(make('p', 'Вхід, залишок коштів, доступ до моделі, написання коду та незалежна перевірка тут ще не перевірялися.'));
  if (product.key_storage_option) {
    const button = make('button', 'Перейти до поля ключа'); button.type = 'button';
    button.disabled = busy || !supported || !canSetUp(product.provider);
    if (button.disabled) root.append(make('p', 'Поле ключа стане доступним після перевірки дорослого й акаунта на ПК із підтримуваним захищеним сховищем.'));
    button.onclick = () => {
      if (!catalogCurrent() || busy || !supported || !canSetUp(product.provider)) { renderGuide(); return; }
      secretInput.value = ''; document.querySelector('#confirmed').checked = false;
      document.querySelector('#provider').value = product.provider; updateSetup(); secretInput.focus();
    };
    root.append(button);
  }
}
productSelect.onchange = () => { secretInput.value = ''; document.querySelector('#confirmed').checked = false; renderGuide(); };
function say(text) { notice.textContent = text; }
function failure(status) { return status === 401 ? 'Увійдіть, щоб керувати доступом.' : status === 403 ? 'Потрібні права власника операцій і дозвіл керувати доступом.' : 'Не вдалося виконати дію. Перевірте доступність сховища Windows і повторіть.'; }
async function refresh() {
  const generation = ++refreshGeneration;
  catalog = null; renderGuide();
  try {
    const response = await fetch('/api/credential-connections', {cache:'no-store'});
    if (generation !== refreshGeneration) return;
    if (!response.ok) { setup = {}; updateSetup(); say(failure(response.status)); return; }
    const data = await response.json();
    if (generation !== refreshGeneration) return;
    catalog = data.catalog || null;
    const selected = productSelect.value; productSelect.replaceChildren(new Option('Оберіть свій варіант', ''));
    for (const product of catalog?.products || []) productSelect.append(new Option(product.title, product.id));
    productSelect.value = selected;
    supported = data.supported; setup = data.setup || {}; updateSetup();
    if (!data.supported) say('Збереження ключів підтримується лише у Windows. Незахищеного запасного сховища немає.');
    const list = document.querySelector('#connections'); list.replaceChildren();
    for (const item of data.connections) {
      const card = document.createElement('section');
      const label = document.createElement('p');
      label.textContent = `${item.provider} · ${item.status === 'active' ? 'Збережено' : item.status === 'pending' ? 'Збереження не завершено' : 'Відключено'} · ${item.id.slice(0,8)}`;
      const button = document.createElement('button'); button.type = 'button';
      button.textContent = item.status === 'active' ? 'Відключити' : 'Повторити видалення зі сховища';
      button.addEventListener('click', () => disconnect(item.id));
      card.append(label, button); list.append(card);
    }
    if (!data.connections.length) list.textContent = 'Збережених підключень ще немає.';
  } catch {
    if (generation !== refreshGeneration) return;
    setup = {}; updateSetup(); say('З’єднання втрачено. Повторіть оновлення.');
  }
}
async function disconnect(id) {
  if (busy) return;
  const dialog = document.querySelector('#disconnect-dialog'); dialog.returnValue = '';
  dialog.showModal();
  dialog.addEventListener('close', async () => {
    if (dialog.returnValue !== 'confirm' || busy) return;
    busy = true;
    try {
      const response = await fetch(`/api/credential-connections/${encodeURIComponent(id)}`, {method:'DELETE',headers:{'X-Agent-Factory-Confirm':'true'}});
      if (!response.ok) { say(failure(response.status)); return; }
      const data = await response.json();
      say(data.os_removal_pending ? 'Доступ заблоковано. Видалення зі сховища не завершилося; повторіть видалення.' : 'Локальний доступ відключено. Відкличте ключ у провайдера, щоб вимкнути інші копії.');
      await refresh();
    } catch { say('Відповідь втрачено. Оновіть стан і за потреби повторіть відключення.'); }
    finally { busy = false; updateSetup(); }
  }, {once:true});
}
document.querySelector('#connect').addEventListener('submit', async event => {
  event.preventDefault(); if (busy || !supported || !canSetUp(document.querySelector('#provider').value)) return;
  busy = true; document.querySelector('#save').disabled = true;
  let body = JSON.stringify({provider:document.querySelector('#provider').value, secret:secretInput.value, confirmed:document.querySelector('#confirmed').checked});
  secretInput.value = ''; document.querySelector('#confirmed').checked = false;
  try {
    const response = await fetch('/api/credential-connections', {method:'POST',headers:{'Content-Type':'application/json','X-Agent-Factory-Confirm':'true'},body});
    body = '';
    if (!response.ok) {
      if (response.status === 403) invalidateSetup();
      say(failure(response.status)); return;
    }
    say('Ключ збережено у Windows. Запуск AI потребує окремого дозволу.');
    await refresh();
  } catch { say('Відповідь втрачено. Оновіть список перед повторним введенням ключа.'); }
  finally { body = ''; busy = false; updateSetup(); }
});
window.addEventListener('pagehide', () => { secretInput.value = ''; });
document.querySelector('#refresh').addEventListener('click', refresh);
document.querySelector('#provider').addEventListener('change', () => { secretInput.value = ''; updateSetup(); });
refresh();
