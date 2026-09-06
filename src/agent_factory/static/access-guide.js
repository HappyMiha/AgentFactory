const paths = {
  unknown: 'Можна зберегти задум і грати в офлайн-шаблон. Підключення AI потребує окремої перевірки.',
  '12': 'У 12 років можна почати із задуму та шаблону. Для хмарного AI потрібен перевірений шлях із дорослим; зараз він недоступний. Не створюйте акаунт із вигаданим віком.',
  '13-15': 'У 13–15 років правила залежать від сервісу та країни. Разом із дорослим перевірте дозволений шлях; зараз доступні задум і шаблон, без хмарного AI.',
  '16-17': 'У 16–17 років ви ще можете підпадати під правила для неповнолітніх. Вибір цієї групи не відкриває AI; можна зберегти задум і спробувати шаблон.',
  adult: 'Для дорослого потрібна перевірка конкретного акаунта, країни та правил даних оператором. Вибір «18+» не надає доступу; дитячий маршрут перевіряється окремо.'
};
const age = document.querySelector('#age-band');
const showPath = () => { document.querySelector('#age-path').textContent = paths[age.value] || paths.unknown; };
age.addEventListener('change', showPath); showPath();
const idea = document.querySelector('#idea');
document.querySelector('#download-idea').addEventListener('click', () => {
  const notice = document.querySelector('#idea-notice');
  if (!idea.value.trim()) { notice.textContent = 'Напишіть кілька слів про гру.'; idea.focus(); return; }
  const url = URL.createObjectURL(new Blob([idea.value], {type:'text/plain;charset=utf-8'}));
  const link = document.createElement('a'); link.href = url; link.download = 'game-idea.txt';
  document.body.append(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  notice.textContent = 'Задум передано браузеру для завантаження. Перевірте завантажені файли.';
});
let stars = 0;
const renderDemo = () => {
  document.querySelector('#demo-state').textContent = stars === 3 ? 'Усі три зірки зібрано! Шаблон пройдено.' : `Зірки: ${stars} / 3`;
  document.querySelector('#collect-star').disabled = stars === 3;
};
document.querySelector('#collect-star').addEventListener('click', () => { stars = Math.min(3, stars + 1); renderDemo(); });
document.querySelector('#reset-demo').addEventListener('click', () => { stars = 0; renderDemo(); });
window.addEventListener('pagehide', () => { idea.value = ''; age.value = 'unknown'; showPath(); });
async function loadCatalog() {
  const notice = document.querySelector('#catalog-notice');
  try {
    const response = await fetch('/api/connector-eligibility', {cache:'no-store'});
    if (!response.ok) throw new Error();
    const data = await response.json();
    notice.textContent = `Перевірено: ${data.checked_at}. Наступна перевірка до: ${data.review_due}. ${data.current ? 'Підключення потребує окремого дозволу.' : 'Огляд застарів: нове підключення закрите до повторної перевірки.'}`;
    const list = document.querySelector('#connectors'); list.replaceChildren();
    for (const item of data.connectors) {
      const card = document.createElement('section'); card.className = 'card';
      const title = document.createElement('h3'); title.textContent = item.title; card.append(title);
      for (const text of [item.requirements, item.privacy]) { const p = document.createElement('p'); p.textContent = text; card.append(p); }
      for (const source of item.sources) {
        const p = document.createElement('p'); const a = document.createElement('a');
        const url = new URL(source.url); if (url.protocol !== 'https:') continue;
        a.href = url.href; a.textContent = source.title; a.rel = 'noreferrer noopener'; a.target = '_blank';
        p.append(a); card.append(p);
      }
      list.append(card);
    }
  } catch { notice.textContent = 'Не вдалося завантажити правила. Нове підключення недоступне; задум і офлайн-шаблон працюють.'; }
}
loadCatalog();
