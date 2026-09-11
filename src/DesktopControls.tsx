import { useEffect, useState } from 'react';
import './desktop.css';
type API=(path:string,options?:RequestInit)=>Promise<any>;
export type Activity={steps:{label:string;status:string;evidence?:string}[];approval?:{nonce:string;label:string;window:string;reason:string;text:string;element?:{name:string;value?:string};image?:string;x:number;y:number};notice?:string};
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
      <div className="desktop-actions"><button className="primary-button" disabled={busy} onClick={async()=>{setBusy(true);try{await onApprove(approval.nonce,true);}catch(e){setError((e as Error).message);setBusy(false);}}}>Подтвердить действие</button><button disabled={busy} onClick={()=>{void onApprove(approval.nonce,false).catch(e=>setError(e.message));}}>Отмена</button></div>{error&&<p role="alert">{error}</p>}
    </div>}
  </section>;
}
type ModelSettings={model:string;vision:boolean;choices:string[];installed:string[];error?:string;download:{status:string;model?:string;percent?:number;error?:string}};
export function DesktopSettings({api}:{api:API}){
  const [data,setData]=useState<ModelSettings>(),[error,setError]=useState(''),[busy,setBusy]=useState(false);
  async function refresh(){try{setData(await api('/desktop/settings'));}catch(e){setError((e as Error).message);}}
  useEffect(()=>{void refresh();const t=setInterval(refresh,3000);return()=>clearInterval(t);},[]);
  async function save(model:string,vision:boolean){setBusy(true);setError('');try{await api('/desktop/settings',{method:'POST',body:JSON.stringify({model,vision})});await refresh();}catch(e){setError((e as Error).message);}finally{setBusy(false);}}
  return <section className="settings-card desktop-settings"><div className="settings-card-heading"><div><h2>Управление компьютером</h2><p>Обычные команды — сразу. Сложные — через локальную модель.</p></div></div>{data&&<>
    <label className="desktop-model-select">Модель понимания<select aria-label="Модель понимания" value={data.model} disabled={busy} onChange={e=>void save(e.target.value,data.vision)}>{data.choices.map(m=><option key={m} value={m}>{m.replace('qwen3.5:','Qwen 3.5 ').toUpperCase()}{m.endsWith(':4b')?' · рекомендуется':''}{data.installed.includes(m)?' · установлена':''}</option>)}</select></label>
    {!data.installed.includes(data.model)&&<button className="primary-button" disabled={data.download.status==='downloading'} onClick={async()=>{try{await api('/desktop/download',{method:'POST',body:JSON.stringify({model:data.model,vision:data.vision})});await refresh();}catch(e){setError((e as Error).message);}}}>Скачать выбранную модель</button>}
    {data.download.status==='downloading'&&<p role="status">Загрузка {data.download.model}: {data.download.percent}%</p>}
    <label className="desktop-vision"><input type="checkbox" checked={data.vision} disabled={busy} onChange={e=>void save(data.model,e.target.checked)}/><span>Разрешить снимок окна, когда чтения интерфейса недостаточно<small>Только по вашей команде. Снимки обрабатывает Ollama на этом ПК.</small></span></label>
    <p className="desktop-settings-hint">«Открой калькулятор, перенеси его на второй монитор и разверни». Остановить: «Пятница, стоп» или кнопка «Стоп». Для голосовой остановки включите голосовую активацию.</p>
    {(data.error||data.download.error)&&<p role="alert">{data.error||data.download.error}</p>}</>}{error&&<p role="alert">{error}</p>}
  </section>;
}
