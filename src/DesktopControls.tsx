import { useEffect, useState } from 'react';
import './desktop.css';
type API=(path:string,options?:RequestInit)=>Promise<any>;
export type Activity={steps:{label:string;status:string;evidence?:string}[];approval?:{kind?:string;nonce:string;label:string;window:string;reason:string;text:string;element?:{name:string;value?:string};image?:string;x:number;y:number};notice?:string};
export function DesktopActivity({value,onApprove,onStop}:{value:Activity;onApprove:(nonce:string,allow:boolean)=>Promise<void>;onStop:()=>void}){
  const [busy,setBusy]=useState(false),[error,setError]=useState('');
  const approval=value.approval;
  useEffect(()=>{setBusy(false);setError('');},[approval?.nonce]);
  if(!value.steps.length&&!approval&&!value.notice)return null;
  const active=value.steps.some(s=>s.status==='running'||s.status==='waiting');
  return <section className="desktop-activity" aria-label="Действия на компьютере" aria-live="polite">
    <div className="desktop-activity-heading"><strong>{approval?'Нужно ваше подтверждение':active?'Выполняю действия':'Результат действий'}</strong>{active&&<button onClick={onStop}>Стоп</button>}</div>
    <ol>{value.steps.map((s,i)=><li key={i} data-status={s.status}><span>{s.status==='done'?'✓':s.status==='running'?'◌':s.status==='stopped'?'−':i+1}</span><span title={s.evidence}>{s.label}</span></li>)}</ol>
    {value.notice&&<p>{value.notice}</p>}
    {approval&&<div className="desktop-approval"><strong>{approval.label}</strong><p>Окно: {approval.window}</p>{approval.element?.name&&<p>Элемент: {approval.element.name}</p>}<p>{approval.reason}</p>{approval.text&&<blockquote>{approval.text}</blockquote>}
      {approval.image&&<div className="approval-image"><img alt="Окно перед нажатием" src={'data:image/jpeg;base64,'+approval.image}/><i style={{left:approval.x*100+'%',top:approval.y*100+'%'}}/></div>}
      <div className="desktop-actions"><button className="primary-button" disabled={busy} onClick={async()=>{setBusy(true);try{await onApprove(approval.nonce,true);}catch(e){setError((e as Error).message);setBusy(false);}}}>{approval.kind==='telegram_message'?'Отправить сообщение':'Подтвердить действие'}</button><button disabled={busy} onClick={()=>{void onApprove(approval.nonce,false).catch(e=>setError(e.message));}}>{approval.kind==='telegram_message'?'Нет':'Отмена'}</button></div>{error&&<p role="alert">{error}</p>}
    </div>}
  </section>;
}
type ModelSettings={model:string;vision:boolean;choices:string[];installed:string[];ai_mode:'local'|'hybrid'|'codex_vision';cloud_model:string;vision_provider:'ollama'|'codex';local_fallback:boolean;image_optimization:boolean;codex:{status:string;authenticated:boolean;version:string};error?:string;download:{status:string;model?:string;percent?:number;error?:string}};
export function DesktopSettings({api}:{api:API}){
  const [data,setData]=useState<ModelSettings>(),[error,setError]=useState(''),[busy,setBusy]=useState(false);
  async function refresh(){try{setData(await api('/desktop/settings'));}catch(e){setError((e as Error).message);}}
  useEffect(()=>{void refresh();const t=setInterval(refresh,3000);return()=>clearInterval(t);},[]);
  async function save(model:string,vision:boolean,changes:Partial<ModelSettings>={}){setBusy(true);setError('');try{await api('/desktop/settings',{method:'POST',body:JSON.stringify({model,vision,...changes})});await refresh();}catch(e){setError((e as Error).message);}finally{setBusy(false);}}
  const statuses:Record<string,string>={connected:'Подключён через ChatGPT',not_authenticated:'Нужен вход через ChatGPT',unavailable:'Недоступен',usage_limit:'Достигнут лимит подписки',timeout:'Время ожидания истекло',invalid_response:'Некорректный ответ'};
  const cloudVision=data?.ai_mode==='codex_vision'||data?.ai_mode==='hybrid'&&data.vision_provider==='codex';
  return <section className="settings-card desktop-settings"><div className="settings-card-heading"><div><h2>Управление компьютером</h2><p>Обычные команды выполняются локально, без нейросети.</p></div></div>{data&&<>
    <label className="desktop-model-select">Режим AI<select aria-label="Режим AI" value={data.ai_mode} disabled={busy} onChange={e=>void save(data.model,data.vision,{ai_mode:e.target.value as ModelSettings['ai_mode']})}><option value="local">Local only · только на этом ПК</option><option value="hybrid">Hybrid · рекомендуется</option><option value="codex_vision">Codex vision · анализ экрана</option></select></label>
    {data.ai_mode!=='local'&&<>
      <label className="desktop-model-select">Анализ экрана<select aria-label="Провайдер анализа экрана" value={cloudVision?'codex':'ollama'} disabled={busy||data.ai_mode==='codex_vision'} onChange={e=>void save(data.model,data.vision,{vision_provider:e.target.value as ModelSettings['vision_provider']})}><option value="ollama">Qwen · на этом ПК</option><option value="codex">Codex · через ChatGPT</option></select></label>
      <label className="desktop-model-select">Облачная модель<select aria-label="Облачная модель" value={data.cloud_model} disabled={busy} onChange={e=>void save(data.model,data.vision,{cloud_model:e.target.value})}><option value="gpt-5.6-luna">GPT-5.6 Luna</option><option value="gpt-5.6-terra">GPT-5.6 Terra · сложные задачи</option></select></label>
      <p role="status">Codex: {statuses[data.codex.status]||'Проверяю подключение'}{data.codex.version&&<small> · {data.codex.version}</small>}</p>
      <label className="desktop-vision"><input type="checkbox" checked={data.local_fallback} disabled={busy} onChange={e=>void save(data.model,data.vision,{local_fallback:e.target.checked})}/><span>Локальный fallback<small>Если Codex недоступен, запрос обработает Qwen на этом ПК.</small></span></label>
    </>}
    <label className="desktop-model-select">Модель понимания<select aria-label="Модель понимания" value={data.model} disabled={busy} onChange={e=>void save(e.target.value,data.vision)}>{data.choices.map(m=><option key={m} value={m}>{m.replace('qwen3.5:','Qwen 3.5 ').toUpperCase()}{m.endsWith(':4b')?' · рекомендуется':''}{data.installed.includes(m)?' · установлена':''}</option>)}</select></label>
    {!data.installed.includes(data.model)&&<button className="primary-button" disabled={data.download.status==='downloading'} onClick={async()=>{try{await api('/desktop/download',{method:'POST',body:JSON.stringify({model:data.model,vision:data.vision})});await refresh();}catch(e){setError((e as Error).message);}}}>Скачать выбранную модель</button>}
    {data.download.status==='downloading'&&<p role="status">Загрузка {data.download.model}: {data.download.percent}%</p>}
    <label className="desktop-vision"><input type="checkbox" checked={data.vision} disabled={busy} onChange={e=>void save(data.model,e.target.checked)}/><span>Анализ экрана по команде<small>{cloudVision?'Снимок выбранного окна или монитора отправляется в Codex через подписку ChatGPT.':'Снимки обрабатываются только на этом ПК.'}</small></span></label>
    <label className="desktop-vision"><input type="checkbox" checked={data.image_optimization} disabled={busy} onChange={e=>void save(data.model,data.vision,{image_optimization:e.target.checked})}/><span>Оптимизация изображений<small>Уменьшать общий снимок и увеличивать нужный фрагмент для мелкого текста.</small></span></label>
    <p className="desktop-settings-hint">«Открой калькулятор, перенеси его на второй монитор и разверни». Остановить: «Пятница, стоп» или кнопка «Стоп». Для голосовой остановки включите голосовую активацию.</p>
    {(data.error||data.download.error)&&<p role="alert">{data.error||data.download.error}</p>}</>}{error&&<p role="alert">{error}</p>}
  </section>;
}
