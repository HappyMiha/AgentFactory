"use strict";
const $=id=>document.getElementById(id), mission=location.pathname.split('/').pop();
const labels={controls:'Керування',goal:'Умова перемоги',lose_rule:'Невдача або недозволена дія',visual_style:'Візуальний стиль',first_playable:'Малий завершений ігровий цикл',assumptions:'Припущення для перевірки',deferred_scope:'Задум, відкладений до наступних версій',cost_notes:'Витрати, бюджет і невідомі обмеження'};
let current=null,templates={},pending=null,dirty=false,navigationGeneration=0,editGeneration=0;
const el=(tag,text)=>{const n=document.createElement(tag);n.textContent=text;return n;};
for(const [id,title] of Object.entries(labels)){const label=el('label',title);label.htmlFor=id;const field=el('textarea','');field.id=id;field.maxLength=1500;$('text-fields').append(label,field);}
const values=()=>Object.fromEntries(['genre','engine','platform',...Object.keys(labels)].map(id=>[id,$(id).value]));
const fill=fields=>Object.entries(fields).forEach(([id,value])=>$(id).value=value);
async function api(body,revision){
 const response=await fetch('/api/game-planning/'+encodeURIComponent(mission)+(revision?'?revision_id='+revision:''),{method:body?'POST':'GET',headers:body?{'Content-Type':'application/json','X-Agent-Factory-Confirm':'true'}:{},body:body?JSON.stringify(body):undefined,cache:'no-store'});
 if(response.status===401){location.assign('/login');throw Error('Потрібно увійти.');}
 const data=await response.json();
 if(!response.ok){const e=Error(response.status===409?'Джерело або план змінилися. Ваші поля збережені на екрані; скопіюйте їх перед відкриттям останньої версії.':'Запит не виконано. Перевірте доступ і введені дані.');e.definitive=response.status<500;throw e;}
 return data;
}
function render(data){
 current=data;templates=data.templates||templates;fill(data.fields);dirty=false;
 $('source').textContent=data.source_text;$('source-label').textContent=`Початкове джерело, версія ${data.source_version}. План прив’язаний до версії ${data.bound_source_version}.`+(data.source_preview_truncated?' Показано перші 12 000 символів. Повне джерело збережене в Core.':'');
 const historical=data.revision_id!==data.latest_revision_id;
 $('fields').disabled=!data.editable||historical;$('confirmed').checked=false;
 $('notice').textContent=data.stale?'Джерело оновлене. Перевірте всі поля перед новим збереженням.':historical?'Перегляд попередньої незмінної версії.':data.revision_id?'Збережена ручна версія плану.':'Незбережений шаблон. Звірте його зі своїм задумом.';
 $('questions').replaceChildren(...data.questions.map(q=>el('li',(labels[q.field]||q.field)+': '+q.question)));
 if(!data.questions.length)$('questions').append(el('li','Поля заповнені. Це ще не підтверджує правильність припущень або готовність до виконання.'));
 $('history').replaceChildren();for(const revision of data.history){const li=el('li','');const button=el('button','Версія '+revision.revision_number);button.type='button';button.onclick=()=>load(revision.id);li.append(button);$('history').append(li);}
 $('tasks').replaceChildren();for(const task of data.tasks){const card=el('article','');card.append(el('h3',task.title),el('p',task.description));const list=el('ul','');for(const criterion of task.acceptance_criteria)list.append(el('li',criterion));card.append(list,el('p','Залежності: '+(task.dependencies.join(', ')||'немає')),el('p','Перевірка: '+task.validation_method.join(' ')),el('p','Артефакти: '+task.expected_artifacts.join(' ')));const details=el('details','');details.append(el('summary','Зв’язок із джерелом'),el('code',task.source_references.join(' · ')));card.append(details);$('tasks').append(card);}
}
async function load(revision){if(dirty||pending){$('notice').textContent='Є незбережені зміни. Збережіть їх або скопіюйте й перезавантажте сторінку.';return;}const generation=++navigationGeneration,edits=editGeneration;try{const data=await api(null,revision);if(generation!==navigationGeneration)return;if(edits!==editGeneration||dirty||pending){$('notice').textContent='Під час завантаження ви змінили поля. Відповідь відхилено; ваш текст залишився у формі.';return;}render(data);}catch(e){if(generation===navigationGeneration)$('notice').textContent=e.message;}}
$('plan').oninput=()=>{++editGeneration;dirty=true;$('task-note').textContent='Поля змінені. Задачі нижче відповідають попередній версії; збережіть план для їх оновлення.';};
$('use-template').onclick=()=>{++editGeneration;fill(templates[$('genre').value]);dirty=true;$('confirmed').checked=false;$('notice').textContent='Шаблон заповнив поля. Перевірте кожне припущення перед збереженням.';};
$('plan').onsubmit=async event=>{event.preventDefault();if(!$('confirmed').checked){$('notice').textContent='Підтвердьте збереження чернетки.';return;}++navigationGeneration;pending=pending||{fields:values(),command_id:crypto.randomUUID(),expected_revision_id:current.latest_revision_id||0,expected_source_digest:current.source_digest,confirmed:true};$('fields').disabled=true;$('notice').textContent='Збереження…';try{const newer=values(),changed=JSON.stringify(newer)!==JSON.stringify(pending.fields);const data=await api(pending);pending=null;render(data);if(changed){fill(newer);dirty=true;$('notice').textContent='Попередню команду відновлено. Нові зміни залишені у формі; збережіть їх окремо.';}else $('task-note').textContent='Задачі відповідають щойно збереженій версії.';}catch(e){if(e.definitive)pending=null;$('fields').disabled=false;$('notice').textContent=e.message+' Якщо відповідь загубилась, повторне збереження відновить ту саму команду.';}};
$('latest').onclick=()=>load();window.addEventListener('beforeunload',event=>{if(dirty||pending){event.preventDefault();event.returnValue='';}});load();
