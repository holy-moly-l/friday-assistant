import { AudioLines, Mic, RefreshCw } from 'lucide-react';
import type { WakeStatus } from './useWakeWord';
export const wakeLabels:Record<WakeStatus,string>={off:'Голосовая активация выключена',paused:'Микрофон на паузе',starting:'Подключаю фоновый микрофон…',waiting:'Жду обращения «Пятница»',listening:'Слушаю вашу команду…',transcribing:'Распознаю команду…',error:'Голосовой активации нужно внимание'};
export function WakeSettings({enabled,onChange,status,error,retry}:{enabled:boolean;onChange:(value:boolean)=>void;status:WakeStatus;error:string;retry:()=>void}){
  return <section className="settings-card wake-card"><div className="settings-card-heading"><AudioLines size={22}/><h2>Активация голосом</h2></div>
    <div className="settings-row"><div><strong>Откликаться на «Пятница»</strong><p>Микрофон слушает в фоне, в том числе при свёрнутом окне.</p></div><button className={'toggle '+(enabled?'on':'')} role="switch" aria-checked={enabled} aria-label="Активация по слову Пятница" onClick={()=>onChange(!enabled)}><span/></button></div>
    <div className={'wake-state '+status} role="status"><Mic size={16}/><span>{wakeLabels[status]}</span>{status==='error'&&<button className="outline-button" onClick={retry}><RefreshCw size={14}/>Повторить</button>}</div>
    {error&&<p className="mic-error">{error}</p>}
    <details className="settings-details"><summary>Как давать команды голосом</summary><p>«Пятница, открой проводник». Или назовите имя и произнесите команду в течение 8 секунд.</p><p>«Отмена» отменяет команду. Esc выключает прослушивание. Во время ответа микрофон на паузе; при полном выходе он отключается. Окружающая речь не сохраняется.</p></details>
  </section>;
}
