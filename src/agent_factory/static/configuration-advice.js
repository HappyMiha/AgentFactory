"use strict";
(() => {
 const node=id=>document.getElementById(id), make=(tag,text)=>{const n=document.createElement(tag);n.textContent=text;return n;};
 let generation=0;
 async function post(url,body){
  const response=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body),cache:'no-store'});
  if(response.status===401){location.assign('/login');throw Error('Потрібно увійти.');}
  if(!response.ok)throw Error(response.status===409?'Перевірка ПК вже виконується. Повторіть пізніше.':'Не вдалося порівняти варіанти. Перевірте доступ і повторіть перевірку ПК.');
  return response.json();
 }
 node('compare-configuration').onclick=async()=>{
  const start=window.gamePlanAdvice.capture();
  if(!start.editable){node('advice-status').textContent='Відкрийте останню редаговану версію плану.';return;}
  const version=++generation;node('compare-configuration').disabled=true;node('advice-results').replaceChildren();node('advice-status').textContent='Читаємо характеристики ПК…';
  try{
   const report=await post('/api/hardware/scan',{});
   if(version!==generation || start.token!==window.gamePlanAdvice.capture().token)throw Error('Поля або версія змінилися під час перевірки. Повторіть порівняння; ваші зміни збережені у формі.');
   const result=await post('/api/configuration-advice',{fields:start.fields,report});
   if(version!==generation || start.token!==window.gamePlanAdvice.capture().token)throw Error('План змінився. Попередню відповідь відхилено; повторіть порівняння.');
   const root=node('advice-results');root.append(make('p',result.scope_note),make('p',result.target));
   const list=make('ul','');for(const reason of result.reasons)list.append(make('li',reason));root.append(list);
   for(const option of result.options){
    const card=make('article','');card.append(make('h3',option.title+(option.id===result.recommended?' — почніть із цього варіанта':'')),make('p',option.reason));
    const button=make('button','Обрати для чернетки');button.type='button';button.disabled=!option.selectable;
    button.onclick=()=>{
     const age=Date.now()-Date.parse(report.observed_at);
     if(option.id!=='manual' && (!Number.isFinite(age)||age<0||age>900000||new Date().toISOString().slice(0,10)>=result.catalog.review_due)){
      node('advice-status').textContent='Рекомендація застаріла. Повторіть перевірку ПК.';root.replaceChildren();return;
     }
     if(window.gamePlanAdvice.apply(option,start.token)){root.replaceChildren();node('advice-status').textContent='Вибір у формі. Збережіть план після перевірки.';}
     else node('advice-status').textContent='План змінився або бракує місця в нотатках. Ваші поля залишилися; повторіть порівняння.';
    };card.append(button);root.append(card);
   }
   for(const estimate of result.estimates)root.append(make('p',`${estimate.item}: ${estimate.range} Джерело: ${estimate.source}; огляд ${result.catalog.reviewed_on}.`));
   const details=make('details','');details.append(make('summary','Джерела й планові припущення'),make('p',result.catalog.policy_basis));
   for(const source of result.catalog.sources){const link=make('a',source.id);link.href=source.url;link.target='_blank';link.rel='noopener noreferrer';details.append(link,make('p',source.finding));}root.append(details);
   node('advice-status').textContent='Порівняння готове. Це планові варіанти; модель і збірка ще не кваліфіковані.';
  }catch(error){node('advice-results').replaceChildren();node('advice-status').textContent=error.message;}
  finally{node('compare-configuration').disabled=false;}
 };
})();
