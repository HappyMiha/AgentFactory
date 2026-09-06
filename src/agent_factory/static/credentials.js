const notice = document.querySelector('#notice');
const secretInput = document.querySelector('#secret');
let busy = false;
let supported = false;
function say(text) { notice.textContent = text; }
function failure(status) { return status === 401 ? 'Увійдіть, щоб керувати доступом.' : status === 403 ? 'Потрібні права власника операцій і дозвіл керувати доступом.' : 'Не вдалося виконати дію. Перевірте доступність сховища Windows і повторіть.'; }
async function refresh() {
  try {
    const response = await fetch('/api/credential-connections', {cache:'no-store'});
    if (!response.ok) { say(failure(response.status)); return; }
    const data = await response.json();
    supported = data.supported;
    document.querySelector('#save').disabled = !supported || busy;
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
  } catch { say('З’єднання втрачено. Повторіть оновлення.'); }
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
    finally { busy = false; document.querySelector('#save').disabled = !supported; }
  }, {once:true});
}
document.querySelector('#connect').addEventListener('submit', async event => {
  event.preventDefault(); if (busy) return;
  busy = true; document.querySelector('#save').disabled = true;
  let body = JSON.stringify({provider:document.querySelector('#provider').value, secret:secretInput.value, confirmed:document.querySelector('#confirmed').checked});
  secretInput.value = ''; document.querySelector('#confirmed').checked = false;
  try {
    const response = await fetch('/api/credential-connections', {method:'POST',headers:{'Content-Type':'application/json','X-Agent-Factory-Confirm':'true'},body});
    body = '';
    if (!response.ok) { say(failure(response.status)); return; }
    say('Ключ збережено у Windows. Запуск AI потребує окремого дозволу.');
    await refresh();
  } catch { say('Відповідь втрачено. Оновіть список перед повторним введенням ключа.'); }
  finally { body = ''; busy = false; document.querySelector('#save').disabled = !supported; }
});
window.addEventListener('pagehide', () => { secretInput.value = ''; });
document.querySelector('#refresh').addEventListener('click', refresh);
refresh();
