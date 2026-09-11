import { useMemo, useState } from 'react';
import { ArrowUpRight, Check, ChevronDown, Copy, Search, X } from 'lucide-react';
import { commands } from './commandCatalog';

const normalize=(text:string)=>text.toLocaleLowerCase('ru').replace(/ё/g,'е').replace(/[?!.,:«»]/g,' ').replace(/\s+/g,' ').trim();
const categories=['Все',...new Set(commands.map(c=>c.category))];
const phraseCount=commands.reduce((total,c)=>total+c.phrases.length,0);
type Props={disabled:boolean;onRun:(text:string)=>void;onInsert:(text:string)=>void};
export function CommandLibrary({disabled,onRun,onInsert}:Props){
  const [query,setQuery]=useState(''),[category,setCategory]=useState('Все'),[expanded,setExpanded]=useState<string|null>(null),[copied,setCopied]=useState('');
  const filtered=useMemo(()=>{
    const words=normalize(query).split(' ').filter(Boolean);
    return commands.filter(c=>(category==='Все'||c.category===category)&&words.every(w=>normalize(c.title+' '+c.category+' '+c.description+' '+c.phrases.join(' ')).includes(w)));
  },[query,category]);
  async function copy(id:string,text:string){try{await navigator.clipboard.writeText(text);setCopied(id);}catch{onInsert(text);}}
  return <div className="catalog">
    <div className="search-field catalog-search"><Search size={17}/><input aria-label="Поиск команд" placeholder="Команда, фраза или категория…" value={query} onChange={e=>setQuery(e.target.value)}/>{query&&<button className="icon-button" aria-label="Очистить поиск команд" onClick={()=>setQuery('')}><X size={15}/></button>}</div>
    <div className="catalog-categories" role="group" aria-label="Категория команд">{categories.map(c=><button key={c} aria-pressed={category===c} onClick={()=>setCategory(c)}>{c}</button>)}</div>
    <div className="catalog-results" aria-live="polite">Найдено: {filtered.length} из {commands.length}</div>
    <div className="command-grid catalog-grid">{filtered.map(c=><article className="command-card catalog-card" key={c.id}>
      <div className="catalog-card-top"><span className="command-icon"><c.icon size={21}/></span><small>{c.category}</small></div>
      <h3>{c.title}</h3>
      <div className="catalog-example"><span>«{c.prompt}»</span><button className="icon-button" aria-label={'Скопировать: '+c.title} onClick={()=>copy(c.id,c.prompt)}>{copied===c.id?<Check size={14}/>:<Copy size={14}/>}</button></div>
      <div className="catalog-card-actions"><button className="outline-button" aria-expanded={expanded===c.id} onClick={()=>setExpanded(expanded===c.id?null:c.id)}><ChevronDown size={14}/>Формулировки · {c.phrases.length}</button><button className="catalog-run" disabled={disabled} onClick={()=>c.template?onInsert(c.template):onRun(c.prompt)}>{c.template?'Ввести команду':'Выполнить'}<ArrowUpRight size={15}/></button></div>
      {expanded===c.id&&<div className="catalog-variants"><p>Нажмите на фразу, чтобы подставить её в чат и при необходимости изменить.</p>{c.phrases.map(phrase=><button key={phrase} disabled={disabled} onClick={()=>onInsert(phrase)}>{phrase}<ArrowUpRight size={12}/></button>)}</div>}
    </article>)}</div>
    {!filtered.length&&<div className="empty-state"><Search size={30}/><h2>Команда не найдена</h2><p>Попробуйте другое слово или выберите все категории.</p><button className="outline-button" onClick={()=>{setQuery('');setCategory('Все');}}>Сбросить фильтры</button></div>}
    <details className="settings-details"><summary>Как формулировать команды</summary><p>Можно добавить «Пятница, пожалуйста…» или «Не могла бы ты…». Числа можно говорить словами. Одна команда за сообщение. Все {phraseCount.toLocaleString('ru-RU')} примеров доступны в карточках.</p></details>
  </div>;
}
